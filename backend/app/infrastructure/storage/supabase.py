import json
import logging
import os
import time
from typing import Optional

import requests

from backend.app.infrastructure.storage.base import (
    PAID_INVOICE_EVENT_SELECT,
    PAID_REPORT_SUMMARY_SELECT,
    PAYMENT_EVENT_SUMMARY_SELECT,
    invoice_payment_events,
    normalize_address,
    paid_report_summary_from_row,
    payment_event_from_row,
    wallet_matches,
)

logger = logging.getLogger("QMA-Storage.Supabase")

class SupabaseStorage:
    """Supabase REST storage for payment and entitlement persistence."""

    backend_name = "supabase"

    def __init__(self, *, url: str, service_role_key: str, schema: str = "public", timeout: int = 12):
        self.url = url.rstrip("/")
        self.rest_url = f"{self.url}/rest/v1"
        self.schema = schema
        self.timeout = timeout
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Profile": schema,
            "Content-Profile": schema,
        }

    def _request(self, method: str, table: str, *, params: Optional[dict] = None, json_body=None, prefer: str = ""):
        import time as _time
        import random as _random
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        url = f"{self.rest_url}/{table}"
        max_retries = 3
        last_error = None
        for attempt in range(max_retries):
            try:
                resp = requests.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self.timeout,
                )
                if resp.ok:
                    if resp.status_code == 204 or not resp.text:
                        return None
                    return resp.json()
                error_body = resp.text[:300]
                if (resp.status_code in (500, 502, 503, 504) and "40P01" in error_body) or resp.status_code in (502, 503, 504):
                    last_error = RuntimeError(f"Supabase {method} {table} returned {resp.status_code}: {error_body}")
                    _time.sleep(0.15 * (2 ** attempt) + _random.uniform(0.05, 0.15))
                    continue
                raise RuntimeError(f"Supabase {method} {table} returned {resp.status_code}: {error_body}")
            except (requests.RequestException, TimeoutError) as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    _time.sleep(0.15 * (2 ** attempt) + _random.uniform(0.05, 0.15))
                    continue
                raise RuntimeError(f"Supabase {method} {table} request failed: {exc}") from exc
        raise last_error or RuntimeError(f"Supabase {method} {table} failed after {max_retries} attempts.")

    def rpc(self, fn_name: str, payload: Optional[dict] = None):
        return self._request("POST", f"rpc/{fn_name}", json_body=payload or {})

    def _upsert(self, table: str, rows: list[dict], conflict: str) -> None:
        if not rows:
            return
        self._request(
            "POST",
            table,
            params={"on_conflict": conflict},
            json_body=rows,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def load_payment_events(self) -> list:
        rows = self._request(
            "GET",
            "qma_payment_events",
            params={"select": "event", "order": "paid_at.desc.nullslast", "limit": "5000"},
        ) or []
        return [row.get("event") for row in rows if isinstance(row.get("event"), dict)]

    def load_payment_event_summaries(self, *, limit: int = 5000) -> list:
        rows = self._request(
            "GET",
            "qma_payment_events",
            params={
                "select": PAYMENT_EVENT_SUMMARY_SELECT,
                "order": "paid_at.desc.nullslast",
                "limit": str(limit),
            },
        ) or []
        return [payment_event_from_row(row) for row in rows]

    def load_payment_events_for_wallet(self, address: str, *, limit: int = 5000) -> list:
        events = [event for event in self.load_payment_events() if wallet_matches(event, address)]
        return sorted(events, key=lambda item: item.get("paid_at") or 0, reverse=True)[:limit]

    def save_payment_events(self, events: list) -> None:
        rows = []
        for event in events:
            key = event_key(event)
            if not key:
                continue
            rows.append({
                "event_id": key,
                "invoice_id": event.get("invoice_id"),
                "settlement_id": event.get("settlement_id"),
                "payer_address": normalize_address(event.get("payer_address")),
                "symbol": event.get("symbol"),
                "tier": event.get("tier"),
                "provider_id": event.get("provider_id", "funding_memory"),
                "amount_usdc": event.get("amount_usdc"),
                "gateway_status": event.get("gateway_status"),
                "transaction_hash": event.get("transaction_hash"),
                "explorer_url": event.get("explorer_url"),
                "paid_at": event.get("paid_at"),
                "event": event,
            })
        self._upsert("qma_payment_events", rows, "event_id")

    def save_single_payment_event(self, event: dict) -> None:
        key = event_key(event)
        if not key:
            return
        row = {
            "event_id": key,
            "invoice_id": event.get("invoice_id"),
            "settlement_id": event.get("settlement_id"),
            "payer_address": normalize_address(event.get("payer_address")),
            "symbol": event.get("symbol"),
            "tier": event.get("tier"),
            "provider_id": event.get("provider_id", "funding_memory"),
            "amount_usdc": event.get("amount_usdc"),
            "gateway_status": event.get("gateway_status"),
            "transaction_hash": event.get("transaction_hash"),
            "explorer_url": event.get("explorer_url"),
            "paid_at": event.get("paid_at"),
            "event": event,
        }
        self._upsert("qma_payment_events", [row], "event_id")

    def load_paid_reports(self) -> dict:
        rows = self._request(
            "GET",
            "qma_paid_reports",
            params={"select": "entitlement_id,entitlement", "order": "saved_at.desc.nullslast", "limit": "5000"},
        ) or []
        records = {}
        for row in rows:
            record = row.get("entitlement")
            entitlement_id = row.get("entitlement_id") or (record or {}).get("entitlement_id")
            if entitlement_id and isinstance(record, dict):
                records[entitlement_id] = record
        return records

    def load_paid_reports_for_wallet(
        self,
        address: str,
        *,
        symbol: Optional[str] = None,
        provider_id: Optional[str] = None,
        limit: int = 5000,
    ) -> dict:
        symbol_filter = str(symbol or "").strip().upper()
        records = {
            entitlement_id: record
            for entitlement_id, record in self.load_paid_reports().items()
            if wallet_matches(record, address)
            and (not symbol_filter or str(record.get("symbol", "")).upper() == symbol_filter)
            and (not provider_id or record.get("provider_id", "funding_memory") == provider_id)
        }
        ordered = sorted(
            records.items(),
            key=lambda item: item[1].get("paid_at") or item[1].get("saved_at") or 0,
            reverse=True,
        )
        records = dict(ordered[:limit])
        return records

    def load_paid_report_summaries(self, *, limit: int = 5000) -> list:
        rows = self._request(
            "GET",
            "qma_paid_reports",
            params={
                "select": PAID_REPORT_SUMMARY_SELECT,
                "order": "saved_at.desc.nullslast",
                "limit": str(limit),
            },
        ) or []
        return [paid_report_summary_from_row(row) for row in rows]

    def load_paid_report_summaries_for_wallet(
        self,
        address: str,
        *,
        symbol: Optional[str] = None,
        provider_id: Optional[str] = None,
        limit: int = 5000,
    ) -> list:
        return [
            paid_report_summary_from_row({
                "entitlement_id": entitlement_id,
                "entitlement": record,
            })
            for entitlement_id, record in self.load_paid_reports_for_wallet(
                address,
                symbol=symbol,
                provider_id=provider_id,
                limit=limit,
            ).items()
        ]

    def load_paid_report_by_id(self, address: str, entitlement_id: str) -> Optional[dict]:
        record = self.load_paid_reports().get(entitlement_id)
        return record if wallet_matches(record, address) else None

    def is_settlement_id_claimed(self, settlement_id: str, exclude_invoice_id: Optional[str] = None) -> bool:
        if not settlement_id:
            return False
        for table, binding in (
            ("qma_invoices", {"settlement_id": f"eq.{settlement_id}"}),
            ("qma_invoices", {"invoice->split->legs": "cs." + json.dumps([{"settlement_id": settlement_id}])}),
            ("qma_payment_events", {"settlement_id": f"eq.{settlement_id}"}),
        ):
            params = {"select": "invoice_id", "limit": "1", **binding}
            if exclude_invoice_id:
                params["invoice_id"] = f"neq.{exclude_invoice_id}"
            try:
                rows = self._request("GET", table, params=params) or []
            except RuntimeError as exc:
                if "400" in str(exc) or "PGRST100" in str(exc):
                    continue
                raise
            if any(row.get("invoice_id") != exclude_invoice_id for row in rows):
                return True
        return False

    def claim_settlement_for_invoice(self, settlement_id: str, invoice_id: str, invoices_db: Optional[dict] = None) -> bool:
        if not settlement_id or not invoice_id:
            return False
        if self.is_settlement_id_claimed(settlement_id, exclude_invoice_id=invoice_id):
            return False
        for table, binding in (
            ("qma_invoices", {"settlement_id": f"eq.{settlement_id}"}),
            ("qma_payment_events", {"settlement_id": f"eq.{settlement_id}"}),
            ("qma_paid_reports", {"settlement_id": f"eq.{settlement_id}"}),
        ):
            params = {"select": "invoice_id", "limit": "1", **binding}
            if table == "qma_invoices":
                params["invoice_id"] = f"neq.{invoice_id}"
            try:
                rows = self._request("GET", table, params=params) or []
                if rows:
                    return False
            except Exception:
                pass
        try:
            self._request("PATCH", "qma_invoices", params={"invoice_id": f"eq.{invoice_id}"}, json={"settlement_id": settlement_id})
            if invoices_db and invoice_id in invoices_db:
                invoices_db[invoice_id]["settlement_id"] = settlement_id
            return True
        except Exception:
            return False

    def save_paid_reports(self, reports: dict) -> None:
        rows = []
        for entitlement_id, record in reports.items():
            if not isinstance(record, dict):
                continue
            rows.append({
                "entitlement_id": entitlement_id,
                "payer_address": normalize_address(record.get("payer_address")),
                "symbol": record.get("symbol"),
                "tier": record.get("tier"),
                "provider_id": record.get("provider_id", "funding_memory"),
                "query_hash": record.get("query_hash"),
                "settlement_id": record.get("settlement_id"),
                "paid_at": record.get("paid_at"),
                "saved_at": record.get("saved_at"),
                "entitlement": record,
            })
        self._upsert("qma_paid_reports", rows, "entitlement_id")

    def save_single_paid_report(self, entitlement_id: str, record: dict) -> None:
        if not entitlement_id or not isinstance(record, dict):
            return
        row = {
            "entitlement_id": entitlement_id,
            "payer_address": normalize_address(record.get("payer_address")),
            "symbol": record.get("symbol"),
            "tier": record.get("tier"),
            "provider_id": record.get("provider_id", "funding_memory"),
            "query_hash": record.get("query_hash"),
            "settlement_id": record.get("settlement_id"),
            "paid_at": record.get("paid_at"),
            "saved_at": record.get("saved_at"),
            "entitlement": record,
        }
        self._upsert("qma_paid_reports", [row], "entitlement_id")

    def load_creator_claims(self) -> list:
        records = []
        offset = 0
        while True:
            try:
                rows = self._request("GET", "qma_creator_claims", params={
                    "select": "claim", "order": "claim_id.asc", "limit": "500", "offset": str(offset),
                }) or []
            except RuntimeError as exc:
                if "404" in str(exc) or "PGRST205" in str(exc):
                    return []
                raise
            records.extend(row["claim"] for row in rows)
            if len(rows) < 500:
                return records
            offset += len(rows)

    def load_wallet_spending_events(self, address: str) -> list:
        result = []
        for table, field in (("qma_invoices", "invoice"), ("qma_payment_events", "event")):
            offset = 0
            while True:
                try:
                    rows = self._request("GET", table, params={
                        "payer_address": f"eq.{normalize_address(address)}", "select": field,
                        "order": "invoice_id.asc", "limit": "500", "offset": str(offset),
                    }) or []
                except Exception as exc:
                    logger.warning(f"Could not query {table} for wallet spending events: {exc}")
                    break
                result.extend(row[field] for row in rows if field in row)
                if len(rows) < 500:
                    break
                offset += len(rows)
        return result

    def save_creator_claim(self, record: dict) -> None:
        try:
            self._upsert("qma_creator_claims", [{
                "claim_id": record["claim_id"], "claim": record,
            }], "claim_id")
        except Exception as exc:
            logger.warning(f"Could not save creator claim to Supabase: {exc}")

    def reserve_withdrawal(self, operation_id: str, operation: dict) -> dict:
        try:
            self._request("POST", "qma_withdrawals", params={"on_conflict": "operation_id"},
                          json_body=[{"operation_id": operation_id, "operation": operation}],
                          prefer="resolution=ignore-duplicates,return=minimal")
            rows = self._request("GET", "qma_withdrawals", params={
                "operation_id": f"eq.{operation_id}", "select": "operation", "limit": "1",
            })
            if rows and "operation" in rows[0]:
                return rows[0]["operation"]
        except Exception as exc:
            logger.warning(f"Supabase withdrawals table unavailable: {exc}")
        if not hasattr(self, "_withdrawals"):
            self._withdrawals = {}
        return self._withdrawals.setdefault(operation_id, operation)

    def save_withdrawal(self, operation_id: str, operation: dict) -> None:
        try:
            self._upsert("qma_withdrawals", [{"operation_id": operation_id, "operation": operation}], "operation_id")
        except Exception as exc:
            logger.warning(f"Supabase withdrawals table unavailable: {exc}")
        if not hasattr(self, "_withdrawals"):
            self._withdrawals = {}
        self._withdrawals[operation_id] = operation

    def load_invoices(self) -> dict:
        rows = self._request(
            "GET",
            "qma_invoices",
            params={"select": "invoice_id,invoice", "order": "created_at.desc.nullslast", "limit": "2000"},
        ) or []
        invoices = {}
        for row in rows:
            invoice = row.get("invoice")
            invoice_id = row.get("invoice_id") or (invoice or {}).get("invoice_id")
            if invoice_id and isinstance(invoice, dict):
                invoices[invoice_id] = invoice
        return invoices

    def load_paid_invoices_for_wallet(self, address: str, *, limit: int = 5000) -> dict:
        invoices = {
            invoice_id: invoice
            for invoice_id, invoice in self.load_invoices().items()
            if isinstance(invoice, dict)
            and invoice.get("status") == "paid"
            and wallet_matches(invoice, address)
        }
        ordered = sorted(
            invoices.items(),
            key=lambda item: item[1].get("paid_at") or item[1].get("created_at") or 0,
            reverse=True,
        )
        return dict(ordered[:limit])

    def load_paid_invoice_events(self, *, limit: int = 5000) -> list:
        rows = self._request(
            "GET",
            "qma_invoices",
            params={
                "select": PAID_INVOICE_EVENT_SELECT,
                "status": "eq.paid",
                "order": "paid_at.desc.nullslast",
                "limit": str(limit),
            },
        ) or []
        events = []
        for row in rows:
            invoice = row.get("invoice") if isinstance(row.get("invoice"), dict) else {}
            events.extend(invoice_payment_events({
                **invoice,
                "invoice_id": row.get("invoice_id") or invoice.get("invoice_id"),
                "settlement_id": row.get("settlement_id") or invoice.get("settlement_id"),
                "payer_address": row.get("payer_address") or invoice.get("payer_address"),
                "symbol": row.get("symbol") or invoice.get("symbol"),
                "tier": row.get("tier") or invoice.get("tier"),
                "provider_id": row.get("provider_id") or invoice.get("provider_id", "funding_memory"),
                "query_hash": row.get("query_hash") or invoice.get("query_hash"),
                "paid_at": row.get("paid_at") if row.get("paid_at") is not None else invoice.get("paid_at"),
            }))
        return events

    def save_invoice(self, invoice: dict) -> None:
        invoice_id = invoice.get("invoice_id")
        if not invoice_id:
            return
        self._upsert("qma_invoices", [{
            "invoice_id": invoice_id,
            "status": invoice.get("status"),
            "settlement_id": invoice.get("settlement_id"),
            "payer_address": normalize_address(invoice.get("payer_address")),
            "symbol": invoice.get("symbol"),
            "tier": invoice.get("tier"),
            "provider_id": invoice.get("provider_id", "funding_memory"),
            "query_hash": invoice.get("query_hash"),
            "created_at": invoice.get("created_at"),
            "expires_at": invoice.get("expires_at"),
            "paid_at": invoice.get("paid_at"),
            "invoice": invoice,
        }], "invoice_id")

    def load_creator_applications(self) -> dict:
        try:
            rows = self._request(
                "GET",
                "qma_creator_applications",
                params={"select": "application_id,application", "order": "created_at.desc.nullslast", "limit": "1000"},
            ) or []
        except RuntimeError:
            return {}
        applications = {}
        for row in rows:
            application = row.get("application")
            application_id = row.get("application_id") or (application or {}).get("application_id")
            if application_id and isinstance(application, dict):
                applications[application_id] = application
        return applications

    def save_creator_application(self, application: dict) -> None:
        application_id = application.get("application_id")
        if not application_id:
            return
        self._upsert("qma_creator_applications", [{
            "application_id": application_id,
            "creator_wallet": normalize_address(application.get("creator_wallet")),
            "provider_id": application.get("provider_id"),
            "status": application.get("status", "pending"),
            "created_at": application.get("created_at"),
            "updated_at": application.get("updated_at"),
            "application": application,
        }], "application_id")

    def load_provider_controls(self) -> dict:
        try:
            rows = self._request(
                "GET",
                "qma_provider_controls",
                params={"select": "provider_id,control", "limit": "1000"},
            ) or []
        except RuntimeError:
            return {}
        controls = {}
        for row in rows:
            provider_id = row.get("provider_id")
            control = row.get("control")
            if provider_id and isinstance(control, dict):
                controls[provider_id] = control
        return controls

    def save_provider_control(self, provider_id: str, control: dict) -> None:
        if not provider_id:
            return
        self._upsert("qma_provider_controls", [{
            "provider_id": provider_id,
            "enabled": control.get("enabled"),
            "updated_at": control.get("updated_at"),
            "control": control,
        }], "provider_id")

    def load_incidents(self) -> list:
        try:
            rows = self._request("GET", "agent_incidents", params={"order": "created_at.asc", "limit": "1000"}) or []
            return [r.get("incident") or r for r in rows]
        except Exception as exc:
            logger.warning(f"Could not load incidents from Supabase: {exc}")
            raise

    def save_incident(self, incident: dict) -> None:
        try:
            self._upsert("agent_incidents", [incident], "incident_id")
        except Exception as exc:
            logger.warning(f"Could not save incident to Supabase: {exc}")
            raise

    def load_earn_vault_positions(self) -> dict:
        try:
            rows = self._request("GET", "earn_vault_positions", params={"limit": "1000"}) or []
            positions = {}
            for r in rows:
                key = f"{r.get('wallet')}:{r.get('vault_id')}"
                positions[key] = r
            return positions
        except Exception as exc:
            logger.warning(f"Could not load earn vault positions from Supabase: {exc}")
            return {}

    def save_earn_vault_position(self, position: dict) -> None:
        try:
            key = f"{position.get('wallet')}:{position.get('vault_id')}"
            row = dict(position)
            row["position_id"] = key
            self._upsert("earn_vault_positions", [row], "position_id")
        except Exception as exc:
            logger.warning(f"Could not save earn vault position to Supabase: {exc}")

    def save_earn_vault_positions(self, positions: dict) -> None:
        for pos in positions.values():
            if isinstance(pos, dict):
                self.save_earn_vault_position(pos)

    def load_euthyna_records(
        self,
        limit: int = 50,
        action_filter: Optional[str] = None,
        actor_filter: Optional[str] = None,
        only_live: bool = False,
    ) -> list:
        try:
            params = {"order": "created_at.desc", "limit": str(limit)}
            if only_live:
                params["tx_hash"] = "neq."
            if action_filter:
                params["action"] = f"eq.{action_filter}"
            if actor_filter:
                params["actor"] = f"eq.{normalize_address(actor_filter)}"
            return self._request("GET", "euthyna_audit_trail", params=params) or []
        except Exception as exc:
            logger.warning(f"Could not load euthyna records from Supabase: {exc}")
            raise

    def save_euthyna_record(self, record: dict) -> None:
        try:
            self._upsert("euthyna_audit_trail", [record], "record_id")
        except Exception as exc:
            logger.warning(f"Could not save euthyna record to Supabase: {exc}")
            raise

    def load_treasury_policy(self, policy_id: str = "default") -> Optional[dict]:
        try:
            rows = self._request("GET", "qma_treasury_policy", params={"policy_id": f"eq.{policy_id}"}) or []
            return rows[0].get("policy") if rows else None
        except Exception as exc:
            logger.warning(f"Could not load treasury policy from Supabase: {exc}")
            return None

    def save_treasury_policy(self, policy: dict, policy_id: str = "default") -> None:
        try:
            self._upsert("qma_treasury_policy", [{"policy_id": policy_id, "policy": policy}], "policy_id")
        except Exception as exc:
            logger.warning(f"Could not save treasury policy to Supabase: {exc}")

    def load_spend_guard_events(self, since_epoch: float) -> list:
        try:
            from datetime import datetime, timezone
            since_iso = datetime.fromtimestamp(float(since_epoch), tz=timezone.utc).isoformat()
            params = {"created_at": f"gte.{since_iso}", "order": "created_at.asc"}
            return self._request("GET", "qma_spend_guard_events", params=params) or []
        except Exception as exc:
            logger.warning(f"Could not load spend guard events from Supabase: {exc}")
            return []

    def save_spend_guard_event(self, event: dict) -> None:
        try:
            row = {
                "payer_address": str(event.get("payer_address") or "global_default"),
                "event_type": str(event.get("event_type") or "SPEND"),
                "amount_usdc": float(event.get("amount_usdc") or 0.0),
                "reason": event.get("reason"),
            }
            if event.get("event_id"):
                row["event_id"] = event["event_id"]
            self._upsert("qma_spend_guard_events", [row], "event_id")
        except Exception as exc:
            logger.warning(f"Could not save spend guard event to Supabase: {exc}")



import json
import os
from typing import Optional

import requests


def normalize_address(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def event_key(event: dict) -> str:
    return str(event.get("settlement_id") or event.get("invoice_id") or "")


class JsonStorage:
    """Local JSON fallback for development and offline demos."""

    backend_name = "json"

    def __init__(self, *, ledger_path: str, reports_path: str, invoices_path: str, creators_path: str):
        self.ledger_path = ledger_path
        self.reports_path = reports_path
        self.invoices_path = invoices_path
        self.creators_path = creators_path

    def _load_json(self, path: str, fallback):
        if not os.path.exists(path):
            return fallback
        try:
            with open(path, "r", encoding="utf-8") as file_obj:
                data = json.load(file_obj)
            return data if isinstance(data, type(fallback)) else fallback
        except Exception:
            return fallback

    def _save_json(self, path: str, value) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as file_obj:
            json.dump(value, file_obj, indent=2)

    def load_payment_events(self) -> list:
        data = self._load_json(self.ledger_path, [])
        return data if isinstance(data, list) else []

    def save_payment_events(self, events: list) -> None:
        self._save_json(self.ledger_path, events[-500:])

    def load_paid_reports(self) -> dict:
        data = self._load_json(self.reports_path, {})
        return data if isinstance(data, dict) else {}

    def save_paid_reports(self, reports: dict) -> None:
        self._save_json(self.reports_path, reports)

    def load_invoices(self) -> dict:
        data = self._load_json(self.invoices_path, {})
        return data if isinstance(data, dict) else {}

    def save_invoice(self, invoice: dict) -> None:
        invoices = self.load_invoices()
        invoice_id = invoice.get("invoice_id")
        if invoice_id:
            invoices[invoice_id] = invoice
            self._save_json(self.invoices_path, invoices)

    def load_creator_applications(self) -> dict:
        data = self._load_json(self.creators_path, {})
        return data if isinstance(data, dict) else {}

    def save_creator_application(self, application: dict) -> None:
        applications = self.load_creator_applications()
        application_id = application.get("application_id")
        if application_id:
            applications[application_id] = application
            self._save_json(self.creators_path, applications)


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
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        resp = requests.request(
            method,
            f"{self.rest_url}/{table}",
            params=params,
            json=json_body,
            headers=headers,
            timeout=self.timeout,
        )
        if not resp.ok:
            raise RuntimeError(f"Supabase {method} {table} returned {resp.status_code}: {resp.text[:300]}")
        if resp.status_code == 204 or not resp.text:
            return None
        return resp.json()

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


def create_storage_backend(*, ledger_path: str, reports_path: str, invoices_path: str, creators_path: str):
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("QMA_SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("QMA_SUPABASE_SERVICE_ROLE_KEY")
    schema = os.getenv("SUPABASE_SCHEMA", "public")
    if supabase_url and service_key:
        return SupabaseStorage(url=supabase_url, service_role_key=service_key, schema=schema)
    return JsonStorage(
        ledger_path=ledger_path,
        reports_path=reports_path,
        invoices_path=invoices_path,
        creators_path=creators_path,
    )

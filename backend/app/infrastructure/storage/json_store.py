import json
import logging
import os
import tempfile
import threading
import time
from typing import Optional

from backend.app.core.state import cross_process_lock
from backend.app.services.payment_state_machine import has_fabricated_settlement
from backend.app.services.wallet_utils import normalize_address
from backend.app.infrastructure.storage.base import (
    _storage_json_lock_key,
    event_key,
    invoice_payment_events,
    paid_report_summary_from_row,
    payment_event_from_row,
    wallet_matches,
)

logger = logging.getLogger("QMA-Storage.Json")

class JsonStorage:
    """Local JSON fallback for development and offline demos."""

    backend_name = "json"

    def __init__(
        self,
        *,
        ledger_path: str,
        reports_path: str,
        invoices_path: str,
        creators_path: str,
        provider_controls_path: str,
    ):
        self.ledger_path = ledger_path
        self.reports_path = reports_path
        self.invoices_path = invoices_path
        self.creators_path = creators_path
        self.provider_controls_path = provider_controls_path
        base_dir = os.path.dirname(self.invoices_path) or "."
        self.sessions_path = os.path.join(base_dir, "agent_sessions.json")
        self.wallets_path = os.path.join(base_dir, "agent_wallets.json")
        self.session_events_path = os.path.join(base_dir, "agent_session_events.json")
        self.incidents_path = os.path.join(base_dir, "agent_incidents.json")
        self.vault_positions_path = os.path.join(base_dir, "earn_vault_positions.json")
        self.euthyna_audit_path = os.path.join(base_dir, "euthyna_audit_trail.json")
        self.treasury_policy_path = os.path.join(base_dir, "treasury_policy.json")
        self.spend_guard_events_path = os.path.join(base_dir, "spend_guard_events.json")
        self._rpc_lock = threading.Lock()

    @staticmethod
    def _lock_key(path: str) -> str:
        return _storage_json_lock_key(path)

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
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file_obj:
                json.dump(value, file_obj, indent=2)
                file_obj.flush()
                os.fsync(file_obj.fileno())
            for attempt in range(5):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            if os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

    def load_payment_events(self) -> list:
        data = self._load_json(self.ledger_path, [])
        return data if isinstance(data, list) else []

    def load_payment_event_summaries(self, *, limit: int = 5000) -> list:
        return sorted(self.load_payment_events(), key=lambda item: item.get("paid_at") or 0, reverse=True)[:limit]

    def load_payment_events_for_wallet(self, address: str, *, limit: int = 5000) -> list:
        normalized = normalize_address(address)
        events = [
            event for event in self.load_payment_events()
            if wallet_matches(event, normalized)
        ]
        return sorted(events, key=lambda item: item.get("paid_at") or 0, reverse=True)[:limit]

    def save_payment_events(self, events: list) -> None:
        with cross_process_lock(self._lock_key(self.ledger_path)):
            self._save_json(self.ledger_path, events)

    def load_wallet_spending_events(self, address: str) -> list:
        normalized = normalize_address(address)
        invoices = [row for row in self.load_invoices().values() if normalize_address(row.get("payer_address")) == normalized]
        events = [row for row in self.load_payment_events() if normalize_address(row.get("payer_address")) == normalized]
        return invoices + events

    def save_single_payment_event(self, event: dict) -> None:
        with cross_process_lock(self._lock_key(self.ledger_path)):
            events = self.load_payment_events()
            key = event_key(event)
            updated = False
            for i, existing in enumerate(events):
                if event_key(existing) == key:
                    events[i] = event
                    updated = True
                    break
            if not updated:
                events.append(event)
            self._save_json(self.ledger_path, events)

    def reserve_withdrawal(self, operation_id: str, operation: dict) -> dict:
        withdrawals_path = os.path.join(os.path.dirname(self.invoices_path) or ".", "withdrawals.json")
        withdrawals = self._load_json(withdrawals_path, {})
        if operation_id not in withdrawals:
            withdrawals[operation_id] = operation
            self._save_json(withdrawals_path, withdrawals)
        return withdrawals[operation_id]

    def save_withdrawal(self, operation_id: str, operation: dict) -> None:
        withdrawals_path = os.path.join(os.path.dirname(self.invoices_path) or ".", "withdrawals.json")
        withdrawals = self._load_json(withdrawals_path, {})
        withdrawals[operation_id] = operation
        self._save_json(withdrawals_path, withdrawals)

    def load_paid_reports(self) -> dict:
        data = self._load_json(self.reports_path, {})
        return data if isinstance(data, dict) else {}

    def load_paid_reports_for_wallet(
        self,
        address: str,
        *,
        symbol: Optional[str] = None,
        provider_id: Optional[str] = None,
        limit: int = 5000,
    ) -> dict:
        normalized = normalize_address(address)
        symbol_filter = str(symbol or "").strip().upper()
        records = {
            entitlement_id: record for entitlement_id, record in self.load_paid_reports().items()
            if isinstance(record, dict)
            and wallet_matches(record, normalized)
            and (not symbol_filter or str(record.get("symbol", "")).upper() == symbol_filter)
            and (not provider_id or record.get("provider_id", "funding_memory") == provider_id)
        }
        ordered = sorted(
            records.items(),
            key=lambda item: item[1].get("paid_at") or item[1].get("saved_at") or 0,
            reverse=True,
        )
        return dict(ordered[:limit])

    def load_paid_report_summaries(self, *, limit: int = 5000) -> list:
        records = self.load_paid_reports()
        ordered = sorted(
            records.items(),
            key=lambda item: item[1].get("paid_at") or item[1].get("saved_at") or 0,
            reverse=True,
        )
        return [
            paid_report_summary_from_row({
                "entitlement_id": entitlement_id,
                "entitlement": record,
            })
            for entitlement_id, record in ordered[:limit]
        ]

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
        normalized = normalize_address(address)
        record = self.load_paid_reports().get(entitlement_id)
        if wallet_matches(record, normalized):
            return record
        return None

    def is_settlement_id_claimed(self, settlement_id: str, exclude_invoice_id: Optional[str] = None) -> bool:
        if not settlement_id:
            return False
        for other_id, invoice in self.load_invoices().items():
            if other_id == exclude_invoice_id:
                continue
            if invoice.get("settlement_id") == settlement_id:
                return True
            for leg in (invoice.get("split") or {}).get("legs") or []:
                if leg.get("settlement_id") == settlement_id:
                    return True
        return False

    def claim_settlement_for_invoice(self, settlement_id: str, invoice_id: str, invoices_db: Optional[dict] = None) -> bool:
        if not settlement_id or not invoice_id:
            return False
        with cross_process_lock(self._lock_key(self.invoices_path)):
            if self.is_settlement_id_claimed(settlement_id, exclude_invoice_id=invoice_id):
                return False
            for ev in self.load_payment_events():
                if ev.get("settlement_id") == settlement_id and ev.get("invoice_id") != invoice_id:
                    return False
            for rep in self.load_paid_reports().values():
                if isinstance(rep, dict) and rep.get("settlement_id") == settlement_id:
                    return False
            invoices = self.load_invoices()
            target = invoices.get(invoice_id)
            if target is None and invoices_db and invoice_id in invoices_db:
                target = dict(invoices_db[invoice_id])
                invoices[invoice_id] = target
            if target is None:
                return False
            if target.get("settlement_id") and target.get("settlement_id") != settlement_id:
                return False
            target["settlement_id"] = settlement_id
            self._save_json(self.invoices_path, invoices)
            if invoices_db and invoice_id in invoices_db:
                invoices_db[invoice_id]["settlement_id"] = settlement_id
            return True

    def save_paid_reports(self, reports: dict) -> None:
        with cross_process_lock(self._lock_key(self.reports_path)):
            self._save_json(self.reports_path, reports)

    def save_single_paid_report(self, entitlement_id: str, record: dict) -> None:
        with cross_process_lock(self._lock_key(self.reports_path)):
            reports = self.load_paid_reports()
            reports[entitlement_id] = record
            self._save_json(self.reports_path, reports)

    def load_invoices(self) -> dict:
        data = self._load_json(self.invoices_path, {})
        return data if isinstance(data, dict) else {}

    def load_paid_invoices_for_wallet(self, address: str, *, limit: int = 5000) -> dict:
        normalized = normalize_address(address)
        invoices = {
            invoice_id: invoice for invoice_id, invoice in self.load_invoices().items()
            if isinstance(invoice, dict)
            and wallet_matches(invoice, normalized)
            and invoice.get("status") == "paid"
        }
        ordered = sorted(
            invoices.items(),
            key=lambda item: item[1].get("paid_at") or item[1].get("created_at") or 0,
            reverse=True,
        )
        return dict(ordered[:limit])

    def load_paid_invoice_events(self, *, limit: int = 5000) -> list:
        events = []
        for invoice in self.load_invoices().values():
            if isinstance(invoice, dict) and invoice.get("status") == "paid":
                events.extend(invoice_payment_events(invoice))
        return sorted(events, key=lambda item: item.get("paid_at") or 0, reverse=True)[:limit]

    def save_invoice(self, invoice: dict) -> None:
        with cross_process_lock(self._lock_key(self.invoices_path)):
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

    def load_provider_controls(self) -> dict:
        data = self._load_json(self.provider_controls_path, {})
        return data if isinstance(data, dict) else {}

    def _request(self, method: str, table: str, *, params: Optional[dict] = None, json_body=None, prefer: str = ""):
        table_clean = table.split("?")[0].strip("/")
        params = params or {}

        if table_clean.startswith("rpc/"):
            fn = table_clean.split("/", 1)[1]
            return self.rpc(fn, json_body)

        if table_clean == "agent_sessions":
            sessions = self._load_json(self.sessions_path, [])
            if not isinstance(sessions, list):
                sessions = []
            if method == "GET":
                filtered = sessions
                for key, val in params.items():
                    if key == "id" and str(val).startswith("eq."):
                        target_id = str(val)[3:]
                        filtered = [s for s in filtered if str(s.get("id")) == target_id]
                    elif key == "runtime_state->>owner_wallet" and str(val).startswith("eq."):
                        target_owner = str(val)[3:].lower()
                        filtered = [s for s in filtered if str((s.get("runtime_state") or {}).get("owner_wallet") or "").lower() == target_owner]
                    elif key == "status" and str(val).startswith("eq."):
                        target_st = str(val)[3:]
                        filtered = [s for s in filtered if str(s.get("status")) == target_st]
                limit_val = params.get("limit")
                limit = int(limit_val) if limit_val and str(limit_val).isdigit() else 100
                return filtered[:limit]
            elif method == "POST":
                row = json_body if isinstance(json_body, dict) else (json_body[0] if isinstance(json_body, list) and json_body else {})
                from datetime import datetime, timezone
                now_iso = datetime.now(timezone.utc).isoformat()
                row.setdefault("created_at", now_iso)
                row.setdefault("updated_at", now_iso)
                sessions.append(row)
                self._save_json(self.sessions_path, sessions)
                return [row]
            elif method == "PATCH":
                target_id = None
                if "id" in params and str(params["id"]).startswith("eq."):
                    target_id = str(params["id"])[3:]
                elif "id=eq." in table:
                    target_id = table.split("id=eq.")[1].split("&")[0]

                updated_rows = []
                for s in sessions:
                    if not target_id or str(s.get("id")) == target_id:
                        if isinstance(json_body, dict):
                            s.update(json_body)
                        updated_rows.append(s)
                self._save_json(self.sessions_path, sessions)
                return updated_rows
            elif method == "DELETE":
                target_id = None
                if "id" in params and str(params["id"]).startswith("eq."):
                    target_id = str(params["id"])[3:]
                elif "id=eq." in table:
                    target_id = table.split("id=eq.")[1].split("&")[0]
                if target_id:
                    sessions = [s for s in sessions if str(s.get("id")) != target_id]
                    self._save_json(self.sessions_path, sessions)
                return []

        elif table_clean == "agent_wallets":
            wallets = self._load_json(self.wallets_path, [])
            if not isinstance(wallets, list):
                wallets = []
            if method == "GET":
                filtered = wallets
                for key, val in params.items():
                    if key == "owner_wallet" and str(val).startswith("eq."):
                        target_owner = str(val)[3:].lower()
                        filtered = [w for w in filtered if str(w.get("owner_wallet") or "").lower() == target_owner]
                return filtered
            elif method in ("POST", "PATCH"):
                row = json_body if isinstance(json_body, dict) else (json_body[0] if isinstance(json_body, list) and json_body else {})
                wallets.append(row)
                self._save_json(self.wallets_path, wallets)
                return [row]

        elif table_clean == "agent_session_events":
            events = self._load_json(self.session_events_path, [])
            if not isinstance(events, list):
                events = []
            if method == "GET":
                filtered = events
                if "session_id" in params and str(params["session_id"]).startswith("eq."):
                    sid = str(params["session_id"])[3:]
                    filtered = [e for e in filtered if str(e.get("session_id")) == sid]
                if params.get("order") == "id.desc":
                    filtered = sorted(filtered, key=lambda e: int(e.get("id") or 0), reverse=True)
                limit_val = params.get("limit")
                if limit_val and str(limit_val).isdigit():
                    filtered = filtered[:int(limit_val)]
                return filtered
            elif method == "POST":
                row = json_body if isinstance(json_body, dict) else {}
                from datetime import datetime, timezone
                max_id = max([int(e.get("id") or 0) for e in events if str(e.get("id", "")).isdigit()], default=0)
                row.setdefault("id", max_id + 1)
                row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                events.append(row)
                self._save_json(self.session_events_path, events)
                return [row]

        return []

    def _upsert(self, table: str, rows: list[dict], conflict: str) -> None:
        table_clean = table.split("?")[0].strip("/")
        if not rows:
            return
        if table_clean == "agent_wallets":
            wallets = self._load_json(self.wallets_path, [])
            if not isinstance(wallets, list):
                wallets = []
            by_owner = {str(w.get("owner_wallet", "")).lower(): w for w in wallets if isinstance(w, dict)}
            for r in rows:
                if isinstance(r, dict):
                    by_owner[str(r.get("owner_wallet", "")).lower()] = r
            self._save_json(self.wallets_path, list(by_owner.values()))
        elif table_clean == "agent_sessions":
            sessions = self._load_json(self.sessions_path, [])
            if not isinstance(sessions, list):
                sessions = []
            by_id = {str(s.get("id", "")): s for s in sessions if isinstance(s, dict)}
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat()
            for r in rows:
                if isinstance(r, dict):
                    sid = str(r.get("id", ""))
                    if sid:
                        existing = by_id.get(sid, {})
                        r.setdefault("created_at", existing.get("created_at") or now_iso)
                        r["updated_at"] = r.get("updated_at") or now_iso
                        by_id[sid] = {**existing, **r}
            self._save_json(self.sessions_path, list(by_id.values()))

    def load_incidents(self) -> list:
        data = self._load_json(self.incidents_path, [])
        return data if isinstance(data, list) else []

    def save_incident(self, incident: dict) -> None:
        incidents = self.load_incidents()
        inc_id = incident.get("incident_id")
        updated = False
        for idx, item in enumerate(incidents):
            if item.get("incident_id") == inc_id:
                incidents[idx] = incident
                updated = True
                break
        if not updated:
            incidents.append(incident)
        self._save_json(self.incidents_path, incidents)

    def save_incidents(self, incidents: list) -> None:
        self._save_json(self.incidents_path, incidents)

    def load_earn_vault_positions(self) -> dict:
        data = self._load_json(self.vault_positions_path, {})
        return data if isinstance(data, dict) else {}

    def save_earn_vault_position(self, position: dict) -> None:
        positions = self.load_earn_vault_positions()
        wallet = position.get("wallet")
        vault_id = position.get("vault_id")
        key = f"{wallet}:{vault_id}"
        positions[key] = position
        self._save_json(self.vault_positions_path, positions)

    def save_earn_vault_positions(self, positions: dict) -> None:
        self._save_json(self.vault_positions_path, positions)

    def load_euthyna_records(
        self,
        limit: int = 50,
        action_filter: Optional[str] = None,
        actor_filter: Optional[str] = None,
        only_live: bool = False,
    ) -> list:
        records = self._load_json(self.euthyna_audit_path, [])
        if not isinstance(records, list):
            return []
        results = records
        if only_live:
            results = [r for r in results if r.get("tx_hash")]
        if action_filter:
            results = [r for r in results if str(r.get("action", "")).lower() == action_filter.lower()]
        if actor_filter:
            norm_actor = normalize_address(actor_filter)
            results = [r for r in results if normalize_address(r.get("actor", "")) == norm_actor]
        return list(reversed(results))[:limit]

    def save_euthyna_record(self, record: dict) -> None:
        records = self._load_json(self.euthyna_audit_path, [])
        if not isinstance(records, list):
            records = []
        records.append(record)
        self._save_json(self.euthyna_audit_path, records)

    def load_treasury_policy(self, policy_id: str = "default") -> Optional[dict]:
        return self._load_json(self.treasury_policy_path, None)

    def save_treasury_policy(self, policy: dict, policy_id: str = "default") -> None:
        self._save_json(self.treasury_policy_path, policy)

    def load_spend_guard_events(self, since_epoch: float) -> list:
        records = self._load_json(self.spend_guard_events_path, [])
        if not isinstance(records, list):
            return []
        return [
            r for r in records
            if isinstance(r, dict) and float(r.get("ts") or 0) >= float(since_epoch)
        ]

    def save_spend_guard_event(self, event: dict) -> None:
        records = self._load_json(self.spend_guard_events_path, [])
        if not isinstance(records, list):
            records = []
        records.append(event)
        self._save_json(self.spend_guard_events_path, records)

    def _parse_ts(self, val) -> int:
        if not val:
            return 0
        if isinstance(val, (int, float)):
            return int(val)
        val_str = str(val).strip()
        if val_str.isdigit():
            return int(val_str)
        try:
            from datetime import datetime
            return int(datetime.fromisoformat(val_str).timestamp())
        except Exception:
            try:
                return int(float(val_str))
            except Exception:
                return 0

    def rpc(self, fn_name: str, payload: Optional[dict] = None):
        payload = payload or {}
        try:
            from backend.app.core.state import cross_process_lock
            lock_cm = cross_process_lock("agent_sessions_rpc")
        except Exception:
            lock_cm = self._rpc_lock

        with lock_cm:
            import time as _time
            now = int(_time.time())
            sessions = self._load_json(self.sessions_path, [])
            if not isinstance(sessions, list):
                sessions = []

            if fn_name in ("acquire_session_tick_lease", "pick_queued_session"):
                worker_id = payload.get("p_worker_id")
                lease_duration = int(payload.get("p_lease_duration_sec", 60))
                for s in sessions:
                    st = str(s.get("status") or "")
                    leased_until = self._parse_ts(s.get("lease_expires_at"))
                    next_run_at = self._parse_ts(s.get("next_run_at"))
                    if st in ("running", "active", "queued") and (leased_until < now) and (next_run_at <= now):
                        s["leased_worker_id"] = worker_id
                        s["lease_expires_at"] = now + lease_duration
                        s["run_generation"] = int(s.get("run_generation") or 0) + 1
                        self._save_json(self.sessions_path, sessions)
                        return [s]
                return []

            elif fn_name == "reclaim_expired_leases":
                reclaimed = 0
                for s in sessions:
                    exp = self._parse_ts(s.get("lease_expires_at"))
                    if exp and exp < now:
                        s["lease_expires_at"] = None
                        s["leased_worker_id"] = None
                        reclaimed += 1
                if reclaimed:
                    self._save_json(self.sessions_path, sessions)
                return reclaimed

            elif fn_name == "checkpoint_session_tick":
                sid = payload.get("p_session_id") or payload.get("session_id")
                for s in sessions:
                    if str(s.get("id")) == str(sid):
                        rs = payload.get("p_runtime_state") if "p_runtime_state" in payload else payload.get("runtime_state")
                        if rs is not None:
                            s["runtime_state"] = rs
                        st = payload.get("p_status") if "p_status" in payload else payload.get("status")
                        if st is not None:
                            s["status"] = st
                        next_sec = payload.get("p_next_run_in_sec") if "p_next_run_in_sec" in payload else payload.get("next_run_in_sec", 15)
                        s["next_run_at"] = now + int(next_sec or 15)
                        s["lease_expires_at"] = None
                        s["leased_worker_id"] = None
                        self._save_json(self.sessions_path, sessions)
                        return True
                return False

            elif fn_name == "heartbeat_session_lease":
                sid = payload.get("p_session_id") or payload.get("session_id")
                lease_duration = int(payload.get("p_lease_duration_sec") or payload.get("lease_duration_sec", 60))
                for s in sessions:
                    if str(s.get("id")) == str(sid):
                        s["lease_expires_at"] = now + lease_duration
                        self._save_json(self.sessions_path, sessions)
                        return True
                return False

            elif fn_name in ("append_qma_ledger_event", "append_ledger_entry"):
                actor = payload.get("p_actor", "agent")
                domain = payload.get("p_domain", "treasury")
                action = payload.get("p_action", "settlement")
                summary = payload.get("p_summary", "")
                detail = payload.get("p_detail", {})
                body_hash = payload.get("p_body_hash", "")
                signature = payload.get("p_signature", "")
                audit_path = os.path.join(os.path.dirname(self.invoices_path) or ".", "euthyna_audit_trail.json")
                entries = self._load_json(audit_path, [])
                if not isinstance(entries, list):
                    entries = []
                prev_hash = entries[-1].get("hash") if entries else ("0" * 64)
                if not prev_hash:
                    prev_hash = "0" * 64
                import hashlib
                comb = f"{prev_hash}{body_hash}{signature}".encode("utf-8")
                entry_hash = hashlib.sha256(comb).hexdigest()
                new_entry = {
                    "seq": len(entries) + 1,
                    "id": str(int(now * 1000)),
                    "ts": now,
                    "actor": actor,
                    "domain": domain,
                    "action": action,
                    "summary": summary,
                    "detail": detail,
                    "body_hash": body_hash,
                    "signature": signature,
                    "prev_hash": prev_hash,
                    "hash": entry_hash,
                }
                entries.append(new_entry)
                self._save_json(audit_path, entries)
                return new_entry

            elif fn_name == "reserve_agent_wallet_spend":
                addr = normalize_address(payload.get("p_wallet_address"))
                amt = float(payload.get("p_amount", 0) or 0)
                cap = float(payload.get("p_spend_cap", 10000) or 10000)
                wallets = self._load_json(self.wallets_path, [])
                if not isinstance(wallets, list):
                    wallets = []
                for w in wallets:
                    if normalize_address(w.get("address")) == addr:
                        bal = float(w.get("balance_usdc", 0) or 0)
                        spent = float(w.get("spent_usdc", 0) or 0)
                        if round(spent + amt, 6) <= cap and bal >= amt:
                            w["spent_usdc"] = round(spent + amt, 6)
                            w["balance_usdc"] = round(bal - amt, 6)
                            self._save_json(self.wallets_path, wallets)
                            return True
                        return False
                return False

            elif fn_name == "release_agent_wallet_spend":
                addr = normalize_address(payload.get("p_wallet_address"))
                amt = float(payload.get("p_amount", 0) or 0)
                wallets = self._load_json(self.wallets_path, [])
                if isinstance(wallets, list):
                    for w in wallets:
                        if normalize_address(w.get("address")) == addr:
                            spent = float(w.get("spent_usdc", 0) or 0)
                            bal = float(w.get("balance_usdc", 0) or 0)
                            w["spent_usdc"] = max(0.0, round(spent - amt, 6))
                            w["balance_usdc"] = round(bal + amt, 6)
                            self._save_json(self.wallets_path, wallets)
                            return True
                return True

            return None




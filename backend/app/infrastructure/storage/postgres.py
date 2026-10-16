import json
import logging
import os
import time
from typing import Optional
from urllib.parse import unquote, urlparse

try:
    import psycopg2
    from psycopg2.extras import Json as PgJson, RealDictCursor
    from psycopg2.pool import ThreadedConnectionPool
except ImportError:
    psycopg2 = None
    PgJson = None
    RealDictCursor = None
    ThreadedConnectionPool = None

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

logger = logging.getLogger("QMA-Storage.Postgres")

class PostgresStorage:
    """Native PostgreSQL storage engine for QMA."""

    backend_name = "postgres"

    def __init__(self, database_url: str, min_conn: int = 1, max_conn: int = 30):
        if psycopg2 is None:
            raise RuntimeError("psycopg2 is not installed. Please install psycopg2-binary to use PostgresStorage.")
        self.database_url = database_url
        from urllib.parse import urlparse, unquote
        parsed = urlparse(database_url)
        if parsed.scheme in ("postgresql", "postgres"):
            user = unquote(parsed.username or "postgres")
            password = unquote(parsed.password or "")
            host = parsed.hostname or "localhost"
            port = parsed.port or 5432
            dbname = parsed.path.lstrip("/") or "qma"
            self.pool = ThreadedConnectionPool(
                min_conn, max_conn,
                user=user,
                password=password,
                host=host,
                port=port,
                dbname=dbname,
            )
        else:
            self.pool = ThreadedConnectionPool(min_conn, max_conn, database_url)

        self.sessions_path = "agent_sessions.json"
        self.wallets_path = "agent_wallets.json"
        self.session_events_path = "agent_session_events.json"

    def _load_json(self, path: str, fallback):
        table = (
            "agent_session_events" if "session_event" in str(path)
            else "agent_sessions" if "session" in str(path)
            else "agent_wallets" if "wallet" in str(path)
            else None
        )
        if table:
            rows = self.execute_query(f'SELECT * FROM public."{table}";', fetch_all=True) or []
            return list(rows)
        # PostgreSQL mode never reads local JSON state.
        raise RuntimeError(f"PostgresStorage has no table mapping for legacy JSON path '{path}'.")

    def _save_json(self, path: str, data):
        table = (
            "agent_session_events" if "session_event" in str(path)
            else "agent_sessions" if "session" in str(path)
            else "agent_wallets" if "wallet" in str(path)
            else None
        )
        if table and isinstance(data, list):
            conflict = "id" if table in ("agent_sessions", "agent_session_events") else "address"
            self._upsert(table, data, conflict)
            return
        # PostgreSQL mode never writes local JSON state; fail loudly instead of
        # silently diverging into a file only this instance can see.
        raise RuntimeError(f"PostgresStorage has no table mapping for legacy JSON path '{path}'.")

    def get_connection(self):
        return self.pool.getconn()

    def put_connection(self, conn):
        # A connection left in an aborted or idle-in-transaction state fails
        # every later borrower until the pool recycles it, which read paths
        # surface as silent empty results. Reset it before reuse.
        try:
            if conn.closed:
                self.pool.putconn(conn, close=True)
                return
            status_ready = getattr(psycopg2.extensions, "STATUS_READY", None)
            if status_ready is not None and conn.status != status_ready:
                conn.rollback()
        except Exception:
            try:
                self.pool.putconn(conn, close=True)
            except Exception:
                pass
            return
        self.pool.putconn(conn)

    def execute_query(self, query: str, params: tuple = (), fetch_all: bool = False, fetch_one: bool = False):
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                if fetch_one:
                    return cur.fetchone()
                if fetch_all:
                    return cur.fetchall()
                conn.commit()
                return None
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self.put_connection(conn)

    # ---------------------------------------------------------------------------
    # Payment Events
    # ---------------------------------------------------------------------------
    def load_payment_events(self) -> list:
        rows = self.execute_query(
            "SELECT event FROM public.qma_payment_events ORDER BY paid_at DESC NULLS LAST LIMIT 5000;",
            fetch_all=True
        ) or []
        return [row["event"] for row in rows if isinstance(row.get("event"), dict)]

    def load_payment_event_summaries(self, *, limit: int = 5000) -> list:
        rows = self.execute_query(
            """
            SELECT event_id, invoice_id, settlement_id, payer_address, symbol, tier,
                   provider_id, amount_usdc, gateway_status, transaction_hash,
                   explorer_url, paid_at
            FROM public.qma_payment_events
            ORDER BY paid_at DESC NULLS LAST
            LIMIT %s;
            """,
            (limit,),
            fetch_all=True
        ) or []
        return [payment_event_from_row(row) for row in rows]

    def load_payment_events_for_wallet(self, address: str, *, limit: int = 5000) -> list:
        events = [event for event in self.load_payment_events() if wallet_matches(event, address)]
        return sorted(events, key=lambda item: item.get("paid_at") or 0, reverse=True)[:limit]

    def save_payment_events(self, events: list) -> None:
        if not events:
            return
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for event in events:
                    key = event_key(event)
                    if not key:
                        continue
                    cur.execute(
                        """
                        INSERT INTO public.qma_payment_events (
                            event_id, invoice_id, settlement_id, payer_address, symbol, tier,
                            provider_id, amount_usdc, gateway_status, transaction_hash,
                            explorer_url, paid_at, event
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (event_id) DO UPDATE SET
                            settlement_id = EXCLUDED.settlement_id,
                            gateway_status = EXCLUDED.gateway_status,
                            event = EXCLUDED.event;
                        """,
                        (
                            key,
                            event.get("invoice_id"),
                            event.get("settlement_id"),
                            normalize_address(event.get("payer_address")),
                            event.get("symbol"),
                            event.get("tier"),
                            event.get("provider_id", "funding_memory"),
                            event.get("amount_usdc"),
                            event.get("gateway_status"),
                            event.get("transaction_hash"),
                            event.get("explorer_url"),
                            event.get("paid_at"),
                            PgJson(event),
                        )
                    )
                conn.commit()
        finally:
            self.put_connection(conn)

    def save_single_payment_event(self, event: dict) -> None:
        self.save_payment_events([event])

    # ---------------------------------------------------------------------------
    # Paid Reports
    # ---------------------------------------------------------------------------
    def load_paid_reports(self) -> dict:
        rows = self.execute_query(
            "SELECT entitlement_id, entitlement FROM public.qma_paid_reports ORDER BY saved_at DESC NULLS LAST LIMIT 5000;",
            fetch_all=True
        ) or []
        records = {}
        for row in rows:
            record = row.get("entitlement")
            ent_id = row.get("entitlement_id") or (record or {}).get("entitlement_id")
            if ent_id and isinstance(record, dict):
                records[ent_id] = record
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
        return dict(ordered[:limit])

    def load_paid_report_summaries(self, *, limit: int = 5000) -> list:
        rows = self.execute_query(
            """
            SELECT entitlement_id, payer_address, symbol, tier, provider_id, query_hash, settlement_id, paid_at, saved_at
            FROM public.qma_paid_reports
            ORDER BY saved_at DESC NULLS LAST
            LIMIT %s;
            """,
            (limit,),
            fetch_all=True
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
        if exclude_invoice_id:
            row = self.execute_query(
                "SELECT event_id FROM public.qma_payment_events WHERE settlement_id = %s AND (invoice_id != %s OR invoice_id IS NULL) LIMIT 1;",
                (settlement_id, exclude_invoice_id),
                fetch_one=True
            )
        else:
            row = self.execute_query(
                "SELECT event_id FROM public.qma_payment_events WHERE settlement_id = %s LIMIT 1;",
                (settlement_id,),
                fetch_one=True
            )
        if row:
            return True

        if exclude_invoice_id:
            row = self.execute_query(
                "SELECT invoice_id FROM public.qma_invoices WHERE settlement_id = %s AND invoice_id != %s LIMIT 1;",
                (settlement_id, exclude_invoice_id),
                fetch_one=True
            )
        else:
            row = self.execute_query(
                "SELECT invoice_id FROM public.qma_invoices WHERE settlement_id = %s LIMIT 1;",
                (settlement_id,),
                fetch_one=True
            )
        if row:
            return True

        row = self.execute_query(
            "SELECT entitlement_id FROM public.qma_paid_reports WHERE settlement_id = %s LIMIT 1;",
            (settlement_id,),
            fetch_one=True
        )
        return row is not None

    def claim_settlement_for_invoice(self, settlement_id: str, invoice_id: str, invoices_db: Optional[dict] = None) -> bool:
        if not settlement_id or not invoice_id:
            return False
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                # Advisory transaction lock on the settlement ID to serialize claims
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('settlement:' || %s));", (settlement_id,))

                # Check payment events
                cur.execute("SELECT 1 FROM public.qma_payment_events WHERE settlement_id = %s LIMIT 1;", (settlement_id,))
                if cur.fetchone():
                    conn.rollback()
                    return False

                # Check other invoices (both top-level and split legs)
                cur.execute(
                    """SELECT 1 FROM public.qma_invoices
                       WHERE (settlement_id = %s OR invoice->'split'->'legs' @> %s::jsonb)
                       AND invoice_id != %s LIMIT 1;""",
                    (settlement_id, json.dumps([{"settlement_id": settlement_id}]), invoice_id),
                )
                if cur.fetchone():
                    conn.rollback()
                    return False

                # Check paid reports
                cur.execute("SELECT 1 FROM public.qma_paid_reports WHERE settlement_id = %s LIMIT 1;", (settlement_id,))
                if cur.fetchone():
                    conn.rollback()
                    return False

                # Bind to invoice atomically
                cur.execute(
                    "UPDATE public.qma_invoices SET settlement_id = %s WHERE invoice_id = %s AND (settlement_id IS NULL OR settlement_id = %s);",
                    (settlement_id, invoice_id, settlement_id),
                )
                updated = cur.rowcount > 0
                if not updated:
                    # In unit tests or mock setups, the invoice might exist only in invoices_db in-memory
                    if invoices_db and invoice_id in invoices_db:
                        target = invoices_db[invoice_id]
                        if target.get("settlement_id") and target.get("settlement_id") != settlement_id:
                            conn.rollback()
                            return False
                        target["settlement_id"] = settlement_id
                        updated = True
                conn.commit()
                if updated and invoices_db and invoice_id in invoices_db:
                    invoices_db[invoice_id]["settlement_id"] = settlement_id
                return updated
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return False
        finally:
            self.put_connection(conn)

    def save_paid_reports(self, reports: dict) -> None:
        if not reports:
            return
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for entitlement_id, record in reports.items():
                    if not isinstance(record, dict) or not entitlement_id:
                        continue
                    cur.execute(
                        """
                        INSERT INTO public.qma_paid_reports (
                            entitlement_id, payer_address, symbol, tier, provider_id,
                            query_hash, settlement_id, paid_at, saved_at, entitlement
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (entitlement_id) DO UPDATE SET
                            settlement_id = EXCLUDED.settlement_id,
                            entitlement = EXCLUDED.entitlement;
                        """,
                        (
                            entitlement_id,
                            normalize_address(record.get("payer_address")),
                            record.get("symbol"),
                            record.get("tier"),
                            record.get("provider_id", "funding_memory"),
                            record.get("query_hash"),
                            record.get("settlement_id"),
                            record.get("paid_at"),
                            record.get("saved_at"),
                            PgJson(record),
                        )
                    )
                conn.commit()
        finally:
            self.put_connection(conn)

    def save_single_paid_report(self, entitlement_id: str, record: dict) -> None:
        self.save_paid_reports({entitlement_id: record})

    # ---------------------------------------------------------------------------
    # Invoices
    # ---------------------------------------------------------------------------
    def load_invoices(self) -> dict:
        rows = self.execute_query(
            "SELECT invoice_id, invoice FROM public.qma_invoices ORDER BY created_at DESC NULLS LAST LIMIT 2000;",
            fetch_all=True
        ) or []
        invoices = {}
        for row in rows:
            invoice = row.get("invoice")
            inv_id = row.get("invoice_id") or (invoice or {}).get("invoice_id")
            if inv_id and isinstance(invoice, dict):
                invoices[inv_id] = invoice
        return invoices

    def count_invoices(self) -> int:
        """Authoritative invoice count straight from PostgreSQL. The in-memory
        invoice map is only a newest-2000 view, so len() must never be used as
        a platform metric."""
        row = self.execute_query("SELECT count(*) AS n FROM public.qma_invoices;", fetch_one=True)
        return int(row["n"]) if row else 0

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
        rows = self.execute_query(
            """
            SELECT invoice_id, settlement_id, payer_address, symbol, tier, provider_id,
                   query_hash, created_at, expires_at, paid_at, invoice
            FROM public.qma_invoices
            WHERE status = 'paid'
            ORDER BY paid_at DESC NULLS LAST
            LIMIT %s;
            """,
            (limit,),
            fetch_all=True
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
        inv_id = invoice.get("invoice_id")
        if not inv_id:
            return
        self.execute_query(
            """
            INSERT INTO public.qma_invoices (
                invoice_id, status, settlement_id, payer_address, symbol, tier,
                provider_id, query_hash, created_at, expires_at, paid_at, invoice
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (invoice_id) DO UPDATE SET
                status = EXCLUDED.status,
                settlement_id = EXCLUDED.settlement_id,
                paid_at = EXCLUDED.paid_at,
                invoice = EXCLUDED.invoice;
            """,
            (
                inv_id,
                invoice.get("status", "pending"),
                invoice.get("settlement_id"),
                normalize_address(invoice.get("payer_address")),
                invoice.get("symbol"),
                invoice.get("tier"),
                invoice.get("provider_id", "funding_memory"),
                invoice.get("query_hash"),
                invoice.get("created_at"),
                invoice.get("expires_at"),
                invoice.get("paid_at"),
                PgJson(invoice),
            )
        )

    # ---------------------------------------------------------------------------
    # Creator Applications & Controls
    # ---------------------------------------------------------------------------
    def load_creator_applications(self) -> dict:
        rows = self.execute_query(
            "SELECT application_id, application FROM public.qma_creator_applications ORDER BY created_at DESC NULLS LAST LIMIT 1000;",
            fetch_all=True
        ) or []
        apps = {}
        for row in rows:
            app = row.get("application")
            app_id = row.get("application_id") or (app or {}).get("application_id")
            if app_id and isinstance(app, dict):
                apps[app_id] = app
        return apps

    def save_creator_application(self, application: dict) -> None:
        app_id = application.get("application_id")
        if not app_id:
            return
        self.execute_query(
            """
            INSERT INTO public.qma_creator_applications (
                application_id, creator_wallet, provider_id, status,
                created_at, updated_at, application
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (application_id) DO UPDATE SET
                status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at,
                application = EXCLUDED.application;
            """,
            (
                app_id,
                normalize_address(application.get("creator_wallet")),
                application.get("provider_id"),
                application.get("status", "pending"),
                application.get("created_at"),
                application.get("updated_at"),
                PgJson(application),
            )
        )

    def load_provider_controls(self) -> dict:
        rows = self.execute_query(
            "SELECT provider_id, control FROM public.qma_provider_controls LIMIT 1000;",
            fetch_all=True
        ) or []
        ctrls = {}
        for row in rows:
            pid = row.get("provider_id")
            ctrl = row.get("control")
            if pid and isinstance(ctrl, dict):
                ctrls[pid] = ctrl
        return ctrls

    def save_provider_control(self, provider_id: str, control: dict) -> None:
        if not provider_id:
            return
        self.execute_query(
            """
            INSERT INTO public.qma_provider_controls (
                provider_id, enabled, updated_at, control
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (provider_id) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                updated_at = EXCLUDED.updated_at,
                control = EXCLUDED.control;
            """,
            (
                provider_id,
                control.get("enabled", True),
                control.get("updated_at") or int(time.time()),
                PgJson(control),
            )
        )

    def load_creator_claims(self) -> list:
        try:
            rows = self.execute_query(
                "SELECT claim FROM public.qma_creator_claims ORDER BY claim_id ASC LIMIT 500;",
                fetch_all=True
            ) or []
            return [r["claim"] for r in rows if "claim" in r]
        except Exception:
            return []

    def load_incidents(self) -> list:
        try:
            rows = self.execute_query(
                "SELECT incident FROM public.agent_incidents ORDER BY created_at ASC LIMIT 1000;",
                fetch_all=True
            ) or []
            res = []
            for r in rows:
                inc = r.get("incident")
                if isinstance(inc, str):
                    try:
                        inc = json.loads(inc)
                    except Exception:
                        continue
                if isinstance(inc, dict):
                    res.append(inc)
            return res
        except Exception as exc:
            logger.warning(f"Could not load incidents from Postgres: {exc}")
            raise

    def save_incident(self, incident: dict) -> None:
        inc_id = incident.get("incident_id")
        if not inc_id:
            return
        sess_id = incident.get("session_id")
        trace_id = incident.get("trace_id")
        sev = incident.get("severity", "P3_INFO")
        status = incident.get("status", "OPEN")
        cat = incident.get("category")
        rule = incident.get("rule")
        details = incident.get("details")
        fin_ctx = incident.get("financial_context") or {}
        actor_type = incident.get("actor_type")
        actor_addr = incident.get("actor_address")
        euthyna_hash = incident.get("euthyna_hash")
        admin_note = incident.get("admin_note")
        try:
            self.execute_query(
                """
                INSERT INTO public.agent_incidents (
                    incident_id, session_id, trace_id, severity, status, category, rule,
                    details, financial_context, actor_type, actor_address, euthyna_hash,
                    admin_note, incident, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (incident_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    admin_note = EXCLUDED.admin_note,
                    resolved_at = CASE WHEN EXCLUDED.status = 'RESOLVED' THEN NOW() ELSE public.agent_incidents.resolved_at END,
                    incident = EXCLUDED.incident;
                """,
                (
                    inc_id, sess_id, trace_id, sev, status, cat, rule,
                    details, PgJson(fin_ctx), actor_type, actor_addr, euthyna_hash,
                    admin_note, PgJson(incident)
                )
            )
        except Exception as exc:
            logger.warning(f"Could not save incident to Postgres: {exc}")
            raise

    def load_earn_vault_positions(self) -> dict:
        try:
            rows = self.execute_query(
                "SELECT wallet, vault_id, vault_address, shares, principal_usdc, last_deposit_at, last_rebalance_at, metadata FROM public.earn_vault_positions;",
                fetch_all=True
            ) or []
            positions = {}
            for r in rows:
                w = r.get("wallet")
                v = r.get("vault_id")
                if not w or not v:
                    continue
                key = f"{w}:{v}"
                dep_at = r.get("last_deposit_at")
                reb_at = r.get("last_rebalance_at")
                positions[key] = {
                    "wallet": w,
                    "vault_id": v,
                    "vaultAddress": r.get("vault_address"),
                    "shares": float(r.get("shares") or 0.0),
                    "principal_usdc": float(r.get("principal_usdc") or 0.0),
                    "last_deposit_at": dep_at.timestamp() if hasattr(dep_at, "timestamp") else dep_at,
                    "last_rebalance_at": reb_at.timestamp() if hasattr(reb_at, "timestamp") else reb_at,
                    "metadata": r.get("metadata") or {},
                }
            return positions
        except Exception as exc:
            logger.warning(f"Could not load earn positions from Postgres: {exc}")
            return {}

    def save_earn_vault_position(self, position: dict) -> None:
        w = position.get("wallet")
        v = position.get("vault_id")
        if not w or not v:
            return
        key = f"{w}:{v}"
        v_addr = position.get("vaultAddress")
        shares = float(position.get("shares") or 0.0)
        princ = float(position.get("principal_usdc") or 0.0)
        dep_at = position.get("last_deposit_at")
        reb_at = position.get("last_rebalance_at")
        meta = position.get("metadata") or {}
        try:
            self.execute_query(
                """
                INSERT INTO public.earn_vault_positions (
                    position_id, wallet, vault_id, vault_address, shares, principal_usdc,
                    last_deposit_at, last_rebalance_at, metadata, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s::double precision > 0 THEN to_timestamp(%s::double precision) ELSE NULL END,
                    CASE WHEN %s::double precision > 0 THEN to_timestamp(%s::double precision) ELSE NULL END,
                    %s, NOW()
                )
                ON CONFLICT (wallet, vault_id) DO UPDATE SET
                    vault_address = EXCLUDED.vault_address,
                    shares = EXCLUDED.shares,
                    principal_usdc = EXCLUDED.principal_usdc,
                    last_deposit_at = EXCLUDED.last_deposit_at,
                    last_rebalance_at = EXCLUDED.last_rebalance_at,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW();
                """,
                (
                    key, w, v, v_addr, shares, princ,
                    float(dep_at or 0), float(dep_at or 0),
                    float(reb_at or 0), float(reb_at or 0),
                    PgJson(meta)
                )
            )
        except Exception as exc:
            logger.warning(f"Could not save earn position to Postgres: {exc}")

    def save_earn_vault_positions(self, positions: dict) -> None:
        for pos in positions.values():
            if isinstance(pos, dict):
                self.save_earn_vault_position(pos)

    # ---------------------------------------------------------------------------
    # Euthyna Cryptographic Audit Trail
    # ---------------------------------------------------------------------------
    def load_euthyna_records(
        self,
        limit: int = 50,
        action_filter: Optional[str] = None,
        actor_filter: Optional[str] = None,
        only_live: bool = False,
    ) -> list:
        try:
            where_clauses = []
            params = []
            if only_live:
                where_clauses.append("tx_hash IS NOT NULL AND tx_hash != ''")
            if action_filter:
                where_clauses.append("LOWER(action) = LOWER(%s)")
                params.append(action_filter)
            if actor_filter:
                where_clauses.append("LOWER(actor) = LOWER(%s)")
                params.append(actor_filter)

            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            sql = f"""
                SELECT record_id, previous_hash, timestamp, action, actor,
                       amount_usdc::float, treasury_liquid_before::float, treasury_liquid_after::float,
                       usyc_vault_shares::float, tx_hash, arcscan_url, policy_rule_applied,
                       cfo_reasoning, provider_id, genlayer_consensus, integrity_hash, status
                FROM public.euthyna_audit_trail
                {where_sql}
                ORDER BY sequence_id DESC
                LIMIT %s;
            """
            params.append(limit)
            rows = self.execute_query(sql, tuple(params), fetch_all=True) or []
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning(f"Could not load euthyna records from Postgres: {exc}")
            raise

    def save_euthyna_record(self, record: dict) -> None:
        rec_id = record.get("record_id")
        if not rec_id:
            return
        try:
            self.execute_query(
                """
                INSERT INTO public.euthyna_audit_trail (
                    record_id, previous_hash, timestamp, action, actor, amount_usdc,
                    treasury_liquid_before, treasury_liquid_after, usyc_vault_shares,
                    tx_hash, arcscan_url, policy_rule_applied, cfo_reasoning,
                    provider_id, genlayer_consensus, integrity_hash, status, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                )
                ON CONFLICT (record_id) DO NOTHING;
                """,
                (
                    rec_id,
                    record.get("previous_hash"),
                    record.get("timestamp"),
                    record.get("action", "UNKNOWN"),
                    record.get("actor", "0x0000000000000000000000000000000000000000"),
                    float(record.get("amount_usdc") or 0.0),
                    float(record.get("treasury_liquid_before") or 0.0),
                    float(record.get("treasury_liquid_after") or 0.0),
                    float(record.get("usyc_vault_shares") or 0.0),
                    record.get("tx_hash"),
                    record.get("arcscan_url"),
                    record.get("policy_rule_applied"),
                    record.get("cfo_reasoning"),
                    record.get("provider_id"),
                    record.get("genlayer_consensus"),
                    record.get("integrity_hash"),
                    record.get("status"),
                )
            )
        except Exception as exc:
            logger.warning(f"Could not save euthyna record to Postgres: {exc}")
            raise

    # ---------------------------------------------------------------------------
    # Corporate Treasury Policy
    # ---------------------------------------------------------------------------
    def load_treasury_policy(self, policy_id: str = "default") -> Optional[dict]:
        try:
            row = self.execute_query(
                "SELECT policy FROM public.qma_treasury_policy WHERE policy_id = %s;",
                (policy_id,),
                fetch_one=True
            )
            return row.get("policy") if row else None
        except Exception as exc:
            logger.warning(f"Could not load treasury policy from Postgres: {exc}")
            return None

    def save_treasury_policy(self, policy: dict, policy_id: str = "default") -> None:
        try:
            self.execute_query(
                """
                INSERT INTO public.qma_treasury_policy (policy_id, policy, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (policy_id) DO UPDATE SET policy = EXCLUDED.policy, updated_at = NOW();
                """,
                (policy_id, PgJson(policy))
            )
        except Exception as exc:
            logger.warning(f"Could not save treasury policy to Postgres: {exc}")

    # ---------------------------------------------------------------------------
    # Spend Guard Ledger (durable autonomous spending controls)
    # ---------------------------------------------------------------------------
    def load_spend_guard_events(self, since_epoch: float) -> list:
        try:
            rows = self.execute_query(
                """
                SELECT payer_address, event_type, amount_usdc::float AS amount_usdc,
                       reason, EXTRACT(EPOCH FROM created_at)::float AS ts
                FROM public.qma_spend_guard_events
                WHERE created_at >= to_timestamp(%s)
                ORDER BY event_id ASC;
                """,
                (float(since_epoch),),
                fetch_all=True,
            ) or []
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning(f"Could not load spend guard events from Postgres: {exc}")
            return []

    def save_spend_guard_event(self, event: dict) -> None:
        try:
            self.execute_query(
                """
                INSERT INTO public.qma_spend_guard_events
                    (payer_address, event_type, amount_usdc, reason)
                VALUES (%s, %s, %s, %s);
                """,
                (
                    str(event.get("payer_address") or "global_default"),
                    str(event.get("event_type") or "SPEND"),
                    float(event.get("amount_usdc") or 0.0),
                    event.get("reason"),
                ),
            )
        except Exception as exc:
            logger.warning(f"Could not save spend guard event to Postgres: {exc}")

    # ---------------------------------------------------------------------------
    # Shared runtime state (formerly process-local JSON files)
    # ---------------------------------------------------------------------------
    def _execute_write_returning(self, query: str, params: tuple = ()):
        """Run a write statement, commit, and return the first row (or None)."""
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                row = cur.fetchone() if cur.description else None
            conn.commit()
            return row
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self.put_connection(conn)

    @staticmethod
    def _json_param(value):
        return PgJson(value, dumps=lambda obj: json.dumps(obj, default=str))

    # -- Agent session control (single-row compare-and-set) --------------------
    def load_session(self, session_id: str) -> Optional[dict]:
        row = self.execute_query(
            "SELECT * FROM public.agent_sessions WHERE id = %s;",
            (str(session_id),),
            fetch_one=True,
        )
        return dict(row) if row else None

    def transition_session_status(
        self,
        session_id: str,
        *,
        expected_status: str,
        next_status: str,
        runtime_state: dict,
    ) -> bool:
        """Atomically move one session from expected_status to next_status.

        Returns False when the row changed concurrently (status no longer matches),
        so a stale read can never overwrite a worker's newer state.
        """
        row = self._execute_write_returning(
            """
            UPDATE public.agent_sessions
               SET status = %s,
                   runtime_state = %s,
                   updated_at = NOW(),
                   state_version = COALESCE(state_version, 0) + 1
             WHERE id = %s AND status = %s
         RETURNING id;
            """,
            (next_status, self._json_param(runtime_state or {}), str(session_id), expected_status),
        )
        return row is not None

    # -- Swap execution store ----------------------------------------------------
    def load_swap_execution(self, execution_key: str) -> Optional[dict]:
        row = self.execute_query(
            "SELECT record FROM public.swap_executions WHERE execution_key = %s;",
            (str(execution_key),),
            fetch_one=True,
        )
        record = row.get("record") if row else None
        return dict(record) if isinstance(record, dict) else None

    def list_swap_executions(self, limit: int = 50) -> list:
        rows = self.execute_query(
            """
            SELECT record FROM public.swap_executions
             WHERE execution_key NOT LIKE 'idemp:%%'
             ORDER BY updated_at DESC
             LIMIT %s;
            """,
            (int(limit),),
            fetch_all=True,
        ) or []
        return [dict(r["record"]) for r in rows if isinstance(r.get("record"), dict)]

    def save_swap_execution(self, record: dict) -> None:
        quote_id = str(record.get("quote_id") or "").strip()
        if not quote_id:
            return
        keys = [quote_id]
        idemp = record.get("idempotency_key")
        if idemp and idemp != quote_id:
            keys.append(f"idemp:{idemp}")
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for key in keys:
                    cur.execute(
                        """
                        INSERT INTO public.swap_executions (execution_key, quote_id, record)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (execution_key) DO UPDATE
                           SET record = EXCLUDED.record,
                               quote_id = EXCLUDED.quote_id,
                               updated_at = NOW();
                        """,
                        (key, quote_id, self._json_param(dict(record))),
                    )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self.put_connection(conn)

    # -- StableFX deposit replay guard -------------------------------------------
    def reserve_stablefx_deposit(
        self,
        deposit_tx_hash: str,
        *,
        quote_id: Optional[str] = None,
        recipient_address: Optional[str] = None,
    ) -> bool:
        """Atomically reserve a deposit hash. False means it was already consumed."""
        row = self._execute_write_returning(
            """
            INSERT INTO public.stablefx_consumed_deposits (deposit_tx_hash, quote_id, recipient_address)
            VALUES (%s, %s, %s)
            ON CONFLICT (deposit_tx_hash) DO NOTHING
            RETURNING deposit_tx_hash;
            """,
            (str(deposit_tx_hash), quote_id, recipient_address),
        )
        return row is not None

    def mark_stablefx_deposit_broadcast(self, deposit_tx_hash: str, payout_tx_hash: Optional[str] = None) -> None:
        self._execute_write_returning(
            """
            UPDATE public.stablefx_consumed_deposits
               SET status = 'broadcast',
                   payout_tx_hash = COALESCE(%s, payout_tx_hash),
                   updated_at = NOW()
             WHERE deposit_tx_hash = %s;
            """,
            (payout_tx_hash, str(deposit_tx_hash)),
        )

    def release_stablefx_deposit(self, deposit_tx_hash: str) -> None:
        """Drop a reservation only if no payout was ever broadcast for it."""
        self._execute_write_returning(
            "DELETE FROM public.stablefx_consumed_deposits WHERE deposit_tx_hash = %s AND status = 'reserved';",
            (str(deposit_tx_hash),),
        )

    def is_stablefx_deposit_consumed(self, deposit_tx_hash: str) -> bool:
        row = self.execute_query(
            "SELECT 1 AS hit FROM public.stablefx_consumed_deposits WHERE deposit_tx_hash = %s;",
            (str(deposit_tx_hash),),
            fetch_one=True,
        )
        return row is not None

    # -- Earn vault share-price snapshots ----------------------------------------
    def record_vault_snapshots(self, samples: dict, max_age_seconds: float) -> int:
        now = time.time()
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for vault_id, sample in (samples or {}).items():
                    cur.execute(
                        """
                        INSERT INTO public.earn_vault_snapshots (vault_id, ts, share_price_usdc, tvl_usdc)
                        VALUES (%s, %s, %s, %s);
                        """,
                        (
                            str(vault_id),
                            float(sample.get("ts") or now),
                            float(sample.get("share_price_usdc") or 0.0),
                            float(sample.get("tvl_usdc") or 0.0),
                        ),
                    )
                cur.execute("DELETE FROM public.earn_vault_snapshots WHERE ts < %s;", (now - float(max_age_seconds),))
                cur.execute("SELECT COUNT(*) FROM public.earn_vault_snapshots;")
                total = int(cur.fetchone()[0])
            conn.commit()
            return total
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self.put_connection(conn)

    def load_vault_snapshots(self, vault_id: Optional[str] = None) -> dict:
        if vault_id:
            rows = self.execute_query(
                """
                SELECT vault_id, ts, share_price_usdc::float AS share_price_usdc, tvl_usdc::float AS tvl_usdc
                  FROM public.earn_vault_snapshots WHERE vault_id = %s ORDER BY ts ASC;
                """,
                (str(vault_id),),
                fetch_all=True,
            ) or []
        else:
            rows = self.execute_query(
                """
                SELECT vault_id, ts, share_price_usdc::float AS share_price_usdc, tvl_usdc::float AS tvl_usdc
                  FROM public.earn_vault_snapshots ORDER BY ts ASC;
                """,
                fetch_all=True,
            ) or []
        out: dict = {}
        for r in rows:
            out.setdefault(r["vault_id"], []).append({
                "ts": float(r["ts"]),
                "share_price_usdc": float(r["share_price_usdc"] or 0.0),
                "tvl_usdc": float(r["tvl_usdc"] or 0.0),
            })
        return out

    # -- Runtime flags (shared by every instance) --------------------------------
    def get_runtime_flag(self, flag_name: str) -> Optional[dict]:
        row = self.execute_query(
            "SELECT payload FROM public.qma_runtime_flags WHERE flag_name = %s;",
            (str(flag_name),),
            fetch_one=True,
        )
        if not row:
            return None
        payload = row.get("payload")
        return dict(payload) if isinstance(payload, dict) else {}

    def set_runtime_flag(self, flag_name: str, payload: dict) -> None:
        self._execute_write_returning(
            """
            INSERT INTO public.qma_runtime_flags (flag_name, payload)
            VALUES (%s, %s)
            ON CONFLICT (flag_name) DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW();
            """,
            (str(flag_name), self._json_param(payload or {})),
        )

    def clear_runtime_flag(self, flag_name: str) -> None:
        self._execute_write_returning(
            "DELETE FROM public.qma_runtime_flags WHERE flag_name = %s;",
            (str(flag_name),),
        )

    # ---------------------------------------------------------------------------
    # High-Performance Analytical Views (Read-Only Offload)
    # ---------------------------------------------------------------------------
    def load_traction_daily_view(self, days: int = 14) -> list:
        try:
            rows = self.execute_query(
                "SELECT * FROM public.v_platform_traction_daily LIMIT %s;",
                (days,),
                fetch_all=True
            ) or []
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning(f"Could not query v_platform_traction_daily: {exc}")
            return []

    def load_platform_metrics_summary_view(self) -> dict:
        try:
            row = self.execute_query(
                "SELECT * FROM public.v_platform_metrics_summary;",
                fetch_one=True
            )
            summary = dict(row) if row else {}
        except Exception as exc:
            logger.warning(f"Could not query v_platform_metrics_summary: {exc}")
            summary = {}
        # Provenance must reflect the buyer_type actually recorded on each
        # payment event; reporting the whole volume as one type is a false
        # claim about where the money came from.
        try:
            rows = self.execute_query(
                """
                SELECT COALESCE(NULLIF(event->>'buyer_type', ''), 'human') AS buyer_type,
                       COUNT(*)::int AS reports,
                       COALESCE(SUM(amount_usdc), 0)::float AS volume_usdc
                FROM public.qma_payment_events
                WHERE COALESCE(NULLIF(event->>'buyer_type', ''), 'human') <> 'dry_run'
                GROUP BY 1;
                """,
                fetch_all=True
            ) or []
            counts = {
                str(r["buyer_type"]).lower(): {
                    "reports": int(r["reports"]),
                    "volume_usdc": float(r["volume_usdc"]),
                }
                for r in rows
            }
            summary["buyer_type_counts"] = {
                "human": counts.get("human", {"reports": 0, "volume_usdc": 0.0}),
                "agent": counts.get("agent", {"reports": 0, "volume_usdc": 0.0}),
                **{k: v for k, v in counts.items() if k not in ("human", "agent")},
            }
        except Exception as exc:
            logger.warning(f"Could not aggregate buyer_type provenance: {exc}")
        return summary

    def load_payer_leaderboard_view(self, limit: int = 50) -> list:
        try:
            rows = self.execute_query(
                "SELECT * FROM public.v_payer_traction_leaderboard LIMIT %s;",
                (limit,),
                fetch_all=True
            ) or []
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning(f"Could not query v_payer_traction_leaderboard: {exc}")
            return []

    def load_provider_revenue_view(self) -> list:
        try:
            rows = self.execute_query(
                "SELECT * FROM public.v_provider_revenue_breakdown;",
                fetch_all=True
            ) or []
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning(f"Could not query v_provider_revenue_breakdown: {exc}")
            return []

    def load_recent_settled_events(self, limit: int = 20) -> list:
        try:
            rows = self.execute_query(
                """
                SELECT event FROM public.qma_payment_events
                WHERE (gateway_status IN ('SETTLED', 'COMPLETED', 'completed', 'ACCEPTED', 'accepted') OR transaction_hash IS NOT NULL)
                ORDER BY paid_at DESC NULLS LAST, created_at DESC
                LIMIT %s;
                """,
                (limit,),
                fetch_all=True
            ) or []
            return [r["event"] for r in rows if "event" in r]
        except Exception as exc:
            logger.warning(f"Could not load recent settled events from Postgres: {exc}")
            return []

    def save_creator_claim(self, record: dict) -> None:
        # Claims are money-critical: a failed write must fail closed, never
        # vanish behind a warning while the caller reports success.
        wallet = record.get("creator_wallet") or record.get("claimant_address")
        amount = float(record.get("amount_usdc") or 0.0)
        self._upsert("qma_creator_claims", [{
            "claim_id": record["claim_id"],
            "creator_wallet": normalize_address(wallet) if wallet else None,
            "amount_usdc": amount,
            "claim": record,
        }], "claim_id")

    def reserve_agent_wallet_spend(self, wallet_address: str, amount: float, spend_cap: float = 10000.0) -> bool:
        norm = normalize_address(wallet_address)
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT public.reserve_agent_wallet_spend(%s, %s, %s);",
                    (norm, amount, spend_cap),
                )
                conn.commit()
                res = cur.fetchone()
                return bool(res and res[0])
        finally:
            self.put_connection(conn)

    def release_agent_wallet_spend(self, wallet_address: str, amount: float) -> bool:
        norm = normalize_address(wallet_address)
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT public.release_agent_wallet_spend(%s, %s);",
                    (norm, amount),
                )
                conn.commit()
                return True
        finally:
            self.put_connection(conn)

    def reserve_session_spend(self, session_id: str, amount: float) -> bool:
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT public.reserve_session_spend(%s, %s);",
                    (session_id, amount),
                )
                conn.commit()
                res = cur.fetchone()
                return bool(res and res[0])
        finally:
            self.put_connection(conn)

    def release_session_spend(self, session_id: str, amount: float) -> bool:
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT public.release_session_spend(%s, %s);",
                    (session_id, amount),
                )
                conn.commit()
                return True
        finally:
            self.put_connection(conn)

    def load_wallet_spending_events(self, address: str) -> list:
        result = []
        norm = normalize_address(address)
        invs = self.execute_query(
            "SELECT invoice FROM public.qma_invoices WHERE payer_address = %s ORDER BY created_at DESC LIMIT 500;",
            (norm,),
            fetch_all=True
        ) or []
        result.extend(r["invoice"] for r in invs if "invoice" in r)
        evts = self.execute_query(
            "SELECT event FROM public.qma_payment_events WHERE payer_address = %s ORDER BY paid_at DESC LIMIT 500;",
            (norm,),
            fetch_all=True
        ) or []
        result.extend(r["event"] for r in evts if "event" in r)
        return result

    def reserve_withdrawal(self, operation_id: str, operation: dict) -> dict:
        try:
            row = self.execute_query(
                "SELECT operation FROM public.qma_withdrawals WHERE operation_id = %s;",
                (operation_id,),
                fetch_one=True
            )
            if row and "operation" in row:
                op = row["operation"]
                if isinstance(op, str):
                    try:
                        op = json.loads(op)
                    except Exception:
                        pass
                if isinstance(op, dict):
                    return op
        except Exception as exc:
            logger.warning(f"Could not load withdrawal from Postgres: {exc}")

        wallet_address = operation.get("wallet_address") or operation.get("address")
        amount = float(operation.get("amount_usdc") or operation.get("amount") or 0.0)
        try:
            self.execute_query(
                """
                INSERT INTO public.qma_withdrawals (operation_id, wallet_address, amount_usdc, operation, created_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (operation_id) DO NOTHING;
                """,
                (operation_id, wallet_address, amount, PgJson(operation) if PgJson else json.dumps(operation))
            )
            row = self.execute_query(
                "SELECT operation FROM public.qma_withdrawals WHERE operation_id = %s;",
                (operation_id,),
                fetch_one=True
            )
            if row and "operation" in row:
                op = row["operation"]
                if isinstance(op, str):
                    try:
                        op = json.loads(op)
                    except Exception:
                        pass
                if isinstance(op, dict):
                    return op
        except Exception as exc:
            logger.warning(f"Could not reserve withdrawal in Postgres: {exc}")

        if not hasattr(self, "_withdrawals"):
            self._withdrawals = {}
        return self._withdrawals.setdefault(operation_id, operation)

    def save_withdrawal(self, operation_id: str, operation: dict) -> None:
        wallet_address = operation.get("wallet_address") or operation.get("address")
        amount = float(operation.get("amount_usdc") or operation.get("amount") or 0.0)
        try:
            self.execute_query(
                """
                INSERT INTO public.qma_withdrawals (operation_id, wallet_address, amount_usdc, operation, created_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (operation_id) DO UPDATE SET
                    wallet_address = EXCLUDED.wallet_address,
                    amount_usdc = EXCLUDED.amount_usdc,
                    operation = EXCLUDED.operation;
                """,
                (operation_id, wallet_address, amount, PgJson(operation) if PgJson else json.dumps(operation))
            )
        except Exception as exc:
            logger.warning(f"Could not save withdrawal in Postgres: {exc}")

        if not hasattr(self, "_withdrawals"):
            self._withdrawals = {}
        self._withdrawals[operation_id] = operation

    # ---------------------------------------------------------------------------
    # PostgREST Compatibility Layer for sessions.py (_request, _upsert, rpc)
    # ---------------------------------------------------------------------------
    def _request(self, method: str, table: str, *, params: Optional[dict] = None, json_body=None, prefer: str = ""):
        clean_table = table.split("?")[0].strip("/")
        params = params or {}
        
        if clean_table.startswith("rpc/"):
            fn_name = clean_table.split("/", 1)[1]
            return self.rpc(fn_name, json_body or {})

        conn = self.get_connection()
        try:
            def _sql_column_expr(col_name: str) -> str:
                if "->>" in col_name:
                    col, field = col_name.split("->>", 1)
                    col_clean = col.replace('"', '').strip()
                    field_clean = field.replace("'", "").strip()
                    return f'"{col_clean}"->>\'{field_clean}\''
                elif "->" in col_name:
                    col, field = col_name.split("->", 1)
                    col_clean = col.replace('"', '').strip()
                    field_clean = field.replace("'", "").strip()
                    return f'"{col_clean}"->\'{field_clean}\''
                else:
                    col_clean = col_name.replace('"', '').strip()
                    return f'"{col_clean}"'

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if method == "GET":
                    where_clauses = []
                    query_params = []
                    limit = 5000
                    for k, v in params.items():
                        if k == "limit":
                            try:
                                limit = int(v)
                            except ValueError:
                                pass
                        elif k in ("select", "order", "Range", "Range-Unit"):
                            continue
                        elif isinstance(v, str) and v.startswith("eq."):
                            where_clauses.append(f'{_sql_column_expr(k)} = %s')
                            query_params.append(v[3:])
                        elif isinstance(v, str) and v.startswith("neq."):
                            where_clauses.append(f'{_sql_column_expr(k)} != %s')
                            query_params.append(v[4:])
                    
                    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                    sql = f'SELECT * FROM public."{clean_table}"{where_sql} LIMIT {limit};'
                    cur.execute(sql, tuple(query_params))
                    return cur.fetchall()

                elif method == "POST":
                    rows = json_body if isinstance(json_body, list) else [json_body] if json_body else []
                    on_conflict = params.get("on_conflict", "id")
                    if rows:
                        self._upsert(clean_table, rows, on_conflict)
                    return None

                elif method == "PATCH":
                    where_clauses = []
                    query_params = []
                    for k, v in params.items():
                        if isinstance(v, str) and v.startswith("eq."):
                            where_clauses.append(f'{_sql_column_expr(k)} = %s')
                            query_params.append(v[3:])
                    
                    if not where_clauses or not json_body:
                        return None
                    
                    set_clauses = []
                    set_values = []
                    array_cols = {"allowed_providers", "allowed_tiers", "redirect_uris"}
                    for k, v in json_body.items():
                        set_clauses.append(f'"{k}" = %s')
                        if k in array_cols:
                            set_values.append(list(v) if v is not None else None)
                        elif isinstance(v, (dict, list)):
                            set_values.append(PgJson(v))
                        else:
                            set_values.append(v)
                    
                    sql = f'UPDATE public."{clean_table}" SET {", ".join(set_clauses)} WHERE {" AND ".join(where_clauses)};'
                    cur.execute(sql, tuple(set_values + query_params))
                    conn.commit()
                    return None

                elif method == "DELETE":
                    where_clauses = []
                    query_params = []
                    for k, v in params.items():
                        if isinstance(v, str) and v.startswith("eq."):
                            where_clauses.append(f'{_sql_column_expr(k)} = %s')
                            query_params.append(v[3:])
                    if where_clauses:
                        sql = f'DELETE FROM public."{clean_table}" WHERE {" AND ".join(where_clauses)};'
                        cur.execute(sql, tuple(query_params))
                        conn.commit()
                    return None
        finally:
            self.put_connection(conn)

    def _get_table_columns(self, table: str) -> set:
        if not hasattr(self, "_column_cache"):
            self._column_cache = {}
        clean_table = table.split("?")[0].strip("/")
        if clean_table not in self._column_cache:
            rows = self.execute_query(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s;",
                (clean_table,),
                fetch_all=True
            ) or []
            self._column_cache[clean_table] = {r["column_name"] for r in rows}
        return self._column_cache[clean_table]

    def _upsert(self, table: str, rows: list[dict], conflict: str) -> None:
        if not rows:
            return
        clean_table = table.split("?")[0].strip("/")
        array_cols = {"allowed_providers", "allowed_tiers", "redirect_uris"}
        valid_cols = self._get_table_columns(clean_table)
        conn = self.get_connection()
        try:
            with conn.cursor() as cur:
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    filtered_row = {k: v for k, v in row.items() if not valid_cols or k in valid_cols}
                    if not filtered_row:
                        continue
                    cols = list(filtered_row.keys())
                    vals = []
                    for c in cols:
                        v = filtered_row[c]
                        if c in array_cols:
                            vals.append(list(v) if v is not None else None)
                        elif isinstance(v, (dict, list)):
                            vals.append(PgJson(v))
                        else:
                            vals.append(v)
                    placeholders = ", ".join(["%s"] * len(cols))
                    col_names = ", ".join([f'"{c}"' for c in cols])
                    update_set = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in cols if c != conflict])
                    
                    if update_set:
                        sql = f'INSERT INTO public."{clean_table}" ({col_names}) VALUES ({placeholders}) ON CONFLICT ("{conflict}") DO UPDATE SET {update_set};'
                    else:
                        sql = f'INSERT INTO public."{clean_table}" ({col_names}) VALUES ({placeholders}) ON CONFLICT ("{conflict}") DO NOTHING;'
                    cur.execute(sql, tuple(vals))
                conn.commit()
        finally:
            self.put_connection(conn)

    def rpc(self, fn_name: str, payload: Optional[dict] = None):
        payload = payload or {}
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if fn_name == "claim_agent_session_lease":
                    worker_id = payload.get("p_worker_id") or "worker_1"
                    duration = int(payload.get("p_lease_duration_seconds", 60))
                    cur.execute("SELECT * FROM public.claim_agent_session_lease(%s, %s);", (worker_id, duration))
                    conn.commit()
                    return cur.fetchall()
                elif fn_name in ("acquire_session_tick_lease", "pick_queued_session"):
                    worker_id = payload.get("p_worker_id") or "worker_1"
                    duration = int(payload.get("p_lease_duration_sec", 60))
                    cur.execute("SELECT * FROM public.claim_agent_session_lease(%s, %s);", (worker_id, duration))
                    conn.commit()
                    return cur.fetchall()
                elif fn_name == "heartbeat_session_lease":
                    sid = payload.get("p_session_id") or payload.get("session_id")
                    duration = int(payload.get("p_lease_duration_sec") or 60)
                    cur.execute(
                        "UPDATE public.agent_sessions SET lease_expires_at = NOW() + (%s || ' seconds')::INTERVAL WHERE id = %s;",
                        (duration, sid)
                    )
                    conn.commit()
                    return True
                elif fn_name == "release_session_tick_lease":
                    sid = payload.get("p_session_id") or payload.get("session_id")
                    cur.execute(
                        "UPDATE public.agent_sessions SET lease_owner = NULL, lease_expires_at = NULL WHERE id = %s;",
                        (sid,)
                    )
                    conn.commit()
                    return True
                elif fn_name in ("append_qma_ledger_event", "append_ledger_entry"):
                    actor = payload.get("p_actor", "agent")
                    domain = payload.get("p_domain", "treasury")
                    action = payload.get("p_action", "settlement")
                    summary = payload.get("p_summary", "")
                    detail = PgJson(payload.get("p_detail", {})) if PgJson else json.dumps(payload.get("p_detail", {}))
                    body_hash = payload.get("p_body_hash", "")
                    signature = payload.get("p_signature", "")
                    cur.execute(
                        "SELECT * FROM public.append_qma_ledger_event(%s, %s, %s, %s, %s, %s, %s);",
                        (actor, domain, action, summary, detail, body_hash, signature)
                    )
                    conn.commit()
                    res = cur.fetchone()
                    return dict(res) if res else None
                elif fn_name == "reserve_agent_wallet_spend":
                    addr = payload.get("p_wallet_address")
                    amt = payload.get("p_amount", 0)
                    cap = payload.get("p_spend_cap", 10000)
                    cur.execute(
                        "SELECT public.reserve_agent_wallet_spend(%s, %s, %s);",
                        (addr, amt, cap)
                    )
                    conn.commit()
                    res = cur.fetchone()
                    return bool(res and list(res.values())[0]) if isinstance(res, dict) else bool(res and res[0])
                elif fn_name == "release_agent_wallet_spend":
                    addr = payload.get("p_wallet_address")
                    amt = payload.get("p_amount", 0)
                    cur.execute(
                        "SELECT public.release_agent_wallet_spend(%s, %s);",
                        (addr, amt)
                    )
                    conn.commit()
                    return True
                elif fn_name == "reserve_session_spend":
                    sid = payload.get("p_session_id") or payload.get("session_id")
                    amt = payload.get("p_amount", 0)
                    cur.execute(
                        "SELECT public.reserve_session_spend(%s, %s);",
                        (sid, amt)
                    )
                    conn.commit()
                    res = cur.fetchone()
                    return bool(res and list(res.values())[0]) if isinstance(res, dict) else bool(res and res[0])
                elif fn_name == "release_session_spend":
                    sid = payload.get("p_session_id") or payload.get("session_id")
                    amt = payload.get("p_amount", 0)
                    cur.execute(
                        "SELECT public.release_session_spend(%s, %s);",
                        (sid, amt)
                    )
                    conn.commit()
                    return True
                elif fn_name == "checkpoint_session_tick":
                    sid = payload.get("p_session_id") or payload.get("session_id")
                    worker_id = payload.get("p_worker_id") or payload.get("worker_id") or "worker_1"
                    run_gen = int(payload.get("p_run_generation") or payload.get("run_generation") or 1)
                    st = payload.get("p_status") or payload.get("status") or "running"
                    rs = payload.get("p_runtime_state") if "p_runtime_state" in payload else payload.get("runtime_state", {})
                    rs_json = PgJson(rs) if PgJson else json.dumps(rs)
                    next_sec = int(payload.get("p_next_run_in_sec") or payload.get("next_run_in_sec") or 15)
                    cur.execute(
                        "SELECT public.checkpoint_session_tick(%s, %s, %s, %s, %s, %s);",
                        (sid, worker_id, run_gen, st, rs_json, next_sec)
                    )
                    conn.commit()
                    res = cur.fetchone()
                    return bool(res and list(res.values())[0]) if isinstance(res, dict) else bool(res and res[0])
                elif fn_name == "reclaim_expired_leases":
                    try:
                        cur.execute("SELECT public.reclaim_expired_leases();")
                        conn.commit()
                        res = cur.fetchone()
                        val = list(res.values())[0] if isinstance(res, dict) else (res[0] if res else 0)
                        return int(val or 0)
                    except Exception:
                        conn.rollback()
                        cur.execute(
                            "UPDATE public.agent_sessions SET lease_owner = NULL, lease_expires_at = NULL, updated_at = NOW() "
                            "WHERE lease_owner IS NOT NULL AND lease_expires_at < NOW() AND status NOT IN ('completed', 'failed', 'stopped');"
                        )
                        count = cur.rowcount
                        conn.commit()
                        return int(count or 0)
                return None
        finally:
            self.put_connection(conn)



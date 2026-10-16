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

logger = logging.getLogger("QMA-Storage")


def _storage_json_lock_key(path: str) -> str:
    return "storage_json:" + os.path.basename(str(path or ""))


def wallet_matches(record: dict, address: str) -> bool:
    normalized = normalize_address(address)
    if not normalized or not isinstance(record, dict) or has_fabricated_settlement(record):
        return False
    return any(
        normalize_address(record.get(field)) == normalized
        for field in ("payer_address", "buyer_wallet_address")
    )


def event_key(event: dict) -> str:
    return str(event.get("settlement_id") or event.get("invoice_id") or "")


PAYMENT_EVENT_SUMMARY_SELECT = (
    "event_id,invoice_id,settlement_id,payer_address,symbol,tier,provider_id,"
    "amount_usdc,gateway_status,transaction_hash,explorer_url,paid_at"
)

PAID_REPORT_SUMMARY_SELECT = (
    "entitlement_id,payer_address,symbol,tier,provider_id,query_hash,settlement_id,"
    "paid_at,saved_at"
)

PAID_INVOICE_EVENT_SELECT = (
    "invoice_id,status,settlement_id,payer_address,symbol,tier,provider_id,query_hash,"
    "paid_at,invoice"
)


def payment_event_from_row(row: dict) -> dict:
    event = row.get("event") if isinstance(row.get("event"), dict) else {}
    merged = {
        **event,
        "event_id": row.get("event_id") or event.get("event_id"),
        "invoice_id": row.get("invoice_id") or event.get("invoice_id"),
        "settlement_id": row.get("settlement_id") or event.get("settlement_id"),
        "payer_address": row.get("payer_address") or event.get("payer_address"),
        "symbol": row.get("symbol") or event.get("symbol"),
        "tier": row.get("tier") or event.get("tier"),
        "provider_id": row.get("provider_id") or event.get("provider_id", "funding_memory"),
        "amount_usdc": row.get("amount_usdc") if row.get("amount_usdc") is not None else event.get("amount_usdc"),
        "gateway_status": row.get("gateway_status") or event.get("gateway_status"),
        "transaction_hash": row.get("transaction_hash") or event.get("transaction_hash"),
        "explorer_url": row.get("explorer_url") or event.get("explorer_url"),
        "paid_at": row.get("paid_at") if row.get("paid_at") is not None else event.get("paid_at"),
    }
    return {key: value for key, value in merged.items() if value is not None}


def paid_report_summary_from_row(row: dict) -> dict:
    entitlement = row.get("entitlement") if isinstance(row.get("entitlement"), dict) else {}
    has_report = isinstance(entitlement.get("report"), dict) if "entitlement" in row else True
    summary = {
        "entitlement_id": row.get("entitlement_id") or entitlement.get("entitlement_id"),
        "payer_address": row.get("payer_address") or entitlement.get("payer_address"),
        "buyer_wallet_address": row.get("buyer_wallet_address") or entitlement.get("buyer_wallet_address"),
        "symbol": row.get("symbol") or entitlement.get("symbol"),
        "tier": row.get("tier") or entitlement.get("tier"),
        "provider_id": row.get("provider_id") or entitlement.get("provider_id", "funding_memory"),
        "query_hash": row.get("query_hash") or entitlement.get("query_hash"),
        "settlement_id": row.get("settlement_id") or entitlement.get("settlement_id"),
        "paid_at": row.get("paid_at") if row.get("paid_at") is not None else entitlement.get("paid_at"),
        "saved_at": row.get("saved_at") if row.get("saved_at") is not None else entitlement.get("saved_at"),
        "buyer_type": entitlement.get("buyer_type"),
        "gateway_status": entitlement.get("gateway_status"),
        "transaction_hash": entitlement.get("transaction_hash"),
        "explorer_url": entitlement.get("explorer_url"),
        "amount_usdc": entitlement.get("amount_usdc"),
        "query": entitlement.get("query"),
        "has_report": has_report,
    }
    return {key: value for key, value in summary.items() if value is not None}


def invoice_payment_events(invoice: dict) -> list:
    if not isinstance(invoice, dict):
        return []
    split = invoice.get("split") if isinstance(invoice.get("split"), dict) else {}
    if split.get("mode") == "x402_direct_split":
        events = []
        for leg in split.get("legs") or []:
            if leg.get("status") == "paid" and leg.get("settlement_id"):
                events.append({
                    "event_id": f"{invoice.get('invoice_id')}:{leg.get('leg_id')}",
                    "invoice_id": invoice.get("invoice_id"),
                    "settlement_id": leg.get("settlement_id"),
                    "payer_address": leg.get("payer_address") or invoice.get("payer_address"),
                    "buyer_wallet_address": leg.get("buyer_wallet_address") or invoice.get("buyer_wallet_address"),
                    "symbol": invoice.get("symbol"),
                    "tier": invoice.get("tier"),
                    "provider_id": invoice.get("provider_id", "funding_memory"),
                    "query_hash": invoice.get("query_hash"),
                    "paid_at": leg.get("paid_at") or invoice.get("paid_at"),
                    "amount_usdc": leg.get("amount_usdc"),
                    "amount_raw": leg.get("amount_raw"),
                    "gateway_status": leg.get("gateway_status"),
                    "transaction_hash": leg.get("transaction_hash"),
                    "explorer_url": leg.get("explorer_url"),
                    "provider_owner_wallet": invoice.get("owner_wallet"),
                    "buyer_type": invoice.get("buyer_type", "human"),
                    "synthetic": invoice.get("synthetic", False),
                    "agent_label": invoice.get("agent_label"),
                    "run_source": invoice.get("run_source"),
                    "resource_type": invoice.get("resource_type"),
                    "settlement": invoice.get("settlement"),
                    "accounting": invoice.get("accounting"),
                    "split_leg": {
                        "leg_id": leg.get("leg_id"),
                        "role": leg.get("role"),
                        "pay_to": leg.get("pay_to"),
                        "amount_raw": leg.get("amount_raw"),
                        "amount_usdc": leg.get("amount_usdc"),
                    },
                })
        return events
    return [{
        "invoice_id": invoice.get("invoice_id"),
        "settlement_id": invoice.get("settlement_id"),
        "payer_address": invoice.get("payer_address"),
        "buyer_wallet_address": invoice.get("buyer_wallet_address"),
        "symbol": invoice.get("symbol"),
        "tier": invoice.get("tier"),
        "provider_id": invoice.get("provider_id", "funding_memory"),
        "query_hash": invoice.get("query_hash"),
        "paid_at": invoice.get("paid_at"),
        "provider_owner_wallet": invoice.get("owner_wallet"),
        "buyer_type": invoice.get("buyer_type", "human"),
        "synthetic": invoice.get("synthetic", False),
        "agent_label": invoice.get("agent_label"),
        "run_source": invoice.get("run_source"),
        "resource_type": invoice.get("resource_type"),
        "amount_usdc": invoice.get("amount"),
        "amount_raw": invoice.get("amount_raw"),
        "gateway_status": invoice.get("gateway_status"),
        "transaction_hash": invoice.get("transaction_hash"),
        "explorer_url": invoice.get("explorer_url"),
    }]

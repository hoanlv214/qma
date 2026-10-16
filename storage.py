"""Backward-compatibility shim for QMA storage.

Authoritative storage engine now lives in `backend.app.infrastructure.storage`.
This shim re-exports all symbols to preserve compatibility with existing callers,
external scripts, and tests.
"""

from backend.app.infrastructure.storage import (
    PAYMENT_EVENT_SUMMARY_SELECT,
    PAID_INVOICE_EVENT_SELECT,
    PAID_REPORT_SUMMARY_SELECT,
    _storage_json_lock_key,
    create_storage_backend,
    event_key,
    invoice_payment_events,
    JsonStorage,
    normalize_address,
    paid_report_summary_from_row,
    payment_event_from_row,
    PostgresStorage,
    SupabaseStorage,
    wallet_matches,
)

__all__ = [
    "PAYMENT_EVENT_SUMMARY_SELECT",
    "PAID_INVOICE_EVENT_SELECT",
    "PAID_REPORT_SUMMARY_SELECT",
    "_storage_json_lock_key",
    "create_storage_backend",
    "event_key",
    "invoice_payment_events",
    "JsonStorage",
    "normalize_address",
    "paid_report_summary_from_row",
    "payment_event_from_row",
    "PostgresStorage",
    "SupabaseStorage",
    "wallet_matches",
]

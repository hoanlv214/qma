"""Infrastructure storage module for QMA.

Unified persistence layer supporting PostgreSQL (local & production), Supabase, and JSON (test/offline).
"""

from backend.app.infrastructure.storage.base import (
    PAYMENT_EVENT_SUMMARY_SELECT,
    PAID_INVOICE_EVENT_SELECT,
    PAID_REPORT_SUMMARY_SELECT,
    _storage_json_lock_key,
    event_key,
    invoice_payment_events,
    normalize_address,
    paid_report_summary_from_row,
    payment_event_from_row,
    wallet_matches,
)
from backend.app.infrastructure.storage.factory import create_storage_backend
from backend.app.infrastructure.storage.json_store import JsonStorage
from backend.app.infrastructure.storage.postgres import PostgresStorage
from backend.app.infrastructure.storage.supabase import SupabaseStorage

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

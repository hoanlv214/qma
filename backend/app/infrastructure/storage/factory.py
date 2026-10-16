import os
from typing import Optional

from backend.app.infrastructure.storage.json_store import JsonStorage
from backend.app.infrastructure.storage.postgres import PostgresStorage


def create_storage_backend(
    *,
    ledger_path: str,
    reports_path: str,
    invoices_path: str,
    creators_path: str,
    provider_controls_path: str,
):
    """Factory to instantiate the appropriate persistence storage backend.

    Selection hierarchy:
    1. QMA_STORAGE_BACKEND == "json" -> JsonStorage (for testing and local offline suites).
    2. QMA_STORAGE_BACKEND == "postgres" or database URL configured -> PostgresStorage.
       Fails loudly (RuntimeError) if psycopg2 is missing, DB is unreachable, or URL is empty.
    3. Otherwise -> raises RuntimeError requiring database URL or explicit QMA_STORAGE_BACKEND=json.
    """
    storage_backend = os.getenv("QMA_STORAGE_BACKEND", "").lower().strip()
    try:
        from backend.app.core.config import resolve_database_url
        database_url = resolve_database_url()
    except Exception:
        database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("QMA_DATABASE_URL")

    # Priority 1: Explicit JSON (tests only)
    if storage_backend == "json":
        return JsonStorage(
            ledger_path=ledger_path,
            reports_path=reports_path,
            invoices_path=invoices_path,
            creators_path=creators_path,
            provider_controls_path=provider_controls_path,
        )

    # Priority 2: PostgreSQL (production target)
    if storage_backend == "postgres" or database_url:
        if not database_url:
            mode = os.getenv("QMA_NETWORK_MODE", "mainnet").strip().lower()
            raise RuntimeError(
                f"QMA_STORAGE_BACKEND=postgres requested (or production active) for network mode '{mode}', "
                f"but no database URL was found. Please set DATABASE_URL_{mode.upper()} or DATABASE_URL."
            )
        try:
            return PostgresStorage(database_url)
        except Exception as exc:
            mode = os.getenv("QMA_NETWORK_MODE", "mainnet").strip().lower()
            raise RuntimeError(
                f"Failed to initialize PostgresStorage for network mode '{mode}': {exc}. Ensure psycopg2 is installed, "
                "database URL is set, and the PostgreSQL database is reachable."
            ) from exc

    # Priority 3: Otherwise fail-fast (no silent fallback)
    raise RuntimeError(
        "Local PostgreSQL storage requires DATABASE_URL, DATABASE_URL_MAINNET, or DATABASE_URL_TESTNET to be set, "
        "or explicit QMA_STORAGE_BACKEND=json for tests."
    )

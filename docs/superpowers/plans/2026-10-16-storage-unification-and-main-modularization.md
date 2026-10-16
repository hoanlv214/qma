# Storage Unification and Main Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate data storage from root `storage.py` into a unified `backend/app/infrastructure/storage/` module with PostgreSQL as the local/production authoritative standard, and decompose the 3,310-line `backend/app/main.py` monolith into dedicated domain services while retiring the root shim and maintaining 100% green test passes across all 570+ test cases.

**Architecture:** 
1. Storage Infrastructure: Migrate `PostgresStorage`, `SupabaseStorage`, and `JsonStorage` into `backend/app/infrastructure/storage/` (modular drivers with connection pooling and PostgreSQL primary resolution via `resolve_database_url()`), keeping a backward-compatibility re-export shim at root `storage.py` for legacy scripts and test fixtures.
2. Main Monolith Decomposition: Extract payment lifecycle, GenLayer consensus verification & reconcile loops, report generation, and market anomaly scanning out of `backend/app/main.py` into dedicated, cohesive domain services in `backend/app/services/`.
3. Canonical Entrypoint: Update `render.yaml` startCommand to `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT --workers 1`, ensuring seamless cloud deployment without depending on root-level shims.

**Tech Stack:** Python 3.14, FastAPI, PostgreSQL (`psycopg2`), Starlette, Pytest, Uvicorn.

**Spec:** User instruction on PostgreSQL local standard, storage consolidation, and Ponytail modularization of `main.py`.

## Global Constraints

- Never break active Render deployment: keep route paths, OpenAPI schema, and response keys 100% stable.
- Local PostgreSQL is the authoritative standard (`DATABASE_URL`, `DATABASE_URL_MAINNET`, `DATABASE_URL_TESTNET`); JSON storage is strictly a fallback for offline/isolated unit tests.
- Re-export all extracted functions in `backend/app/main.py` to prevent breaking existing test monkeypatches (`monkeypatch.setattr(main, ...)`).
- Zero regressions allowed: all 570+ tests across `tests/unit/`, `tests/services/`, and `tests/api_v1/` must pass after every task.
- Independence Policy: zero mentions of hackathons or competitions.

## Review Focus

1. `DATABASE_URL` routing between mainnet and testnet partitions resolves correctly without cross-database pollution.
2. Advisory lock serialization (`pg_advisory_xact_lock`) remains intact during settlement claiming in `PostgresStorage`.
3. Unit tests monkeypatching `main.<func>` continue resolving correctly via module-level re-exports.
4. Render start command in `render.yaml` starts `backend.app.main:app` cleanly without import errors.
5. In-process re-entrant locks (`cross_process_lock` using `threading.RLock`) are maintained across extracted services.

---

### Task 1: Create `backend/app/infrastructure/storage/` Package & Drivers

**Files:**
- Create: `backend/app/infrastructure/storage/__init__.py`
- Create: `backend/app/infrastructure/storage/base.py`
- Create: `backend/app/infrastructure/storage/json_store.py`
- Create: `backend/app/infrastructure/storage/supabase.py`
- Create: `backend/app/infrastructure/storage/postgres.py`
- Create: `backend/app/infrastructure/storage/factory.py`
- Modify: `storage.py` (replace implementation with re-exports from infrastructure)
- Test: `tests/unit/test_storage_double_claim.py`, `tests/integration/test_postgres_runtime_state.py`

**Interfaces:**
- Produces: `create_storage_backend(...)`, `PostgresStorage`, `SupabaseStorage`, `JsonStorage` from `backend.app.infrastructure.storage`
- Consumes: `backend.app.core.config.resolve_database_url`, `backend.app.core.state.cross_process_lock`

- [ ] **Step 1: Write test verifying import from `backend.app.infrastructure.storage`**

```python
def test_infrastructure_storage_exports():
    from backend.app.infrastructure.storage import (
        create_storage_backend,
        PostgresStorage,
        SupabaseStorage,
        JsonStorage,
    )
    assert callable(create_storage_backend)
    assert PostgresStorage is not None
    assert JsonStorage is not None
```

- [ ] **Step 2: Run test to verify it fails before creation**

Run: `uv run pytest tests/unit/test_infrastructure_storage.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Extract and modularize drivers from `storage.py` into `backend/app/infrastructure/storage/`**

- `base.py`: Shared utilities (`normalize_address`, `wallet_matches`, `_storage_json_lock_key`).
- `json_store.py`: `JsonStorage` class for local fallback/tests.
- `supabase.py`: `SupabaseStorage` class for PostgREST HTTP queries.
- `postgres.py`: `PostgresStorage` class for direct PostgreSQL connection pooling with advisory locking.
- `factory.py`: `create_storage_backend()` with PostgreSQL priority via `resolve_database_url()`.
- `__init__.py`: Clean public API export.
- `storage.py` at root: Re-export everything from `backend.app.infrastructure.storage` to maintain 100% backward compatibility for external scripts.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_infrastructure_storage.py tests/unit/test_storage_double_claim.py -v`
Expected: PASS

---

### Task 2: Connect Repository Layer to Storage Infrastructure

**Files:**
- Modify: `backend/app/repositories/storage.py`
- Modify: `backend/app/main.py:35, 830-845`
- Test: `tests/unit/test_financial_integrity.py`, `tests/integration/test_postgres_concurrency_race.py`

**Interfaces:**
- Consumes: `backend.app.infrastructure.storage.create_storage_backend`
- Produces: `backend.app.repositories.storage` API with PostgreSQL-first backing

- [ ] **Step 1: Update repository imports to use `backend.app.infrastructure.storage` directly**
- In `backend/app/main.py`, change `from storage import create_storage_backend` to `from backend.app.infrastructure.storage import create_storage_backend`.
- In `backend/app/repositories/storage.py`, ensure all helper functions cleanly accept `storage_backend` conforming to `PostgresStorage` protocol.
- [ ] **Step 2: Run targeted storage and integration tests**

Run: `uv run pytest tests/unit/test_financial_integrity.py tests/integration/test_postgres_concurrency_race.py -v`
Expected: PASS

---

### Task 3: Extract Payment Domain Service (`backend/app/services/payment_service.py`)

**Files:**
- Create: `backend/app/services/payment_service.py`
- Modify: `backend/app/main.py:1200-1888`
- Test: `tests/unit/test_payment_state_machine.py`, `tests/unit/test_batch6_decision_p3s.py`

**Interfaces:**
- Produces: `create_invoice`, `get_payment_invoice_status`, `verify_payment`, `verify_split_payment`, `submit_withdraw`, `authorize_paid_invoice`
- Re-exports: `backend/app/main.py` imports and re-exports all 6 functions at top-level.

- [ ] **Step 1: Move payment lifecycle functions from `backend/app/main.py` into `backend/app/services/payment_service.py`**
- Functions: `create_invoice`, `get_payment_invoice_status`, `verify_split_payment`, `verify_payment`, `submit_withdraw`, `authorize_paid_invoice`.
- Keep dependencies explicit (importing from `backend.app.core.state`, `backend.app.repositories.storage`).
- [ ] **Step 2: Re-export functions in `backend/app/main.py`**
```python
from backend.app.services.payment_service import (
    create_invoice,
    get_payment_invoice_status,
    verify_split_payment,
    verify_payment,
    submit_withdraw,
    authorize_paid_invoice,
)
```
- [ ] **Step 3: Run payment and race condition tests**

Run: `uv run pytest tests/unit/test_payment_state_machine.py tests/unit/test_security_race_and_leakage.py tests/unit/test_batch6_decision_p3s.py -v`
Expected: PASS (all tests pass including monkeypatched tests).

---

### Task 4: Extract GenLayer Verification & Reconciler Service (`backend/app/services/genlayer_reconcile_service.py`)

**Files:**
- Create: `backend/app/services/genlayer_reconcile_service.py`
- Modify: `backend/app/main.py:2420-2665, 2666-2900`
- Test: `tests/unit/test_genlayer_commerce_e2e_and_balance_tracking.py`, `tests/unit/test_genlayer_sla.py`

**Interfaces:**
- Produces: `verify_invoice_report_with_genlayer`, `_verify_invoice_report_with_genlayer_locked`, `reconcile_arc_verdict_settlements_once`, `prewarm_genlayer_sla_for_invoice`, `_trigger_genlayer_prewarm_in_background`
- Re-exports: `backend/app/main.py` imports and re-exports these symbols.

- [ ] **Step 1: Move GenLayer verification and reconciliation functions into `genlayer_reconcile_service.py`**
- Move `_GENLAYER_PREWARM_EXECUTOR`, `prewarm_genlayer_sla_for_invoice`, `_trigger_genlayer_prewarm_in_background`, `verify_invoice_report_with_genlayer`, `_verify_invoice_report_with_genlayer_locked`, `reconcile_arc_verdict_settlements_once`.
- [ ] **Step 2: Re-export in `backend/app/main.py`**
- [ ] **Step 3: Run GenLayer verification test suites**

Run: `uv run pytest tests/unit/test_genlayer_commerce_e2e_and_balance_tracking.py tests/unit/test_genlayer_sla.py -v`
Expected: PASS

---

### Task 5: Extract Report Generation & Anomaly Live Scanner

**Files:**
- Create: `backend/app/services/report_generator_service.py`
- Create: `backend/app/services/anomaly_scanner_service.py`
- Modify: `backend/app/main.py:1979-2250, 2901-3100`
- Test: `tests/unit/test_signal_verifiability_gate.py`, `tests/unit/test_growth_pillars.py`

**Interfaces:**
- Produces: `build_provider_report`, `build_preview_report`, `invoice_report_meta`, `_build_epoch_snapshot`, `get_or_create_epoch_snapshot`, `scan_anomalies_live`
- Re-exports: `backend/app/main.py` imports and re-exports these symbols.

- [ ] **Step 1: Move report builders to `report_generator_service.py` and anomaly scanner to `anomaly_scanner_service.py`**
- [ ] **Step 2: Re-export in `backend/app/main.py`**
- [ ] **Step 3: Run report and provider tests**

Run: `uv run pytest tests/unit/test_signal_verifiability_gate.py tests/unit/test_growth_pillars.py -v`
Expected: PASS

---

### Task 6: Streamline Entrypoints, Update `render.yaml`, and Full Verification

**Files:**
- Modify: `render.yaml`
- Modify: `main.py` (root)
- Test: Full backend test suite (`tests/unit/`, `tests/services/`, `tests/api_v1/`)
- Test: OpenAPI docs gate (`tests/api_v1/test_api_openapi_docs.py`)
- Test: Frontend build (`npm run build` in `frontend/`)

**Interfaces:**
- Produces: Direct Render start command `uvicorn backend.app.main:app`
- Preserves: Root `main.py` minimal backwards-compatible redirect

- [ ] **Step 1: Update `render.yaml` startCommand**
```yaml
startCommand: uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT --workers 1
```
- [ ] **Step 2: Run complete test suite**

Run: `uv run pytest tests/unit/ tests/services/ tests/api_v1/ -q`
Expected: 570+ passed, 0 failures.

- [ ] **Step 3: Run OpenAPI documentation gate**

Run: `uv run pytest tests/api_v1/test_api_openapi_docs.py -q`
Expected: 13 passed, 0 failures.

- [ ] **Step 4: Run frontend production build**

Run: `cd frontend && npm run build`
Expected: 0 errors, build succeeds.

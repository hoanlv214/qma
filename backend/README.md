# QMA Backend Migration

This directory is the staged home for the FastAPI backend refactor.

The root `main.py` remains the current runtime source of truth while the
backend is split into smaller modules. Do not delete or rewrite root `main.py`
during the migration. Start by moving low-risk structure here, then migrate
routers and services one domain at a time with regression tests after each
step.

Current compatibility entrypoint:

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Render can keep using `uvicorn main:app` until the compatibility layer is
promoted.

## Migration status

Moved so far:

- Pydantic request schemas: `backend/app/schemas/`
- Root path/env loader anchors: `backend/app/core/config.py`
- Rate-limit path/IP helpers: `backend/app/core/rate_limit.py`
- Static shell, health, public config, gateway info, and engine profile routes: `backend/app/api/v1/endpoints/health.py`
- Provider/admin marketplace and creator application routes: `backend/app/api/v1/endpoints/providers.py`
- Platform analytics routes: `backend/app/api/v1/endpoints/platform.py`
- Market cache, live anomalies, and agent recommendation routes: `backend/app/api/v1/endpoints/market.py`
- Internal split-leg sidecar routes: `backend/app/api/v1/endpoints/internal.py`
- Payment quote and settlement lookup routes: `backend/app/api/v1/endpoints/payments.py`
- Payment state-machine helpers: `backend/app/services/payment_state_machine.py`
- Payment event formatting/pagination helpers: `backend/app/services/payment_ledger.py`

Still owned by root `main.py`:

- Live FastAPI app creation and route registration
- Payment state machine and Circle/x402 verification
- Persistence helpers and report authorization
- Wallet, public payment, creator claim, chat, and paid report endpoint bodies

Next safe slices:

1. Move wallet/profile endpoint bodies into `api/v1/endpoints/wallets.py`.
2. Move payment invoice/status/verify mutation endpoints into `api/v1/endpoints/payments.py`.
3. Move wallet profile session helpers into `services/wallet_profiles.py`.

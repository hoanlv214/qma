"""Operational Emergency Kill Switch for QMA Financial State Mutations.

Enforces fail-closed protection over all financial state mutations
(payment invoice creation, settlement verification, creator claims/withdrawals,
and treasury sweeps/redemptions).

Security and Operational Boundaries:
- QMA_EMERGENCY_STOP is an operational kill switch for the API process.
- If the environment variable or storage state cannot be read or is corrupted,
  it FAILS CLOSED (stops financial mutations immediately).
- Read-only endpoints (GET /reports, /health, /config, OpenAPI) are never blocked.
- NOTE: This is an application/process-level safeguard; it does not substitute
  for on-chain smart-contract policy limits if the signer key is compromised.
"""

from __future__ import annotations

import logging
import os
from typing import Set
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("QMA-EmergencyStop")

FINANCIAL_MUTATION_PATHS: Set[str] = {
    "/api/v1/payment/invoice",
    "/api/v1/payment/verify",
    "/api/v1/payment/withdraw",
    "/api/v1/creators/claim",
    "/api/v1/treasury/usyc/sweep",
    "/api/v1/treasury/usyc/jit-redeem",
    "/api/v1/swap/execute",
}


def is_emergency_stop_active() -> bool:
    """Check if the emergency stop is active. Fails closed on any error."""
    raw_env = os.getenv("QMA_EMERGENCY_STOP")
    if raw_env is not None and raw_env.strip() != "":
        normalized = raw_env.strip().lower()
        if normalized in {"1", "true", "yes", "on", "active", "stop"}:
            return True
        if normalized in {"0", "false", "no", "off", "inactive"}:
            # Explicitly disabled by env, but check storage if configured
            pass
        else:
            # Unrecognized/corrupted environment setting -> FAIL CLOSED
            logger.critical(
                f"[EMERGENCY STOP] Unrecognized QMA_EMERGENCY_STOP value '{raw_env}'. "
                "Failing closed to protect financial state!"
            )
            return True

    # Check database/storage backend state if supported
    try:
        from backend.app.core import state
        storage = getattr(state, "storage_backend", None)
        if storage is not None and hasattr(storage, "is_emergency_stop_active"):
            return bool(storage.is_emergency_stop_active())
    except Exception as exc:
        # Any error checking persistent storage state -> FAIL CLOSED
        logger.critical(
            f"[EMERGENCY STOP] Failed to read persistent emergency stop state: {exc}. "
            "Failing closed to protect financial state!"
        )
        return True

    return False


def assert_not_emergency_stopped(action_label: str = "Financial state mutations") -> None:
    """Raise HTTP 503 if emergency stop is currently active."""
    if is_emergency_stop_active():
        logger.warning(f"[EMERGENCY STOP] Rejected {action_label}: Kill switch is active.")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "EMERGENCY_STOP_ACTIVE",
                "message": f"{action_label} are temporarily halted under the QMA emergency kill switch.",
                "code": "EMERGENCY_STOP",
            },
        )


async def emergency_stop_middleware(request: Request, call_next):
    """FastAPI middleware intercepting financial mutations when kill switch is active."""
    path = request.url.path.rstrip("/")
    # Read-only methods (GET, HEAD, OPTIONS) are NEVER blocked
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        if path in FINANCIAL_MUTATION_PATHS or any(path.startswith(p) for p in FINANCIAL_MUTATION_PATHS):
            if is_emergency_stop_active():
                logger.warning(
                    f"[EMERGENCY STOP] Intercepted {request.method} {path} — kill switch active."
                )
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "EMERGENCY_STOP_ACTIVE",
                        "message": "Financial state mutations are temporarily halted under the QMA emergency kill switch.",
                        "code": "EMERGENCY_STOP",
                        "path": path,
                    },
                )

    return await call_next(request)

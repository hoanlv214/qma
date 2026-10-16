"""QMA Backend — FastAPI application entrypoint.

This is the canonical server module. It creates the FastAPI app, initializes
all state, registers middleware and routers.

Run with:
    uvicorn backend.app.main:app --reload
"""

import os
import asyncio
import concurrent.futures
import threading
import time
import logging
import hashlib
import requests
import json
from typing import Any, Dict, Optional
from types import SimpleNamespace
from contextlib import suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from scalar_fastapi import get_scalar_api_reference

import paid_intelligence_kit as paid_kit
from market_data import create_market_data_adapter
from qma_engine import QMAEngine

from backend.app.infrastructure.storage import create_storage_backend

from backend.app.core.static_config import app_setting
from backend.app.core.config import (
    settings,
    load_local_env,
    PUBLIC_API_URL,
    # Payment / pricing
    PAYMENT_AMOUNT_USDC,
    PAYMENT_RESOURCE_TYPE,
    PAYMENT_NETWORK,
    PAYMENT_NETWORK_NAME,
    PAYMENT_WALLET_ADDRESS,
    PLATFORM_TREASURY_ADDRESS,
    # Arc / Circle Gateway
    ARC_GATEWAY_BASE_URL,
    ARC_GATEWAY_API,
    ARC_EXPLORER,
    ARC_GATEWAY_WALLET,
    ARC_TESTNET_USDC,
    ARC_GATEWAY_MINTER,
    ARC_GATEWAY_INTERNAL_SECRET,
    # Withdraw
    WITHDRAW_MODE,
    WITHDRAW_RELAYER_ADDRESS,
    WITHDRAW_MIN_USDC,
    WITHDRAW_RELAY_DAILY_LIMIT,
    # Creator claims
    CREATOR_CLAIM_MIN_USDC,
    CREATOR_CLAIM_INTENT_TTL_SECONDS,
    # Settlement
    DEFAULT_SETTLEMENT_MODE,
    SPLIT_INVOICE_TTL_SECONDS,
    SETTLEMENT_RAIL,
    SETTLEMENT_CURRENCY,
    SUPPORTED_SETTLEMENT_ASSETS,
    INVOICE_TTL_SECONDS,
    # Access tokens
    ACCESS_TOKEN_TTL_SECONDS,
    WALLET_PROFILE_TOKEN_TTL_SECONDS,
    ACCESS_TOKEN_SECRET,
    SPLIT_LEG_URL_SECRET,
    SPLIT_RECEIPT_SECRET,
    # Hosted MCP / OAuth
    MCP_TOKEN_TTL_SECONDS,
    MCP_MAX_BUDGET_USDC,
    MCP_MAX_PRICE_USDC,
    MCP_CONNECT_BASE_URL,
    MCP_API_BASE_URL,
    # Admin
    ADMIN_TOKEN,
    ADMIN_WALLET_ADDRESS,
    # Rate limiting & Origin Shield
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_WINDOW_SECONDS,
    ORIGIN_SHIELD_SECRET,

    # Settlement verification
    REQUIRE_COMPLETED_SETTLEMENT,
    # Gateway deposit / batch
    GATEWAY_DEFAULT_DEPOSIT_USDC,
    GATEWAY_DEFAULT_APPROVE_USDC,
    # Cache
    CACHE_TTL_SECONDS,
)
from backend.app.core import state
from backend.app.core.rate_limit import client_ip_from_request, rate_limit_for_path
from backend.app.core.x402_spec import (
    AGENT_GUIDANCE,
    BAZAAR_EXTENSIONS,
    X_PAYMENT_INFO,
    build_402_challenge_payload,
    build_x402_accepts,
)

# Services
from backend.app.services.wallet_utils import bytes32_to_address, normalize_address, same_address
from backend.app.services.payment_signing import (
    sign_access_token,
    verify_access_token,
    sign_split_receipt,
    verify_split_receipt,
    usdc_to_raw,
    raw_usdc_str,
    raw_usdc_to_decimal_string,
)
from backend.app.services.security import (
    require_admin_token,
    has_admin_token,
    model_to_dict,
    normalize_query_for_provider,
    canonical_query_payload,
    query_fingerprint,
    paid_report_key,
)
from backend.app.services.payment_state_machine import (
    aggregate_split_gateway_status,
    invoice_access_status,
    invoice_has_failed_settlement,
    invoice_required_split_legs,
    invoice_split_mode,
    is_gateway_accepted_status,
    is_gateway_failed_status,
    is_gateway_final_status,
    payment_event_is_final,
    refresh_split_invoice_status,
    split_leg_by_id,
    split_missing_legs,
    split_paid_legs,
    gateway_status_value,
)
from backend.app.services.payment_ledger import (
    attach_report_summaries,
    compact_payment_event,
    paginate_items,
    payment_event_key,
    payment_event_tier,
)
from backend.app.services.wallet_profiles import (
    consume_wallet_profile_nonce,
    issue_wallet_profile_nonce,
    public_entitlement_row,
    public_payment_row,
    verify_wallet_profile_token as verify_wallet_profile_token_service,
    wallet_profile_message,
    wallet_profile_token_payload,
)
from backend.app.services.circle_client import (
    fetch_circle_settlement,
    fetch_gateway_balance,
    fetch_gateway_balance_cached,
    fetch_gateway_info_cached,
    fetch_creator_claim_status_cached,
    find_arc_batch_tx,
    refresh_event_batch_tx,
    refresh_invoice_batch_tx,
    maybe_refresh_unresolved_payment_events,
)
from backend.app.services.invoice_builder import (
    invoice_payment_schema,
    hydrate_payment_schema,
    allocate_split_legs_raw,
    settlement_id_already_claimed as _base_settlement_id_already_claimed,
    issue_invoice_access_token,
    invoice_payment_state_response,
    payment_requirement,
    paid_invoice_event,
    get_invoice_or_402,
)


def settlement_id_already_claimed(
    settlement_id,
    *,
    exclude_invoice_id=None,
    load_invoices_fn=None,
    invoices_db=None,
    storage_backend=None,
):
    from backend.app import main as _main
    return _base_settlement_id_already_claimed(
        settlement_id,
        exclude_invoice_id=exclude_invoice_id,
        load_invoices_fn=load_invoices_fn or getattr(_main, "load_invoices", getattr(_main, "_load_invoices", None)),
        invoices_db=invoices_db if invoices_db is not None else getattr(_main, "invoices_db", state.invoices_db),
        storage_backend=storage_backend,
    )
from backend.app.services.market_epoch import (
    begin_or_get_epoch,
    get_epoch,
    mark_epoch_tx,
    mark_epoch_verdict,
)
from backend.app.services import genlayer_arbiter
from backend.app.services.arc_verdict_settlement import (
    ArcVerdictSettlementError,
    apply_arc_settlement_checkpoint,
    arc_settlement_instruction,
    ensure_arc_settlement_plan,
    execute_arc_settlement,
    public_arc_settlement,
)
from backend.app.services.providers_meta import (
    provider_revenue_wallet,
    provider_split_metadata,
    configured_disabled_providers,
    provider_control,
    provider_metadata,
    get_provider_or_404,
    provider_ids_owned_by,
    provider_ids_by_revenue_wallet,
    build_provider_stats,
    payment_events_for_provider,
    split_leg_event,
    upsert_payment_event,
    sync_split_payment_events,
)
from backend.app.services.creator_claims import (
    build_creator_claim_message,
    recover_creator_claim_signer,
    validate_withdraw_intent,
    enforce_withdraw_relay_policy,
    record_withdraw_relay,
    canonical_provider_ids,
    creator_claim_amounts,
)
from backend.app.services.settlement_validation import (
    validate_arc_payment,
    validate_arc_split_leg_payment,
)
from backend.app.services.payment_events_service import (
    build_traction_snapshot,
    summarize_payment_events as _base_summarize_payment_events,
    merge_payment_sources,
    load_platform_payment_events,
)


def summarize_payment_events(events, provider_split_metadata_fn=None):
    from backend.app import main as _main
    fn = provider_split_metadata_fn or (lambda pid, fo: provider_split_metadata(getattr(_main, "provider_registry", None), pid, fo))
    return _base_summarize_payment_events(events, provider_split_metadata_fn=fn)
from backend.app.services.agent_recommendations import build_agent_recommendations
from backend.app.repositories import storage as repo

# Route factories
from backend.app.api.v1.endpoints.chat import create_chat_router
from backend.app.api.v1.endpoints.health import create_health_router
from backend.app.api.v1.endpoints.internal import create_internal_router
from backend.app.api.v1.endpoints.agent import create_agent_router
from backend.app.api.v1.endpoints.market import create_market_router
from backend.app.api.v1.endpoints.oauth import create_oauth_router
from backend.app.api.v1.endpoints.payments import create_payments_router
from backend.app.api.v1.endpoints.platform import create_platform_router
from backend.app.api.v1.endpoints.providers import create_providers_router
from backend.app.api.v1.endpoints.reports import create_reports_router
from backend.app.api.v1.endpoints.sessions import create_sessions_router
from backend.app.api.v1.endpoints.wallets import create_wallets_router
from backend.app.api.v1.endpoints.treasury import create_treasury_router
from backend.app.api.v1.endpoints.stablefx import create_stablefx_router
from backend.app.api.v1.endpoints.swap import create_swap_router
from backend.app.api.v1.endpoints.onramp import create_onramp_router
from backend.app.api.v1.endpoints.incidents import create_incidents_router


from backend.app.schemas import InvoiceRequest, PaymentVerifyRequest

# ---------------------------------------------------------------------------
# Configure Logger
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("QMA-API")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
OPENAPI_TAGS = [
    {
        "name": "System",
        "description": "Health checks and stable runtime capabilities exposed to API consumers.",
    },
    {
        "name": "Provider discovery",
        "description": "Discover provider identity, supported report types, pricing metadata, and provider statistics.",
    },
    {
        "name": "Market data",
        "description": "Live market anomalies and ranked candidates used by buyers and agents.",
    },
    {
        "name": "Agent decisioning",
        "description": "Turn a buyer policy into one validated, provider-bound purchase decision.",
    },
    {
        "name": "Agent sessions",
        "description": "Create and control wallet-owned autonomous sessions. Owner operations require a wallet token; worker operations require the internal worker secret.",
    },
    {
        "name": "Payments & settlement",
        "description": "Quote, create, inspect, verify, and settle QMA invoices through Circle Gateway x402.",
    },
    {
        "name": "Reports",
        "description": "Retrieve paid provider previews and full reports after entitlement verification.",
    },
    {
        "name": "Wallet & entitlements",
        "description": "Read wallet history, private sessions, entitlements, and wallet-bound report snapshots.",
    },
    {
        "name": "Traction & analytics",
        "description": "Read public product traction, payment activity, payer breakdowns, and platform summaries.",
    },
    {
        "name": "Creator operations",
        "description": "Apply as a provider, inspect owned applications, and claim eligible creator earnings.",
    },
    {
        "name": "Admin / operations",
        "description": "Administrative provider controls and review operations. Requires the configured admin token where indicated.",
    },
    {
        "name": "Report chat",
        "description": "Ask questions about a report after presenting a valid paid invoice.",
    },
    {
        "name": "Legacy compatibility",
        "description": "Deprecated aliases retained for existing clients. New integrations should use provider-specific report routes.",
    },
]

# The hosted MCP app is mounted at the bottom of this module; its streamable
# session manager must run inside the app lifespan (mounts don't propagate
# lifespan events to sub-apps). The holder is filled before uvicorn serves.
_mcp_session_manager_holder: dict = {}


async def _qma_lifespan(app):
    from backend.app.core.config import enforce_single_instance_topology_guard

    enforce_single_instance_topology_guard()
    manager = _mcp_session_manager_holder.get("manager")
    reconcile_task = None
    treasury_decide_task = None
    if ARC_GATEWAY_INTERNAL_SECRET:
        reconcile_task = asyncio.create_task(_arc_settlement_reconcile_loop())
    decide_interval = int(app_setting("treasury", "decideIntervalSeconds"))
    if decide_interval > 0:
        treasury_decide_task = asyncio.create_task(_treasury_decide_loop())
    try:
        from backend.app.services.earn_kit import start_earn_snapshot_sampler
        start_earn_snapshot_sampler()
    except Exception:
        pass
    try:
        from backend.app.services.swap_router import start_swap_spread_sampler
        start_swap_spread_sampler()
    except Exception:
        pass
    try:
        if manager is not None:
            async with manager.run():
                yield
        else:
            yield
    finally:
        if reconcile_task is not None:
            reconcile_task.cancel()
            with suppress(asyncio.CancelledError):
                await reconcile_task
        if treasury_decide_task is not None:
            treasury_decide_task.cancel()
            with suppress(asyncio.CancelledError):
                await treasury_decide_task


app = FastAPI(
    lifespan=_qma_lifespan,
    title="QMA Intelligence & Payments API",
    description=(
        "# QMA Intelligence & Payments API\n\n"
        "QMA is a provider marketplace for quantitative market intelligence. "
        "Clients discover live signals, select a provider-bound report, create a "
        "query-bound invoice, verify Circle Gateway x402 settlement, and retrieve "
        "the resulting preview or full report.\n\n"
        "## Recommended buyer flow\n"
        "1. Discover providers with `GET /api/v1/providers` or live candidates with `GET /api/v1/agent/recommendations`.\n"
        "2. Optional: call `POST /api/v1/payment/quote` for a provider-bound price.\n"
        "3. Create an invoice with `POST /api/v1/payment/invoice`.\n"
        "4. Pay the returned Circle Gateway requirement, then verify with `POST /api/v1/payment/verify`.\n"
        "5. Poll `GET /api/v1/payment/invoices/{invoice_id}/status` when settlement is still processing.\n"
        "6. Retrieve the paid provider report from the provider-specific Reports route.\n\n"
        "## Agent flow\n"
        "Use `POST /api/v1/agent/decision` to turn a bounded budget and provider/tier policy into a validated purchase decision. "
        "The payment executor remains responsible for signing and submitting payment; this API does not custody browser wallet keys.\n\n"
        "## Access levels\n"
        "- **Public:** no credential is required. Optional-auth operations return additional private data only after verification.\n"
        "- **Protected:** requires a paid-access token, wallet-owner token, invoice secret, admin token, signed payload, or one of the documented alternatives.\n"
        "- **Internal worker:** requires `x-qma-internal-secret`; never expose this secret to browsers or third-party clients.\n"
        "- Gateway-only `/api/internal/*` routes are intentionally excluded from this OpenAPI document.\n\n"
        "Use `/openapi/public.json`, `/openapi/agent.json`, `/openapi/wallet.json`, `/openapi/admin.json`, "
        "or `/openapi/private.json` for audience-specific contracts. `/openapi.json` is the complete supported external contract.\n\n"
        "All monetary values are denominated in USDC. New invoices use one treasury-bound x402 settlement. "
        "Report access is granted only after Circle settlement verification and a finalized VALID verdict for the exact GenLayer-bound report hash."
    ),
    version="1.0.0",
    servers=[
        {"url": "http://127.0.0.1:8000", "description": "Local development API"},
        {"url": PUBLIC_API_URL, "description": "Production API"},
    ],
    openapi_tags=OPENAPI_TAGS,
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
)


_HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    402: "payment_required",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    429: "rate_limited",
    500: "internal_server_error",
    502: "bad_gateway",
    503: "service_unavailable",
}


def _error_code_for(status_code: int, detail) -> str:
    if isinstance(detail, dict) and isinstance(detail.get("error"), str) and detail["error"]:
        return detail["error"]
    return _HTTP_ERROR_CODES.get(status_code, "http_error")


def _error_message_for(detail) -> str:
    if isinstance(detail, dict):
        if isinstance(detail.get("message"), str) and detail["message"]:
            return detail["message"]
        if isinstance(detail.get("detail"), str) and detail["detail"]:
            return detail["detail"]
    if isinstance(detail, str) and detail:
        return detail
    return "The request could not be completed."


@app.exception_handler(HTTPException)
async def qma_http_exception_handler(request: Request, exc: HTTPException):
    """Return a stable error envelope while preserving the legacy detail field."""
    detail = exc.detail
    headers = dict(exc.headers or {})
    if exc.status_code == 429 and "retry-after" not in {k.lower() for k in headers}:
        headers["Retry-After"] = str(RATE_LIMIT_WINDOW_SECONDS)

    content = {
        "error": _error_code_for(exc.status_code, detail),
        "message": _error_message_for(detail),
        "status_code": exc.status_code,
        "detail": jsonable_encoder(detail),
    }

    if exc.status_code == 402:
        challenge_body, challenge_headers = build_402_challenge_payload(
            url=str(request.url.path),
            amount_decimal="0.005000",
            description="QMA Quantitative Intelligence Report",
        )
        for k, v in challenge_headers.items():
            headers.setdefault(k, v)
        content["price"] = challenge_body["price"]
        content["x402Version"] = challenge_body["x402Version"]
        content["protocols"] = challenge_body.get("protocols", [])
        content["rails"] = challenge_body.get("rails", ["x402", "mpp"])
        content["dualRail"] = challenge_body.get("dualRail", True)
        content["multiChain"] = challenge_body.get("multiChain", True)
        content["auth"] = challenge_body.get("auth", {})
        content["proofOfHuman"] = challenge_body.get("proofOfHuman", {})
        content["schema"] = challenge_body.get("schema", {})
        content["bazaarSchema"] = challenge_body.get("bazaarSchema", {})
        content["accepts"] = challenge_body["accepts"]
        content["extensions"] = challenge_body.get("extensions", {})

    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=headers if headers else None,
    )



from fastapi.exceptions import RequestValidationError
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Wrap FastAPI 422 validation errors in the standard QMA error envelope.
    For paid endpoints called without credentials/payment, return standard 402 challenge."""
    path = request.url.path
    is_paid_path = (
        path == "/api/v1/chat"
        or path == "/api/v1/preview"
        or path == "/api/v1/analyze"
        or path == "/api/v1/agent/jobs"
        or path.startswith("/api/v1/agent/jobs/")
        or (path.startswith("/api/v1/providers/") and (path.endswith("/preview") or path.endswith("/full-report")))
    )
    has_credentials = (
        request.headers.get("x-qma-access-token")
        or request.headers.get("payment-signature")
        or request.query_params.get("invoice_id")
    )
    if is_paid_path and not has_credentials:
        from backend.app.core.x402_spec import build_402_challenge_payload
        amount_dec = "0.005000" if ("full-report" in path or "chat" in path or "analyze" in path or "agent/jobs" in path) else "0.002000"
        challenge_body, challenge_headers = build_402_challenge_payload(
            url=path,
            amount_decimal=amount_dec,
            description=f"QMA Paid Service ({path})",
        )
        return JSONResponse(
            status_code=402,
            content=challenge_body,
            headers=challenge_headers,
        )

    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": "The request contains invalid parameters or body.",
            "status_code": 422,
            "detail": jsonable_encoder(exc.errors()),
        },
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Ensure unhandled 500 errors also return the standard QMA error envelope."""
    logger.exception("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "The server could not complete the request.",
            "status_code": 500,
            "detail": "An unexpected error occurred.",
        },
    )


from backend.app.core.openapi import (
    AUDIENCE_TAGS,
    DOCUMENTATION_AUDIENCES,
    SIGNED_PAYLOAD_OPERATIONS,
    _operation_access,
    _operation_audiences,
)


@app.get("/openapi/{audience}.json", include_in_schema=False)
async def get_audience_openapi(audience: str):
    import copy
    from fastapi import HTTPException
    
    if audience not in DOCUMENTATION_AUDIENCES:
        raise HTTPException(status_code=404, detail="Audience not found")

    schema = copy.deepcopy(app.openapi())
    
    paths_to_keep = {}
    for path, path_item in schema.get("paths", {}).items():
        new_path_item = {}
        for method, operation in path_item.items():
            if method.lower() in ["get", "post", "put", "delete", "patch", "options", "head", "trace"]:
                if audience in operation.get("x-qma-audiences", []):
                    new_path_item[method] = operation
            else:
                new_path_item[method] = operation
        if new_path_item:
            paths_to_keep[path] = new_path_item
            
    schema["paths"] = paths_to_keep
    
    if "tags" in schema:
        used_tags = {
            tag
            for path_item in paths_to_keep.values()
            for operation in path_item.values()
            if isinstance(operation, dict)
            for tag in operation.get("tags", [])
        }
        schema["tags"] = [tag for tag in schema["tags"] if tag["name"] in used_tags]

    schema["info"]["title"] = f"QMA {audience.title()} API"
        
    return schema

@app.get("/scalar", include_in_schema=False)
async def scalar_html():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
    )

@app.get("/docs/{audience}", include_in_schema=False)
async def scalar_audience_html(audience: str):
    from fastapi import HTTPException
    if audience not in DOCUMENTATION_AUDIENCES:
        raise HTTPException(status_code=404, detail="Audience not found")
    return get_scalar_api_reference(
        openapi_url=f"/openapi/{audience}.json",
        title=f"QMA {audience.title()} API",
    )


_default_openapi = app.openapi


def qma_openapi():
    """Add optional-auth semantics, OpenAPI 3.1.0 metadata, and x402 payment specifications."""
    from backend.app.core.openapi import generate_qma_openapi
    return generate_qma_openapi(app, _default_openapi)


app.openapi = qma_openapi

cors_origins = settings.cors_allowed_origins
allow_credentials = "*" not in cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.app.core.emergency import emergency_stop_middleware
app.middleware("http")(emergency_stop_middleware)

app.mount("/public", StaticFiles(directory=str(settings.public_dir)), name="public")

# ---------------------------------------------------------------------------
# Initialize core services
# ---------------------------------------------------------------------------
engine = QMAEngine()

storage_backend = create_storage_backend(
    ledger_path=str(settings.payment_ledger_path),
    reports_path=str(settings.paid_reports_path),
    invoices_path=str(settings.invoices_path),
    creators_path=str(settings.creator_applications_path),
    provider_controls_path=str(settings.provider_controls_path),
)
state.storage_backend = storage_backend
invoices_db = state.invoices_db
payment_events = state.payment_events
paid_reports = state.paid_reports

# Fail-closed guard: production must never run on uncoordinated local JSON files
_is_prod_env = (
    os.getenv("ENVIRONMENT", "").lower() == "production"
    or os.getenv("RENDER", "").lower() == "true"
    or os.getenv("NODE_ENV", "").lower() == "production"
)
if _is_prod_env and storage_backend.__class__.__name__ not in ("PostgresStorage", "SupabaseStorage"):
    raise RuntimeError(
        "FATAL CONFIGURATION ERROR: Production environment detected (ENVIRONMENT=production or RENDER=true). "
        "Production deployments MUST configure a valid DATABASE_URL/SUPABASE_URL and use PostgresStorage or SupabaseStorage. "
        "Fallback to local JsonStorage is strictly forbidden in production."
    )

from backend.app.core.provider_registry import ProviderRegistryV2
from backend.app.services.plugins.funding_provider import FundingProviderV2
from backend.app.services.plugins.oi_provider import OpenInterestMemoryProviderV2
from backend.app.services.providers_meta import provider_metadata

provider_registry = ProviderRegistryV2()
_provider_owner_wallets = app_setting("providers", "ownerWallets")
provider_registry.register(FundingProviderV2(owner_wallet=str(_provider_owner_wallets["funding"])))
provider_registry.register(OpenInterestMemoryProviderV2(owner_wallet=str(_provider_owner_wallets["openInterest"])))
CREATOR_CLAIMS_PATH = str(settings.creator_claims_path)


# ---------------------------------------------------------------------------
# Bound persistence functions (resolve dynamically over active storage_backend)
# ---------------------------------------------------------------------------
def _current_storage():
    from backend.app import main as _main
    mod_store = getattr(_main, "storage_backend", None)
    if mod_store is not None:
        return mod_store
    return getattr(state, "storage_backend", storage_backend)

def _load_payment_ledger():
    return repo.load_payment_ledger(_current_storage())

def _load_payment_events_for_wallet(address):
    return repo.load_payment_events_for_wallet(_current_storage(), address, normalize_address)

def _load_payment_event_summaries(limit=5000):
    return repo.load_payment_event_summaries(_current_storage(), limit=limit)

def _save_payment_ledger(events):
    repo.save_payment_ledger(_current_storage(), events)

def _save_single_payment_event(event):
    repo.save_single_payment_event(_current_storage(), event)

def _load_paid_reports():
    return repo.load_paid_reports(_current_storage())

def _load_paid_reports_for_wallet(address, *, symbol=None, provider_id=None):
    return repo.load_paid_reports_for_wallet(_current_storage(), address, normalize_address, symbol=symbol, provider_id=provider_id)

def _load_wallet_entitlements(address):
    return paid_kit.list_wallet_entitlements(_load_paid_reports_for_wallet(address), address)

def _load_paid_report_summaries_for_wallet(address, *, symbol=None, provider_id=None):
    return repo.load_paid_report_summaries_for_wallet(_current_storage(), address, normalize_address, symbol=symbol, provider_id=provider_id)

def _load_paid_report_summaries(limit=5000):
    return repo.load_paid_report_summaries(_current_storage(), limit=limit)

def _load_paid_report_by_id(address, entitlement_id):
    return repo.load_paid_report_by_id(_current_storage(), address, entitlement_id, normalize_address)

def _save_paid_reports(reports):
    try:
        repo.save_paid_reports(_current_storage(), reports)
    except Exception as exc:
        import fastapi
        raise fastapi.HTTPException(status_code=503, detail={"error": "persistence_unavailable", "message": "Failed to persist report entitlement"}) from exc

def _save_single_paid_report(entitlement_id, record):
    try:
        repo.save_single_paid_report(_current_storage(), entitlement_id, record)
    except Exception as exc:
        import fastapi
        raise fastapi.HTTPException(status_code=503, detail={"error": "persistence_unavailable", "message": "Failed to persist report entitlement"}) from exc

def _load_invoices():
    return repo.load_invoices(_current_storage())

def _count_invoices() -> int:
    try:
        return int(_current_storage().count_invoices())
    except Exception:
        return len(state.invoices_db)

def _load_paid_invoices_for_wallet(address):
    return repo.load_paid_invoices_for_wallet(_current_storage(), address, normalize_address)

def _save_invoice(invoice):
    inv_id = invoice.get("invoice_id") if isinstance(invoice, dict) else None
    try:
        repo.save_invoice(_current_storage(), invoice)
        if inv_id:
            state.invoices_db[inv_id] = invoice
    except Exception as exc:
        if inv_id:
            state.invoices_db.pop(inv_id, None)
        raise HTTPException(status_code=503, detail="Invoice persistence failed; retry the same invoice.") from exc

save_invoice = _save_invoice
load_invoices = _load_invoices
save_payment_ledger = _save_payment_ledger
load_payment_ledger = _load_payment_ledger
save_paid_reports = _save_paid_reports
load_paid_reports = _load_paid_reports

def _load_creator_applications():
    return repo.load_creator_applications(storage_backend)

def _save_creator_application(application):
    return repo.save_creator_application(storage_backend, application)

def _load_provider_controls():
    return repo.load_provider_controls(storage_backend)

def _save_provider_control(provider_id, control):
    return repo.save_provider_control(storage_backend, provider_id, control)

def _load_creator_claims():
    return repo.load_creator_claims(storage_backend, CREATOR_CLAIMS_PATH)

def _save_creator_claim_record(record):
    return repo.save_creator_claim_record(storage_backend, CREATOR_CLAIMS_PATH, record)


# ---------------------------------------------------------------------------
# Initialize state
# ---------------------------------------------------------------------------
state.init_state(
    load_payment_ledger=_load_payment_ledger,
    load_paid_reports=_load_paid_reports,
    load_invoices=_load_invoices,
    load_creator_applications=_load_creator_applications,
    load_provider_controls=_load_provider_controls,
    load_creator_claims=_load_creator_claims,
)


def reload_persistent_state(include_reports=True, include_invoices=False):
    state.reload_persistent_state(
        load_payment_ledger=_load_payment_ledger,
        load_paid_reports=_load_paid_reports,
        load_invoices=_load_invoices,
        load_creator_applications=_load_creator_applications,
        load_provider_controls=_load_provider_controls,
        load_creator_claims=_load_creator_claims,
        include_reports=include_reports,
        include_invoices=include_invoices,
    )


# ---------------------------------------------------------------------------
# Rate limit middleware
# ---------------------------------------------------------------------------
_RATE_LIMIT_LOCK = threading.Lock()


@app.middleware("http")
async def qma_rate_limit_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    # Client IP and loopback detection
    client_ip = client_ip_from_request(request)
    is_loopback = client_ip in ("127.0.0.1", "::1", "localhost", "testclient")
    is_health = request.url.path in ("/api/v1/health", "/health", "/healthz", "/metrics")

    # 1. Anti-Bot / Anti-Scraper Gate: block headless automated browsers from external networks
    if not is_loopback:
        ua = request.headers.get("user-agent", "").lower()
        sec_ch_ua = request.headers.get("sec-ch-ua", "").lower()
        is_headless_bot = (
            any(sig in ua for sig in ("headlesschrome", "phantomjs", "selenium", "puppeteer"))
            or ("headlesschrome" in sec_ch_ua)
        )
        if is_headless_bot:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "bot_blocked",
                    "message": "Automated headless scrapers are prohibited.",
                    "status_code": 403,
                    "detail": "bot_blocked",
                },
            )

    # 2. Origin Shielding & Tunnel Bypass Protection
    has_vercel_proxy = bool(request.headers.get("x-vercel-id"))
    shield_hdr = request.headers.get("x-qma-origin-secret", "").strip()
    has_origin_secret = bool(ORIGIN_SHIELD_SECRET and shield_hdr == ORIGIN_SHIELD_SECRET)
    internal_sec = request.headers.get("x-qma-internal-secret")
    has_internal_sec = bool(internal_sec and ARC_GATEWAY_INTERNAL_SECRET and internal_sec == ARC_GATEWAY_INTERNAL_SECRET)
    admin_tok = request.headers.get("x-qma-admin-token")
    has_admin_tok = bool(admin_tok and ADMIN_TOKEN and admin_tok == ADMIN_TOKEN)
    has_api_auth = bool(
        request.headers.get("authorization")
        or request.headers.get("payment-signature")
        or request.headers.get("x-qma-access-token")
        or request.headers.get("x-qma-wallet-token")
        or request.headers.get("x-qma-api-key")
    )
    is_authenticated = has_origin_secret or has_internal_sec or has_admin_tok or has_api_auth
    is_tunnel_authorized = is_authenticated or has_vercel_proxy

    # Detect public development tunnels (e.g. ngrok, cloudflare tunnel, localtunnel)
    host_hdr = request.headers.get("host", "").lower()
    is_tunnel = any(t in host_hdr for t in ("ngrok-free.dev", "ngrok.io", "ngrok-free.app", "trycloudflare.com", "loca.lt"))

    if is_tunnel and not is_loopback and not is_health and not is_tunnel_authorized:
        return JSONResponse(
            status_code=403,
            content={
                "error": "direct_tunnel_access_forbidden",
                "message": "Direct access to development tunnel is forbidden. Please route requests via https://qma-three.vercel.app or authenticate.",
                "status_code": 403,
                "detail": "direct_tunnel_access_forbidden",
            },
        )

    if ORIGIN_SHIELD_SECRET and not is_loopback and not is_health and not is_authenticated:
        return JSONResponse(
            status_code=403,
            content={
                "error": "origin_shield_blocked",
                "message": "Direct access to origin tunnel forbidden. Requests must pass through authorized proxy.",
                "status_code": 403,
                "detail": "origin_shield_blocked",
            },
        )

    if not RATE_LIMIT_ENABLED:
        return await call_next(request)

    # Internal workers and admin callers bypass public client rate limits
    if has_internal_sec or has_admin_tok:
        return await call_next(request)
    if request.headers.get("x-benchmark-test") == "1" and is_loopback:
        return await call_next(request)

    scope, limit = rate_limit_for_path(request.url.path)
    if limit <= 0:
        return await call_next(request)
    now = time.time()
    key = f"{scope}:{client_ip}"
    with _RATE_LIMIT_LOCK:
        bucket = state.rate_limit_buckets[key]
        while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0])))
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limited",
                    "message": "Request rate limit exceeded.",
                    "status_code": 429,
                    "detail": "rate_limited",
                    "scope": scope,
                    "limit": limit,
                    "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)

        # Thread-safe periodic cleanup with bounded memory cap to prevent IP explosion
        if len(state.rate_limit_buckets) > 1000:
            stale_keys = [k for k, b in list(state.rate_limit_buckets.items()) if not b or (now - b[-1] > RATE_LIMIT_WINDOW_SECONDS)]
            for k in stale_keys:
                del state.rate_limit_buckets[k]
            if len(state.rate_limit_buckets) > 2000:
                overflow_count = len(state.rate_limit_buckets) - 2000
                for k in list(state.rate_limit_buckets.keys())[:overflow_count]:
                    del state.rate_limit_buckets[k]

    return await call_next(request)



# ---------------------------------------------------------------------------
# Paid invoice events (uses both repos and services)
# ---------------------------------------------------------------------------
def load_paid_invoice_events():
    try:
        if hasattr(storage_backend, "load_paid_invoice_events"):
            return storage_backend.load_paid_invoice_events()
    except Exception as exc:
        logger.warning(f"Could not load paid invoice events: {exc}")
    events = []
    for invoice in _load_invoices().values():
        if not isinstance(invoice, dict) or invoice.get("status") != "paid":
            continue
        if invoice_split_mode(invoice) == "x402_direct_split":
            for leg in invoice_required_split_legs(invoice):
                if leg.get("status") == "paid" and leg.get("settlement_id"):
                    events.append(split_leg_event(invoice, leg))
        else:
            events.append(paid_invoice_event(invoice))
    return events


# ---------------------------------------------------------------------------
# Split leg batch tx refresh (needs circle_client + state)
# ---------------------------------------------------------------------------
def refresh_split_leg_batch_txs(invoice):
    if invoice_split_mode(invoice) != "x402_direct_split":
        return False
    changed = False
    for leg in split_paid_legs(invoice):
        temp_event = {
            "settlement_id": leg.get("settlement_id"),
            "gateway_status": leg.get("gateway_status"),
            "transaction_hash": leg.get("transaction_hash"),
            "explorer_url": leg.get("explorer_url"),
        }
        if refresh_event_batch_tx(temp_event):
            leg["gateway_status"] = temp_event.get("gateway_status")
            leg["transaction_hash"] = temp_event.get("transaction_hash")
            leg["explorer_url"] = temp_event.get("explorer_url")
            changed = True
    if changed:
        invoice["gateway_status"] = aggregate_split_gateway_status(invoice)
    return changed


# ---------------------------------------------------------------------------
# Authorized withdraw depositor
# ---------------------------------------------------------------------------
def authorized_gateway_withdraw_depositor(address):
    depositor = normalize_address(address)
    if same_address(depositor, PAYMENT_WALLET_ADDRESS) or same_address(depositor, PLATFORM_TREASURY_ADDRESS):
        return {"address": depositor, "role": "platform_treasury", "provider_ids": []}
    pids = provider_ids_by_revenue_wallet(provider_registry, depositor)
    if pids:
        return {"address": depositor, "role": "provider_revenue_wallet", "provider_ids": pids}
    from fastapi import HTTPException
    raise HTTPException(status_code=403, detail="This wallet is not authorized to withdraw QMA Gateway balance.")


# ---------------------------------------------------------------------------
# Allocate creator claim
# ---------------------------------------------------------------------------
def allocate_creator_claim(provider_ids, amount_usdc):
    remaining = round(float(amount_usdc), 6)
    allocations = {}
    stats_rows = []
    for pid in provider_ids:
        stats = build_provider_stats(
            provider_registry, pid, hydrate_payment_schema,
            reload_persistent_state,
        )
        available = round(float(stats.get("creator_claimable_usdc") or 0), 6)
        stats_rows.append(stats)
        if remaining <= 0:
            allocations[pid] = 0.0
            continue
        allocation = min(available, remaining)
        allocations[pid] = round(allocation, 6)
        remaining = round(remaining - allocation, 6)
    if remaining > 0.000001:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Claim amount exceeds available creator earnings.")
    return allocations, stats_rows


# ---------------------------------------------------------------------------
# High-level business functions (create_invoice, verify_payment, etc.)
# ---------------------------------------------------------------------------
# Modularized into dedicated domain services:
# - backend.app.services.payment_service
# - backend.app.services.report_generator_service
# - backend.app.services.genlayer_reconcile_service
# ---------------------------------------------------------------------------
from backend.app.services.report_generator_service import (
    _PUBLIC_VERIFICATION_CLAIMS,
    _build_epoch_snapshot,
    _canonical_report_json,
    build_preview_report,
    build_provider_report,
    invoice_report_meta,
)
from backend.app.services.genlayer_reconcile_service import (
    _EVIDENCE_CHECK_CACHE,
    _EVIDENCE_CHECK_TTL_SECONDS,
    _GENLAYER_PREWARM_EXECUTOR,
    _MEXC_ANCHORED_PROVIDERS,
    _arc_settlement_reconcile_loop,
    _ensure_signal_verifiable,
    _gate_enabled,
    _genlayer_evidence_url,
    _genlayer_target_exchange,
    _mexc_evidence_has_market_data,
    _report_verification_manifest,
    _signal_verifiability,
    _sync_arc_settlement_to_payment_events,
    _sync_single_payment_event,
    _trigger_genlayer_prewarm_in_background,
    _verify_invoice_report_with_genlayer_locked,
    prewarm_genlayer_sla_for_invoice,
    reconcile_arc_verdict_settlements_once,
    settle_genlayer_verdict_on_arc,
    verify_invoice_report_with_genlayer,
)
from backend.app.services.payment_service import (
    authorize_paid_invoice,
    create_invoice,
    get_payment_invoice_status,
    refresh_split_leg_batch_txs,
    submit_withdraw,
    verify_payment,
    verify_split_payment,
)


async def _treasury_decide_loop() -> None:
    """Periodic autonomous CFO capital allocation and yield evaluation loop."""
    interval = int(app_setting("treasury", "decideIntervalSeconds"))
    if interval <= 0:
        return
    while True:
        try:
            await asyncio.sleep(interval)
            from backend.app.services.usyc_treasury import usyc_treasury_service
            decision_res = await asyncio.to_thread(
                usyc_treasury_service.evaluate_cfo_decision,
                execute_if_authorized=False,
                record_hold=False,
            )
            logger.info(
                "Treasury periodic decide tick evaluated: action=%s amount=%s",
                decision_res.get("decision"),
                decision_res.get("amount_usdc"),
            )
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Treasury periodic decide loop tick failed")


def _process_agent_direct_x402_payment(**_kwargs) -> dict:
    """Unverified client headers never constitute proof of a settled invoice."""
    raise HTTPException(status_code=402, detail="Create an invoice, settle its Gateway requirement, and verify payment before requesting a report.")


def run_paid_provider_report(*, provider_id, query, invoice_id, token, required_tier, request=None):
    provider = get_provider_or_404(provider_registry, provider_id)
    raw_query = model_to_dict(query)
    for key in [
        "provider_id", "tier", "buyer_type", "buyer_wallet_address",
        "synthetic", "agent_label", "run_source", "resource_type",
        "candidate_id", "expected_price_usdc",
    ]:
        raw_query.pop(key, None)

    normalized_query = normalize_query_for_provider(provider, raw_query)

    invoice = authorize_paid_invoice(
        query=normalized_query, invoice_id=invoice_id, token=token,
        required_tier=required_tier, provider_id=getattr(provider, "provider_id", provider_id),
    )
    refresh_invoice_batch_tx(invoice)


    if invoice.get("verification_required"):
        report = invoice.get("verified_report")
        if report is None:
            raise HTTPException(status_code=503, detail="Verified report payload is unavailable; access remains locked.")
        actual_hash = hashlib.sha256(_canonical_report_json(report).encode("utf-8")).hexdigest()
        if actual_hash != invoice.get("verification_report_hash"):
            raise HTTPException(status_code=409, detail="Verified report payload hash mismatch.")
        return report

    report = build_provider_report(
        provider=provider,
        normalized_query=normalized_query,
        invoice_id=invoice_id,
        invoice=invoice,
        required_tier=required_tier,
    )


    invoice["used_at"] = time.time()
    _save_invoice(invoice)
    paid_kit.record_entitlement(state.paid_reports, invoice=invoice, report=jsonable_encoder(report))
    _save_paid_reports(state.paid_reports)
    return report


# ---------------------------------------------------------------------------
# Bound wrappers for router deps
# ---------------------------------------------------------------------------
def _maybe_refresh(max_events=8):
    maybe_refresh_unresolved_payment_events(_save_payment_ledger, _save_invoice, max_events=max_events)

def _load_platform_payment_events(limit=5000):
    return load_platform_payment_events(
        _load_payment_event_summaries,
        load_paid_invoice_events,
        _load_paid_report_summaries,
        limit=limit,
    )

def _summarize_payment_events(events):
    return summarize_payment_events(events, lambda pid, fo: provider_split_metadata(provider_registry, pid, fo))

def _get_provider_or_404(pid, *, allow_disabled=False):
    return get_provider_or_404(provider_registry, pid, allow_disabled=allow_disabled)

def _provider_ids_owned_by(address):
    return provider_ids_owned_by(provider_registry, address)

def _build_provider_stats(pid):
    return build_provider_stats(provider_registry, pid, hydrate_payment_schema, reload_persistent_state)

def _provider_metadata(provider):
    return provider_metadata(provider)

def _settlement_id_already_claimed(sid, *, exclude_invoice_id=None):
    return settlement_id_already_claimed(sid, exclude_invoice_id=exclude_invoice_id, load_invoices_fn=_load_invoices, invoices_db=state.invoices_db, storage_backend=storage_backend)

def _get_agent_recommendations(limit=25):
    return build_agent_recommendations(SimpleNamespace(
        cache_ttl_seconds=CACHE_TTL_SECONDS,
        live_anomalies_cache=state.live_anomalies_cache,
        live_scan_lock=state.live_scan_lock,
        logger=logger,
        normalize_query_for_provider=normalize_query_for_provider,
        pricing_config=paid_kit.pricing_config,
        provider_control=provider_control,
        provider_registry=provider_registry,
        scan_mexc_live=None,
    ), limit)


# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------
app.include_router(create_health_router(SimpleNamespace(
    admin_wallet_address=ADMIN_WALLET_ADDRESS,
    arc_gateway_base_url=ARC_GATEWAY_BASE_URL,
    arc_gateway_internal_secret=ARC_GATEWAY_INTERNAL_SECRET,
    arc_gateway_minter=ARC_GATEWAY_MINTER,
    arc_gateway_wallet=ARC_GATEWAY_WALLET,
    arc_testnet_usdc=ARC_TESTNET_USDC,
    creator_claim_min_usdc=CREATOR_CLAIM_MIN_USDC,
    default_settlement_mode=DEFAULT_SETTLEMENT_MODE,
    engine=engine,
    fetch_creator_claim_status_cached=fetch_creator_claim_status_cached,
    fetch_gateway_balance_cached=fetch_gateway_balance_cached,
    fetch_gateway_info_cached=fetch_gateway_info_cached,
    gateway_default_approve_usdc=GATEWAY_DEFAULT_APPROVE_USDC,
    gateway_default_deposit_usdc=GATEWAY_DEFAULT_DEPOSIT_USDC,
    normalize_address=normalize_address,
    payment_network=PAYMENT_NETWORK,
    payment_network_name=PAYMENT_NETWORK_NAME,
    platform_treasury_address=PLATFORM_TREASURY_ADDRESS,
    pricing_config=paid_kit.pricing_config,
    provider_control=provider_control,
    provider_metadata=_provider_metadata,
    provider_registry=provider_registry,
    require_completed_settlement=REQUIRE_COMPLETED_SETTLEMENT,
    root_dir=settings.root_dir,
    settlement_currency=SETTLEMENT_CURRENCY,
    settlement_rail=SETTLEMENT_RAIL,
    split_invoice_ttl_seconds=SPLIT_INVOICE_TTL_SECONDS,
    split_leg_url_secret=SPLIT_LEG_URL_SECRET,
    storage_backend=storage_backend,
    supported_settlement_assets=SUPPORTED_SETTLEMENT_ASSETS,
    withdraw_min_usdc=WITHDRAW_MIN_USDC,
    withdraw_mode=WITHDRAW_MODE,
    withdraw_relay_daily_limit=WITHDRAW_RELAY_DAILY_LIMIT,
    withdraw_relayer_address=WITHDRAW_RELAYER_ADDRESS,
)))

app.include_router(create_providers_router(SimpleNamespace(
    admin_token=ADMIN_TOKEN,
    admin_wallet_address=ADMIN_WALLET_ADDRESS,
    allocate_creator_claim=allocate_creator_claim,
    arc_gateway_base_url=ARC_GATEWAY_BASE_URL,
    arc_gateway_internal_secret=ARC_GATEWAY_INTERNAL_SECRET,
    build_creator_claim_message=build_creator_claim_message,
    build_provider_stats=_build_provider_stats,
    canonical_provider_ids=canonical_provider_ids,
    creator_applications=state.creator_applications,
    creator_claim_intent_ttl_seconds=CREATOR_CLAIM_INTENT_TTL_SECONDS,
    creator_claim_lock=state.creator_claim_lock,
    creator_claim_min_usdc=CREATOR_CLAIM_MIN_USDC,
    get_creator_claims_db=lambda: state.creator_claims_db,
    get_provider_or_404=_get_provider_or_404,
    has_admin_token=has_admin_token,
    load_creator_applications=_load_creator_applications,
    model_to_dict=model_to_dict,
    normalize_address=normalize_address,
    payment_wallet_address=PAYMENT_WALLET_ADDRESS,
    provider_ids_owned_by=_provider_ids_owned_by,
    provider_metadata=_provider_metadata,
    provider_registry=provider_registry,
    provider_runtime_controls=state.provider_runtime_controls,
    recover_creator_claim_signer=recover_creator_claim_signer,
    reload_persistent_state=reload_persistent_state,
    require_admin_token=require_admin_token,
    same_address=same_address,
    save_creator_application=_save_creator_application,
    save_creator_claim_record=_save_creator_claim_record,
    save_provider_control=_save_provider_control,
)))

app.include_router(create_platform_router(SimpleNamespace(
    build_traction_snapshot=build_traction_snapshot,
    compact_payment_event=compact_payment_event,
    fetch_gateway_balance_cached=fetch_gateway_balance_cached,
    invoices_db=state.invoices_db,
    count_invoices=_count_invoices,
    load_platform_payment_events=_load_platform_payment_events,
    maybe_refresh_unresolved_payment_events=_maybe_refresh,
    paginate_items=paginate_items,
    payment_wallet_address=PAYMENT_WALLET_ADDRESS,
    summarize_payment_events=_summarize_payment_events,
    storage_backend=storage_backend,
)))

app.include_router(create_market_router(SimpleNamespace(
    cache_ttl_seconds=CACHE_TTL_SECONDS,
    live_anomalies_cache=state.live_anomalies_cache,
    live_scan_lock=state.live_scan_lock,
    logger=logger,
    normalize_query_for_provider=normalize_query_for_provider,
    pricing_config=paid_kit.pricing_config,
    provider_control=provider_control,
    provider_registry=provider_registry,
    engine=engine,
)))


app.include_router(create_agent_router(SimpleNamespace(
    get_agent_recommendations=_get_agent_recommendations,
    load_wallet_entitlements=_load_wallet_entitlements,
    provider_registry=provider_registry,
    create_invoice=create_invoice,
    get_invoice=lambda invoice_id: get_invoice_or_402(state.invoices_db, invoice_id, load_invoices_fn=_load_invoices),
    run_paid_provider_report=run_paid_provider_report,
    load_spending_events=lambda address: storage_backend.load_wallet_spending_events(address),
)))

app.include_router(create_chat_router(SimpleNamespace(
    get_invoices_db=lambda: state.invoices_db,
    get_paid_reports=lambda: state.paid_reports,
    reload_persistent_state=reload_persistent_state,
)))

app.include_router(create_internal_router(SimpleNamespace(
    apply_arc_settlement_checkpoint=apply_arc_settlement_checkpoint,
    arc_settlement_instruction=arc_settlement_instruction,
    arc_gateway_internal_secret=ARC_GATEWAY_INTERNAL_SECRET,
    cross_process_lock=state.cross_process_lock,
    invoice_split_mode=invoice_split_mode,
    invoices_db=state.invoices_db,
    normalize_address=normalize_address,
    public_arc_settlement=public_arc_settlement,
    raw_usdc_str=raw_usdc_str,
    refresh_split_invoice_status=refresh_split_invoice_status,
    save_invoice=_save_invoice,
    settlement_id_already_claimed=_settlement_id_already_claimed,
    split_leg_by_id=split_leg_by_id,
    split_leg_lock=state.split_leg_lock,
    verify_split_receipt=verify_split_receipt,
)))

app.include_router(create_wallets_router(SimpleNamespace(
    access_token_secret=ACCESS_TOKEN_SECRET,
    attach_report_summaries=attach_report_summaries,
    compact_payment_event=compact_payment_event,
    fetch_gateway_balance=fetch_gateway_balance,
    fetch_gateway_balance_cached=fetch_gateway_balance_cached,
    hydrate_payment_schema=hydrate_payment_schema,
    invoice_required_split_legs=invoice_required_split_legs,
    invoice_split_mode=invoice_split_mode,
    list_wallet_entitlements=paid_kit.list_wallet_entitlements,
    load_paid_invoices_for_wallet=_load_paid_invoices_for_wallet,
    load_paid_report_by_id=_load_paid_report_by_id,
    load_paid_report_summaries_for_wallet=_load_paid_report_summaries_for_wallet,
    load_paid_reports_for_wallet=_load_paid_reports_for_wallet,
    load_payment_events_for_wallet=_load_payment_events_for_wallet,
    maybe_refresh_unresolved_payment_events=_maybe_refresh,
    normalize_address=paid_kit.normalize_address,
    paginate_items=paginate_items,
    payment_event_key=payment_event_key,
    payment_event_tier=payment_event_tier,
    payment_resource_type=PAYMENT_RESOURCE_TYPE,
    payment_wallet_address=PAYMENT_WALLET_ADDRESS,
    public_entitlement_row=public_entitlement_row,
    public_payment_row=public_payment_row,
    sign_access_token=paid_kit.sign_access_token,
    summarize_payment_events=_summarize_payment_events,
    verify_wallet_profile_token=lambda address, token: verify_wallet_profile_token_service(
        address, token, access_token_secret=ACCESS_TOKEN_SECRET,
    ),
    wallet_profile_message=wallet_profile_message,
    wallet_profile_token_payload=wallet_profile_token_payload,
    wallet_profile_token_ttl_seconds=WALLET_PROFILE_TOKEN_TTL_SECONDS,
    issue_wallet_profile_nonce=issue_wallet_profile_nonce,
    consume_wallet_profile_nonce=consume_wallet_profile_nonce,
)))

app.include_router(create_payments_router(SimpleNamespace(
    create_invoice=create_invoice,
    fetch_circle_settlement=fetch_circle_settlement,
    find_arc_batch_tx=find_arc_batch_tx,
    get_provider_or_404=_get_provider_or_404,
    get_payment_invoice_status=get_payment_invoice_status,
    model_to_dict=model_to_dict,
    normalize_query_for_provider=normalize_query_for_provider,
    normalize_tier=paid_kit.normalize_tier,
    pricing_config=paid_kit.pricing_config,
    submit_withdraw=submit_withdraw,
    verify_payment=verify_payment,
)))

app.include_router(create_reports_router(SimpleNamespace(
    logger=logger,
    run_paid_provider_report=run_paid_provider_report,
)))

app.include_router(create_sessions_router(SimpleNamespace(
    internal_secret=ARC_GATEWAY_INTERNAL_SECRET,
    normalize_address=paid_kit.normalize_address,
    storage_backend=storage_backend,
    verify_wallet_profile_token=lambda address, token: verify_wallet_profile_token_service(
        address, token, access_token_secret=ACCESS_TOKEN_SECRET,
    ),
)))

app.include_router(create_oauth_router(SimpleNamespace(
    storage_backend=storage_backend,
    normalize_address=paid_kit.normalize_address,
    verify_wallet_profile_token=lambda address, token: verify_wallet_profile_token_service(
        address, token, access_token_secret=ACCESS_TOKEN_SECRET,
    ),
    mcp_token_ttl_seconds=MCP_TOKEN_TTL_SECONDS,
    mcp_max_budget_usdc=MCP_MAX_BUDGET_USDC,
    mcp_max_price_usdc=MCP_MAX_PRICE_USDC,
    mcp_connect_base_url=MCP_CONNECT_BASE_URL,
    mcp_api_base_url=MCP_API_BASE_URL,
)))

app.include_router(create_treasury_router())
app.include_router(create_stablefx_router())
app.include_router(create_swap_router())
app.include_router(create_onramp_router())
app.include_router(create_incidents_router())



@app.get("/", include_in_schema=False)
def root_index():
    return {
        "status": "ok",
        "service": "qma-api",
        "mcp": "/mcp",
        "docs": "/docs",
        "version": "v1",
    }


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    from fastapi.responses import Response
    return Response(status_code=204)


async def mcp_call_api(method: str, path: str, *, json=None, headers=None):
    """In-process HTTP call into this app for MCP tools (no network hop)."""
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal") as client:
        response = await client.request(method, path, json=json, headers=headers)
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text[:2000]}
        return response.status_code, data


from backend.app.mcp_server.server import create_mcp_http_app

_mcp_asgi_app, _mcp_session_manager = create_mcp_http_app(SimpleNamespace(
    storage_backend=storage_backend,
    access_token_secret=ACCESS_TOKEN_SECRET,
    call_api=mcp_call_api,
    mcp_api_base_url=MCP_API_BASE_URL,
))
_mcp_session_manager_holder["manager"] = _mcp_session_manager
# Mounted at "/" (must stay LAST): its internal route matches POST /mcp
# exactly. A Mount("/mcp") would 307 /mcp → /mcp/ and connector clients
# strip Authorization on redirect, breaking the connector flow.
app.mount("/", _mcp_asgi_app)



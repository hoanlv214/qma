"""QMA Backend — FastAPI application entrypoint.

This is the canonical server module. It creates the FastAPI app, initializes
all state, registers middleware and routers.

Run with:
    uvicorn backend.app.main:app --reload
"""

import os
import time
import logging
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import paid_intelligence_kit as paid_kit
from qma_engine import QMAEngine
from market_data import create_market_data_adapter
from providers import create_default_registry
from storage import create_storage_backend

from backend.app.core.config import (
    settings,
    load_local_env,
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
    # Admin
    ADMIN_TOKEN,
    ADMIN_WALLET_ADDRESS,
    # Rate limiting
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_WINDOW_SECONDS,
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
    build_invoice_split,
    allocate_split_legs_raw,
    settlement_id_already_claimed,
    issue_invoice_access_token,
    invoice_payment_state_response,
    payment_requirement,
    paid_invoice_event,
    get_invoice_or_402,
)
from backend.app.services.providers_meta import (
    provider_settlement_mode,
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
    summarize_payment_events,
    merge_payment_sources,
    load_platform_payment_events,
)
from backend.app.services.agent_recommendations import build_agent_recommendations
from backend.app.repositories import storage as repo

# Route factories
from backend.app.api.v1.endpoints.chat import create_chat_router
from backend.app.api.v1.endpoints.health import create_health_router
from backend.app.api.v1.endpoints.internal import create_internal_router
from backend.app.api.v1.endpoints.agent import create_agent_router
from backend.app.api.v1.endpoints.market import create_market_router
from backend.app.api.v1.endpoints.payments import create_payments_router
from backend.app.api.v1.endpoints.platform import create_platform_router
from backend.app.api.v1.endpoints.providers import create_providers_router
from backend.app.api.v1.endpoints.reports import create_reports_router
from backend.app.api.v1.endpoints.wallets import create_wallets_router

from backend.app.schemas import InvoiceRequest, PaymentVerifyRequest

# ---------------------------------------------------------------------------
# Configure Logger
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("QMA-API")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Quant Memory Agent (QMA) Server",
    description=(
        "Paid intelligence API for Arc/Circle USDC micropayments. "
        "List providers, create query-bound invoices, verify settlement, then call paid preview/full report endpoints."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

provider_registry = create_default_registry(engine=engine, default_owner_wallet=PAYMENT_WALLET_ADDRESS)
market_data_adapter = create_market_data_adapter(os.getenv("QMA_MARKET_DATA_SOURCE", "mexc_futures"))

CREATOR_CLAIMS_PATH = str(settings.creator_claims_path)


# ---------------------------------------------------------------------------
# Bound persistence functions (close over storage_backend)
# ---------------------------------------------------------------------------
def _load_payment_ledger():
    return repo.load_payment_ledger(storage_backend)

def _load_payment_events_for_wallet(address):
    return repo.load_payment_events_for_wallet(storage_backend, address, normalize_address)

def _load_payment_event_summaries(limit=5000):
    return repo.load_payment_event_summaries(storage_backend, limit=limit)

def _save_payment_ledger(events):
    repo.save_payment_ledger(storage_backend, events)

def _load_paid_reports():
    return repo.load_paid_reports(storage_backend)

def _load_paid_reports_for_wallet(address, *, symbol=None, provider_id=None):
    return repo.load_paid_reports_for_wallet(storage_backend, address, normalize_address, symbol=symbol, provider_id=provider_id)

def _load_wallet_entitlements(address):
    return paid_kit.list_wallet_entitlements(_load_paid_reports_for_wallet(address), address)

def _load_paid_report_summaries_for_wallet(address, *, symbol=None, provider_id=None):
    return repo.load_paid_report_summaries_for_wallet(storage_backend, address, normalize_address, symbol=symbol, provider_id=provider_id)

def _load_paid_report_summaries(limit=5000):
    return repo.load_paid_report_summaries(storage_backend, limit=limit)

def _load_paid_report_by_id(address, entitlement_id):
    return repo.load_paid_report_by_id(storage_backend, address, entitlement_id, normalize_address)

def _save_paid_reports(reports):
    repo.save_paid_reports(storage_backend, reports)

def _load_invoices():
    return repo.load_invoices(storage_backend)

def _load_paid_invoices_for_wallet(address):
    return repo.load_paid_invoices_for_wallet(storage_backend, address, normalize_address)

def _save_invoice(invoice):
    repo.save_invoice(storage_backend, invoice)

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
@app.middleware("http")
async def qma_rate_limit_middleware(request: Request, call_next):
    if not RATE_LIMIT_ENABLED or request.method == "OPTIONS":
        return await call_next(request)
    scope, limit = rate_limit_for_path(request.url.path)
    if limit <= 0:
        return await call_next(request)
    now = time.time()
    key = f"{scope}:{client_ip_from_request(request)}"
    bucket = state.rate_limit_buckets[key]
    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= limit:
        retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0])))
        return JSONResponse(
            status_code=429,
            content={
                "detail": "rate_limited",
                "scope": scope,
                "limit": limit,
                "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
                "retry_after_seconds": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Live market scanner
# ---------------------------------------------------------------------------
def scan_mexc_live():
    try:
        data = market_data_adapter.scan_anomalies()
        return data or state.live_anomalies_cache.get("data", [])
    except Exception as e:
        logger.error(f"Failed to scan live market data: {e}")
        return []


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
def create_invoice(req: InvoiceRequest):
    req_data = model_to_dict(req)
    provider_id = req_data.pop("provider_id", "funding_memory")
    buyer_type = req_data.pop("buyer_type", "human")
    tier = paid_kit.normalize_tier(req_data.pop("tier", "full"))
    resource_type = req_data.pop("resource_type", PAYMENT_RESOURCE_TYPE) or PAYMENT_RESOURCE_TYPE
    synthetic = bool(req_data.pop("synthetic", False))
    agent_label = req_data.pop("agent_label", None)
    run_source = req_data.pop("run_source", None)
    provider = get_provider_or_404(provider_registry, provider_id)
    req_data = normalize_query_for_provider(provider, req_data)
    quote = provider.quote_price(req_data, tier)
    invoice, requirement = paid_kit.create_invoice(
        query=req_data,
        tier=tier,
        amount_usdc=quote["amount_usdc"],
        resource_type=resource_type,
        provider_id=provider.provider_id,
        buyer_type=buyer_type,
        owner_wallet=provider.owner_wallet,
        network=PAYMENT_NETWORK,
        network_name=PAYMENT_NETWORK_NAME,
        seller_address=PAYMENT_WALLET_ADDRESS,
        gateway_base_url=ARC_GATEWAY_BASE_URL,
        facilitator_url=ARC_GATEWAY_API,
        explorer_url=ARC_EXPLORER,
        ttl_seconds=INVOICE_TTL_SECONDS,
        settlement_rail=SETTLEMENT_RAIL,
        settlement_currency=SETTLEMENT_CURRENCY,
        settlement_token_address=ARC_TESTNET_USDC,
        settlement_decimals=6,
    )
    hydrate_payment_schema(invoice)
    smode = provider_settlement_mode(provider)
    invoice["settlement"]["mode"] = smode
    invoice["accounting"] = {
        **invoice.get("accounting", {}),
        "settlement_mode": smode,
        "creator_wallet": provider_revenue_wallet(provider),
        "creator_share_bps": int(getattr(provider, "revenue_share_bps", 8000)),
        "platform_share_bps": 10000 - int(getattr(provider, "revenue_share_bps", 8000)),
    }
    invoice["wallet_address"] = PLATFORM_TREASURY_ADDRESS
    invoice["platform_treasury_wallet"] = normalize_address(PLATFORM_TREASURY_ADDRESS)
    invoice["synthetic"] = synthetic
    invoice["agent_label"] = agent_label
    invoice["run_source"] = run_source
    if smode == "x402_direct_split":
        invoice["expires_at"] = invoice["created_at"] + SPLIT_INVOICE_TTL_SECONDS
        invoice["split"] = build_invoice_split(
            invoice_id=invoice["invoice_id"],
            provider=provider,
            tier=invoice["tier"],
            amount_usdc=invoice["amount"],
            expires_at=invoice["expires_at"],
        )
        requirement["resource"] = invoice["split"]["legs"][0]["resource"]
        requirement["split"] = invoice["split"]
        requirement["settlement"]["mode"] = smode
        requirement["pay_to"] = None
    state.invoices_db[invoice["invoice_id"]] = invoice
    _save_invoice(invoice)
    return {
        "invoice_id": invoice["invoice_id"],
        "amount": invoice["amount"],
        "amount_usdc": invoice["amount"],
        "currency": invoice["settlement"]["currency"],
        "pricing": invoice["pricing"],
        "settlement": invoice["settlement"],
        "split": invoice.get("split"),
        "accounting": invoice["accounting"],
        "network": PAYMENT_NETWORK,
        "network_name": PAYMENT_NETWORK_NAME,
        "provider_id": invoice["provider_id"],
        "provider_name": provider.provider_name,
        "buyer_type": invoice["buyer_type"],
        "tier": invoice["tier"],
        "tier_label": paid_kit.SUPPORTED_TIERS[invoice["tier"]]["label"],
        "base_usdc": quote["base_usdc"],
        "complexity_score": quote["complexity_score"],
        "resource_type": invoice["resource_type"],
        "wallet_address": invoice["wallet_address"],
        "platform_treasury_wallet": invoice.get("platform_treasury_wallet"),
        "provider_owner_wallet": invoice["owner_wallet"],
        "synthetic": invoice.get("synthetic", False),
        "agent_label": invoice.get("agent_label"),
        "run_source": invoice.get("run_source"),
        "expires_at": invoice["expires_at"],
        "nonce": invoice["nonce"],
        "invoice_secret": invoice["invoice_secret"],
        "query_hash": invoice["query_hash"],
        "payment_requirement": requirement,
        "arc_gateway_url": requirement["resource"],
        "split_legs": invoice.get("split", {}).get("legs", []),
    }


def get_payment_invoice_status(invoice_id, invoice_secret, refresh=True):
    import hmac as _hmac
    from fastapi import status, Query
    invoice = get_invoice_or_402(state.invoices_db, invoice_id)
    hydrate_payment_schema(invoice)
    if not _hmac.compare_digest(str(invoice_secret), str(invoice.get("invoice_secret"))):
        from fastapi import HTTPException
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invoice secret mismatch.")
    changed = False
    if invoice_split_mode(invoice) == "x402_direct_split":
        old_status = invoice.get("status")
        refresh_split_invoice_status(invoice)
        if refresh:
            changed = refresh_split_leg_batch_txs(invoice) or changed
        invoice["gateway_status"] = aggregate_split_gateway_status(invoice)
        changed = changed or old_status != invoice.get("status")
        if invoice.get("status") == "paid":
            sync_split_payment_events(invoice)
            _save_payment_ledger(state.payment_events)
    elif refresh:
        before = (invoice.get("gateway_status"), invoice.get("transaction_hash"), invoice.get("explorer_url"))
        refresh_invoice_batch_tx(invoice)
        after = (invoice.get("gateway_status"), invoice.get("transaction_hash"), invoice.get("explorer_url"))
        changed = before != after
    if changed:
        _save_invoice(invoice)
    return invoice_payment_state_response(
        invoice_id, invoice, include_access_token=True,
        fetch_gateway_balance_fn=fetch_gateway_balance,
    )


def verify_split_payment(invoice_id, invoice, proof):
    import hmac as _hmac
    from fastapi import HTTPException
    refresh_split_invoice_status(invoice)
    if invoice.get("status") == "paid":
        if refresh_split_leg_batch_txs(invoice):
            sync_split_payment_events(invoice)
            _save_payment_ledger(state.payment_events)
        _save_invoice(invoice)
        return invoice_payment_state_response(invoice_id, invoice, include_access_token=True, fetch_gateway_balance_fn=fetch_gateway_balance)
    if invoice.get("status") == "expired":
        raise HTTPException(status_code=400, detail="Invoice expired. Create a new purchase.")
    required_legs = invoice_required_split_legs(invoice)
    if not required_legs:
        raise HTTPException(status_code=400, detail="Invoice has no split legs.")
    provided = {item.leg_id: item for item in proof.split_settlements or []}
    if len(provided) != len(proof.split_settlements or []):
        raise HTTPException(status_code=400, detail="Duplicate split settlement leg submitted.")
    missing = [leg.get("leg_id") for leg in required_legs if leg.get("leg_id") not in provided and not leg.get("settlement_id")]
    if missing:
        invoice["status"] = "partial_paid" if any(leg.get("settlement_id") for leg in required_legs) else "pending"
        _save_invoice(invoice)
        raise HTTPException(status_code=402, detail=f"Missing split settlement leg(s): {', '.join(missing)}")
    payer = normalize_address(proof.payer_address)
    verified_legs = []
    with state.cross_process_lock("split_leg:" + invoice_id):
      with state.split_leg_lock:
        for leg in required_legs:
            leg_id = leg.get("leg_id")
            submitted = provided.get(leg_id)
            if not submitted:
                continue
            if leg.get("status") == "paid" and leg.get("settlement_id"):
                if leg.get("settlement_id") != submitted.settlement_id:
                    raise HTTPException(status_code=409, detail=f"Split leg {leg_id} is already settled with a different settlement_id. Refusing to overwrite.")
                verified_legs.append(leg)
                continue
            if raw_usdc_str(submitted.amount_raw) != raw_usdc_str(leg.get("amount_raw")):
                raise HTTPException(status_code=400, detail=f"Split leg {leg_id} amount does not match invoice.")
            if normalize_address(submitted.pay_to) != normalize_address(leg.get("pay_to")):
                raise HTTPException(status_code=400, detail=f"Split leg {leg_id} pay_to does not match invoice.")
            has_authoritative_gateway_claims = bool(submitted.payer_address and submitted.gateway_status)
            receipt_valid = verify_split_receipt(
                invoice_id=invoice_id, leg_id=leg_id, pay_to=leg.get("pay_to"),
                settled_amount_raw=submitted.amount_raw, settlement_id=submitted.settlement_id,
                receipt=submitted.sidecar_receipt,
                payer_address=submitted.payer_address,
                gateway_status=submitted.gateway_status,
            ) if has_authoritative_gateway_claims else verify_split_receipt(
                invoice_id=invoice_id, leg_id=leg_id, pay_to=leg.get("pay_to"),
                settled_amount_raw=submitted.amount_raw, settlement_id=submitted.settlement_id,
                receipt=submitted.sidecar_receipt,
            )
            if not receipt_valid and has_authoritative_gateway_claims:
                # A legacy relay may include payer/status in its body while
                # still returning a five-field receipt. Keep it on the
                # authoritative Circle-lookup path instead of rejecting it.
                has_authoritative_gateway_claims = False
                receipt_valid = verify_split_receipt(
                    invoice_id=invoice_id, leg_id=leg_id, pay_to=leg.get("pay_to"),
                    settled_amount_raw=submitted.amount_raw, settlement_id=submitted.settlement_id,
                    receipt=submitted.sidecar_receipt,
                )
            if not receipt_valid:
                raise HTTPException(status_code=400, detail=f"Invalid sidecar receipt for split leg {leg_id}.")
            if settlement_id_already_claimed(submitted.settlement_id, exclude_invoice_id=invoice_id, load_invoices_fn=_load_invoices, invoices_db=state.invoices_db):
                raise HTTPException(status_code=409, detail=f"settlement_id for leg {leg_id} is already claimed by another invoice/leg.")
            if has_authoritative_gateway_claims:
                # Arc Gateway already fetched and validated this settlement
                # against Circle before signing the sidecar receipt. The HMAC
                # binds payer and status, so avoid repeating the remote GET.
                settlement = {
                    "status": submitted.gateway_status,
                    "toAddress": leg.get("pay_to"),
                    "fromAddress": submitted.payer_address,
                    "amount": submitted.amount_raw,
                }
            else:
                # Compatibility path for receipts issued before payer/status
                # were included in the signed sidecar proof.
                settlement = fetch_circle_settlement(submitted.settlement_id)
            validate_arc_split_leg_payment(invoice, leg, settlement, payer_address=proof.payer_address)
            settlement_payer = normalize_address(settlement.get("fromAddress"))
            if payer and settlement_payer != payer:
                raise HTTPException(status_code=400, detail="Split settlement payer mismatch.")
            payer = payer or settlement_payer
            batch = {"batch_tx": None, "explorer_url": None} if has_authoritative_gateway_claims else find_arc_batch_tx(settlement)
            leg.update({
                "status": "paid",
                "settlement_id": submitted.settlement_id,
                "payer_address": settlement_payer,
                "gateway_status": settlement.get("status"),
                "transaction_hash": batch.get("batch_tx"),
                "explorer_url": batch.get("explorer_url"),
                "paid_at": time.time(),
                "sidecar_receipt": submitted.sidecar_receipt,
            })
            verified_legs.append(leg)
        if not all(leg.get("status") == "paid" and leg.get("settlement_id") for leg in required_legs):
            invoice["status"] = "partial_paid"
            _save_invoice(invoice)
            raise HTTPException(status_code=402, detail="Invoice is partially paid. Complete all split legs before unlock.")
        invoice["status"] = "paid"
        invoice["paid_at"] = time.time()
        invoice["payer_address"] = payer
        invoice["settlement_id"] = f"split:{invoice_id}"
        invoice["split_settlement_ids"] = [leg.get("settlement_id") for leg in required_legs]
        invoice["gateway_status"] = aggregate_split_gateway_status(invoice)
        invoice["amount_raw"] = (invoice.get("split") or {}).get("total_amount_raw")
        invoice["verification_mode"] = "circle-gateway-x402-direct-split"
        _save_invoice(invoice)
    reload_persistent_state(include_reports=False)
    sync_split_payment_events(invoice)
    _save_payment_ledger(state.payment_events)
    _save_invoice(invoice)
    return invoice_payment_state_response(invoice_id, invoice, include_access_token=True, fetch_gateway_balance_fn=fetch_gateway_balance)


def verify_payment(invoice_id, proof=None):
    import hmac as _hmac
    from fastapi import HTTPException, status
    if proof is None:
        raise HTTPException(status_code=400, detail="payment proof is required.")
    invoice = get_invoice_or_402(state.invoices_db, invoice_id)
    hydrate_payment_schema(invoice)
    if not _hmac.compare_digest(str(proof.invoice_secret), str(invoice.get("invoice_secret"))):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invoice secret mismatch.")
    if invoice.get("status") == "paid":
        if invoice_split_mode(invoice) == "x402_direct_split":
            if refresh_split_leg_batch_txs(invoice):
                sync_split_payment_events(invoice)
                _save_payment_ledger(state.payment_events)
                _save_invoice(invoice)
        else:
            before = (invoice.get("gateway_status"), invoice.get("transaction_hash"), invoice.get("explorer_url"))
            refresh_invoice_batch_tx(invoice)
            after = (invoice.get("gateway_status"), invoice.get("transaction_hash"), invoice.get("explorer_url"))
            if before != after:
                _save_invoice(invoice)
        return invoice_payment_state_response(
            invoice_id, invoice, include_access_token=True, include_seller_balance=True,
            fetch_gateway_balance_fn=fetch_gateway_balance,
        )
    if invoice_split_mode(invoice) == "x402_direct_split" or proof.split_settlements:
        return verify_split_payment(invoice_id, invoice, proof)
    if not proof.settlement_id:
        raise HTTPException(status_code=400, detail="settlement_id is required.")
    if settlement_id_already_claimed(proof.settlement_id, exclude_invoice_id=invoice_id, load_invoices_fn=_load_invoices, invoices_db=state.invoices_db):
        raise HTTPException(status_code=409, detail="settlement_id is already claimed by another invoice.")
    with state.cross_process_lock("split_leg:" + invoice_id):
        invoice = get_invoice_or_402(state.invoices_db, invoice_id)
        hydrate_payment_schema(invoice)
        if invoice.get("status") == "paid":
            return invoice_payment_state_response(
                invoice_id, invoice, include_access_token=True, include_seller_balance=True,
                fetch_gateway_balance_fn=fetch_gateway_balance,
            )
        settlement = fetch_circle_settlement(proof.settlement_id)
        validate_arc_payment(invoice, settlement, payer_address=proof.payer_address)
        batch = find_arc_batch_tx(settlement)
        invoice["status"] = "paid"
        invoice["paid_at"] = time.time()
        invoice["settlement_id"] = proof.settlement_id
        invoice["transaction_hash"] = batch.get("batch_tx")
        invoice["explorer_url"] = batch.get("explorer_url")
        invoice["payer_address"] = settlement.get("fromAddress")
        invoice["gateway_status"] = settlement.get("status")
        invoice["amount_raw"] = settlement.get("amount")
        invoice["verification_mode"] = "circle-gateway-arc-testnet"
        _save_invoice(invoice)
    reload_persistent_state(include_reports=False)
    if not any(event.get("settlement_id") == proof.settlement_id for event in state.payment_events):
        state.payment_events.append({
            "invoice_id": invoice_id,
            "symbol": invoice.get("symbol"),
            "provider_id": invoice.get("provider_id", "funding_memory"),
            "provider_owner_wallet": invoice.get("owner_wallet"),
            "buyer_type": invoice.get("buyer_type", "human"),
            "synthetic": invoice.get("synthetic", False),
            "agent_label": invoice.get("agent_label"),
            "run_source": invoice.get("run_source"),
            "tier": invoice.get("tier", "full"),
            "resource_type": invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
            "query": invoice.get("query"),
            "query_hash": invoice.get("query_hash"),
            "payer_address": invoice.get("payer_address"),
            "seller_address": PAYMENT_WALLET_ADDRESS,
            "amount_usdc": invoice.get("amount"),
            "amount_raw": invoice.get("amount_raw"),
            "pricing": invoice.get("pricing"),
            "settlement": invoice.get("settlement"),
            "accounting": invoice.get("accounting"),
            "settlement_id": invoice.get("settlement_id"),
            "gateway_status": invoice.get("gateway_status"),
            "transaction_hash": invoice.get("transaction_hash"),
            "explorer_url": invoice.get("explorer_url"),
            "paid_at": invoice.get("paid_at"),
        })
        _save_payment_ledger(state.payment_events)
        _save_invoice(invoice)
    return invoice_payment_state_response(
        invoice_id, invoice, include_access_token=True, include_seller_balance=True,
        fetch_gateway_balance_fn=fetch_gateway_balance,
    )


def submit_withdraw(payload):
    import json as _json
    import requests
    from fastapi import HTTPException
    burn_intent = payload.get("burnIntent")
    signature = payload.get("signature")
    if not burn_intent or not signature:
        raise HTTPException(status_code=400, detail="burnIntent and signature are required")
    try:
        requested_depositor = bytes32_to_address((burn_intent.get("spec") or {}).get("sourceDepositor"))
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=400, detail=f"Withdraw intent depositor is invalid: {exc}")
    withdraw_owner = authorized_gateway_withdraw_depositor(requested_depositor)
    expected_depositor = withdraw_owner["address"]
    intent = validate_withdraw_intent(burn_intent, expected_depositor=expected_depositor)
    if WITHDRAW_MODE in ("platform_relayed", "relayed", "gasless"):
        enforce_withdraw_relay_policy(intent)
        try:
            relay_resp = requests.post(
                f"{ARC_GATEWAY_BASE_URL.rstrip('/')}/api/withdraw/relay",
                json={"burnIntent": burn_intent, "signature": signature, "expectedDepositor": expected_depositor},
                timeout=120,
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"Withdraw relayer unavailable: {exc}")
        if not relay_resp.ok:
            try:
                relay_error = relay_resp.json()
            except Exception:
                relay_error = {"error": relay_resp.text[:300]}
            raise HTTPException(
                status_code=relay_resp.status_code,
                detail=relay_error.get("error") or relay_error.get("detail") or f"Relayer returned {relay_resp.status_code}",
            )
        data = relay_resp.json()
        record_withdraw_relay(intent)
        return {
            **data,
            "withdraw_mode": "platform_relayed",
            "relayed": True,
            "amount_usdc": data.get("amount_usdc", f"{intent['amount_usdc']:.6f}"),
            "withdraw_owner": withdraw_owner,
        }
    try:
        resp = requests.post(
            f"{ARC_GATEWAY_API}/v1/transfer",
            json=[{"burnIntent": burn_intent, "signature": signature}],
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if data.get("success") is False or data.get("error") or not data.get("attestation") or not data.get("signature"):
                raise HTTPException(status_code=502, detail=f"Circle Gateway did not return a mint attestation: {_json.dumps(data)[:300]}")
            return {
                **data,
                "withdraw_mode": "seller_wallet",
                "relayed": False,
                "amount_usdc": f"{intent['amount_usdc']:.6f}",
                "withdraw_owner": withdraw_owner,
            }
        raise HTTPException(status_code=502, detail=f"Circle Gateway transfer API returned {resp.status_code}: {resp.text[:300]}")
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        logger.warning(f"Circle transfer API failed: {exc}.")
        raise HTTPException(status_code=502, detail=f"Circle Gateway transfer API failed: {exc}")


def authorize_paid_invoice(*, query, invoice_id, token, required_tier, provider_id="funding_memory"):
    from fastapi import HTTPException, status
    invoice = get_invoice_or_402(state.invoices_db, invoice_id)
    if invoice.get("provider_id", "funding_memory") != provider_id:
        raise HTTPException(status_code=400, detail="Invoice provider does not match requested provider.")
    if invoice_has_failed_settlement(invoice):
        if invoice.get("status") != "disputed":
            invoice["status"] = "disputed"
            _save_invoice(invoice)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "settlement_disputed", "message": "Circle reported a terminal settlement failure for this invoice after access was granted. No further access will be issued; contact support if you believe this is an error."},
        )
    if invoice["status"] != "paid":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "payment_not_settled",
                "message": f"Invoice is {invoice['status']}. Complete the USDC payment before analysis.",
                "payment": payment_requirement(
                    invoice_id=invoice_id, symbol=invoice["symbol"],
                    amount_usdc=invoice.get("amount"),
                    tier=invoice.get("tier", required_tier),
                    resource_type=invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
                    provider_id=invoice.get("provider_id", provider_id),
                ),
            },
        )
    if invoice["symbol"].upper() != str(query.get("symbol", "")).upper():
        raise HTTPException(status_code=400, detail="Invoice symbol does not match query symbol.")
    current_query_hash = query_fingerprint(query)
    if invoice.get("query_hash") != current_query_hash:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Paid invoice is bound to a different query snapshot. Create a fresh invoice for changed signal data.")
    token_payload = verify_access_token(token or "")
    try:
        paid_kit.require_access(token_payload, invoice, required_tier=required_tier)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return invoice


def build_preview_report(full_report, invoice):
    analogs = full_report.get("analogs", [])[:3]
    win_rate = float(full_report.get("weighted_win_rate") or 0)
    win_rate_band = "high" if win_rate >= 70 else ("medium" if win_rate >= 50 else "low")
    return {
        "query_symbol": full_report.get("query_symbol"),
        "query": full_report.get("query"),
        "query_hash": full_report.get("query_hash"),
        "tier": "preview",
        "funding_context": {
            "fundingRate": full_report.get("query", {}).get("fundingRate"),
            "marketCap": full_report.get("query", {}).get("marketCap"),
            "circRatio": full_report.get("query", {}).get("circRatio"),
            "fromATH": full_report.get("query", {}).get("fromATH"),
            "volume24h": full_report.get("query", {}).get("volume24h"),
        },
        "regime_cluster": full_report.get("regime_cluster"),
        "regime_description": full_report.get("regime_description"),
        "is_ood": full_report.get("is_ood"),
        "ood_p_value": full_report.get("ood_p_value"),
        "win_rate_band": win_rate_band,
        "rough_win_rate": round(win_rate, 1),
        "top_analogs": [
            {"symbol": item.get("symbol"), "fundingRate": item.get("fundingRate"), "similarity": item.get("similarity"), "profit_pct": item.get("profit_pct")}
            for item in analogs
        ],
        "upgrade_cta": "Upgrade to the full report for all analogs, weighted percentiles, confidence intervals, and evidence diagnostics.",
        "invoice": full_report.get("invoice"),
        "provider_note": full_report.get("provider_note"),
        "analysis_focus": full_report.get("analysis_focus"),
        "turnover_context": full_report.get("turnover_context"),
        "provider_diagnostics": full_report.get("provider_diagnostics"),
    }


def invoice_report_meta(invoice_id, invoice):
    hydrate_payment_schema(invoice)
    return {
        "invoice_id": invoice_id, "status": "paid",
        "provider_id": invoice.get("provider_id", "funding_memory"),
        "buyer_type": invoice.get("buyer_type", "human"),
        "tier": invoice.get("tier", "full"),
        "settlement_id": invoice.get("settlement_id"),
        "gateway_status": invoice.get("gateway_status"),
        "transaction_hash": invoice.get("transaction_hash"),
        "explorer_url": invoice.get("explorer_url"),
        "payer_address": invoice.get("payer_address"),
        "provider_owner_wallet": invoice.get("owner_wallet"),
        "amount_usdc": invoice.get("amount"),
        "pricing": invoice.get("pricing"),
        "settlement": invoice.get("settlement"),
        "accounting": invoice.get("accounting"),
        "network": invoice.get("network"),
        "verification_mode": invoice.get("verification_mode"),
    }


def run_paid_provider_report(*, provider_id, query, invoice_id, token, required_tier):
    from fastapi.encoders import jsonable_encoder
    from backend.app.schemas import QueryModel
    provider = get_provider_or_404(provider_registry, provider_id)
    normalized_query = normalize_query_for_provider(provider, model_to_dict(query))
    invoice = authorize_paid_invoice(
        query=normalized_query, invoice_id=invoice_id, token=token,
        required_tier=required_tier, provider_id=provider.provider_id,
    )
    refresh_invoice_batch_tx(invoice)
    full_report = provider.full_report(normalized_query)
    full_report["query"] = invoice.get("query") or canonical_query_payload(normalized_query)
    full_report["query_hash"] = invoice.get("query_hash")
    full_report["provider_id"] = provider.provider_id
    full_report["provider_name"] = provider.provider_name
    full_report["provider_owner_wallet"] = provider.owner_wallet
    full_report["invoice"] = invoice_report_meta(invoice_id, invoice)
    if required_tier == "preview":
        report = build_preview_report(full_report, invoice)
        report["provider_id"] = provider.provider_id
        report["provider_name"] = provider.provider_name
    else:
        full_report["tier"] = "full"
        full_report["paid_at"] = invoice.get("paid_at")
        report = full_report
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
    return settlement_id_already_claimed(sid, exclude_invoice_id=exclude_invoice_id, load_invoices_fn=_load_invoices, invoices_db=state.invoices_db)

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
        scan_mexc_live=scan_mexc_live,
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
    compact_payment_event=compact_payment_event,
    fetch_gateway_balance_cached=fetch_gateway_balance_cached,
    invoices_db=state.invoices_db,
    load_platform_payment_events=_load_platform_payment_events,
    maybe_refresh_unresolved_payment_events=_maybe_refresh,
    paginate_items=paginate_items,
    payment_wallet_address=PAYMENT_WALLET_ADDRESS,
    summarize_payment_events=_summarize_payment_events,
)))

app.include_router(create_market_router(SimpleNamespace(
    cache_ttl_seconds=CACHE_TTL_SECONDS,
    live_anomalies_cache=state.live_anomalies_cache,
    live_scan_lock=state.live_scan_lock,
    logger=logger,
    market_data_adapter=market_data_adapter,
    normalize_query_for_provider=normalize_query_for_provider,
    pricing_config=paid_kit.pricing_config,
    provider_control=provider_control,
    provider_registry=provider_registry,
    scan_mexc_live=scan_mexc_live,
)))

app.include_router(create_agent_router(SimpleNamespace(
    get_agent_recommendations=_get_agent_recommendations,
    load_wallet_entitlements=_load_wallet_entitlements,
    provider_registry=provider_registry,
)))

app.include_router(create_chat_router(SimpleNamespace(
    get_invoices_db=lambda: state.invoices_db,
    get_paid_reports=lambda: state.paid_reports,
    reload_persistent_state=reload_persistent_state,
)))

app.include_router(create_internal_router(SimpleNamespace(
    arc_gateway_internal_secret=ARC_GATEWAY_INTERNAL_SECRET,
    cross_process_lock=state.cross_process_lock,
    invoice_split_mode=invoice_split_mode,
    invoices_db=state.invoices_db,
    normalize_address=normalize_address,
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

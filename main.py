import os
import time
import uuid
import requests
import logging
import json
import base64
import hashlib
import hmac
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, Optional, List
from fastapi import FastAPI, HTTPException, status, Query, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Import QMA Engine
from qma_engine import QMAEngine
import paid_intelligence_kit as paid_kit
from providers import create_default_registry
from storage import create_storage_backend
try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
except Exception:  # pragma: no cover - optional dependency guard for minimal installs
    Account = None
    encode_defunct = None

# Configure Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("QMA-API")

def load_local_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

load_local_env()

app = FastAPI(
    title="Quant Memory Agent (QMA) Server",
    description=(
        "Paid intelligence API for Arc/Circle USDC micropayments. "
        "List providers, create query-bound invoices, verify settlement, then call paid preview/full report endpoints."
    ),
    version="1.0.0"
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/public", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "public")), name="public")

# Initialize QMA Engine
engine = QMAEngine()

PAYMENT_LEDGER_PATH = os.path.join(os.path.dirname(__file__), "payment_ledger.json")
PAID_REPORTS_PATH = os.path.join(os.path.dirname(__file__), "paid_reports.json")
INVOICES_PATH = os.path.join(os.path.dirname(__file__), "invoices.json")
CREATOR_APPLICATIONS_PATH = os.path.join(os.path.dirname(__file__), "creator_applications.json")
PROVIDER_CONTROLS_PATH = os.path.join(os.path.dirname(__file__), "provider_controls.json")
PAYMENT_AMOUNT_USDC = float(os.getenv("QMA_PAYMENT_AMOUNT_USDC", os.getenv("QMA_PRICE_FULL_USDC", "0.005")))
PAYMENT_RESOURCE_TYPE = os.getenv("QMA_PAYMENT_RESOURCE_TYPE", "qma_signal_report")
PAYMENT_NETWORK = os.getenv("QMA_PAYMENT_NETWORK", "eip155:5042002")
PAYMENT_NETWORK_NAME = os.getenv("QMA_PAYMENT_NETWORK_NAME", "Arc Testnet")
PAYMENT_WALLET_ADDRESS = os.getenv("QMA_ARC_SELLER_ADDRESS", "0x933a2405f84c224be1ef373ba16e992e1f459682")
ARC_GATEWAY_BASE_URL = os.getenv("QMA_ARC_GATEWAY_URL", "http://127.0.0.1:3000")
ARC_GATEWAY_API = os.getenv("QMA_CIRCLE_GATEWAY_API", "https://gateway-api-testnet.circle.com")
ARC_EXPLORER = os.getenv("QMA_ARC_EXPLORER", "https://testnet.arcscan.app")
ARC_GATEWAY_WALLET = os.getenv("QMA_ARC_GATEWAY_WALLET", "0x0077777d7EBA4688BDeF3E311b846F25870A19B9")
INVOICE_TTL_SECONDS = int(os.getenv("QMA_INVOICE_TTL_SECONDS", "900"))
ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("QMA_ACCESS_TOKEN_TTL_SECONDS", "300"))
WALLET_PROFILE_TOKEN_TTL_SECONDS = int(os.getenv("QMA_WALLET_PROFILE_TOKEN_TTL_SECONDS", "3600"))
ACCESS_TOKEN_SECRET = os.getenv("QMA_ACCESS_TOKEN_SECRET") or os.getenv("QMA_SESSION_SECRET") or "qma-local-demo-secret-change-me"
ADMIN_TOKEN = os.getenv("QMA_ADMIN_TOKEN", "")
ADMIN_WALLET_ADDRESS = os.getenv("QMA_ADMIN_WALLET", PAYMENT_WALLET_ADDRESS)
RATE_LIMIT_ENABLED = os.getenv("QMA_RATE_LIMIT_ENABLED", "true").lower() not in ("false", "0", "no")
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("QMA_RATE_LIMIT_WINDOW_SECONDS", "60"))
# Strict mode: if True, /analyze is blocked until Circle batch is "completed"/"confirmed".
# Default False = unlock immediately on "received" (x402 UX). Set to "true" in .env for strict.
REQUIRE_COMPLETED_SETTLEMENT = os.getenv("QMA_REQUIRE_COMPLETED_SETTLEMENT", "false").lower() in ("true", "1", "yes")
GATEWAY_DEFAULT_DEPOSIT_USDC = float(os.getenv("QMA_ARC_DEFAULT_DEPOSIT_USDC", "1.00"))
ARC_BATCH_TX_CACHE_TTL_SECONDS = int(os.getenv("QMA_ARC_BATCH_TX_CACHE_TTL_SECONDS", "60"))
PAYMENT_EVENT_REFRESH_TTL_SECONDS = int(os.getenv("QMA_PAYMENT_EVENT_REFRESH_TTL_SECONDS", "90"))
GATEWAY_DEFAULT_APPROVE_USDC = float(os.getenv("QMA_ARC_DEFAULT_APPROVE_USDC", "10.00"))
provider_registry = create_default_registry(engine=engine, default_owner_wallet=PAYMENT_WALLET_ADDRESS)
storage_backend = create_storage_backend(
    ledger_path=PAYMENT_LEDGER_PATH,
    reports_path=PAID_REPORTS_PATH,
    invoices_path=INVOICES_PATH,
    creators_path=CREATOR_APPLICATIONS_PATH,
    provider_controls_path=PROVIDER_CONTROLS_PATH,
)
provider_runtime_controls: Dict[str, dict] = {}

rate_limit_buckets = defaultdict(deque)

def client_ip_from_request(request: Request) -> str:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"

def rate_limit_for_path(path: str) -> tuple[str, int]:
    if path.startswith("/api/v1/payment/verify"):
        return "payment_verify", int(os.getenv("QMA_RATE_LIMIT_PAYMENT_VERIFY_PER_MIN", "8"))
    if path.startswith("/api/v1/payment/invoice"):
        return "payment_invoice", int(os.getenv("QMA_RATE_LIMIT_INVOICE_PER_MIN", "20"))
    if path.startswith("/api/v1/providers/") and (path.endswith("/preview") or path.endswith("/full-report")):
        return "paid_report", int(os.getenv("QMA_RATE_LIMIT_REPORT_PER_MIN", "30"))
    if path.startswith("/api/v1/preview") or path.startswith("/api/v1/analyze"):
        return "paid_report", int(os.getenv("QMA_RATE_LIMIT_REPORT_PER_MIN", "30"))
    if path.startswith("/api/v1/live-anomalies") or path.startswith("/api/v1/agent/recommendations"):
        return "public_market", int(os.getenv("QMA_RATE_LIMIT_PUBLIC_MARKET_PER_MIN", "120"))
    if path.startswith("/api/v1/creators/apply"):
        return "creator_apply", int(os.getenv("QMA_RATE_LIMIT_CREATOR_APPLY_PER_MIN", "6"))
    if path.startswith("/api/v1/"):
        return "api_default", int(os.getenv("QMA_RATE_LIMIT_API_DEFAULT_PER_MIN", "240"))
    return "html", 0

@app.middleware("http")
async def qma_rate_limit_middleware(request: Request, call_next):
    if not RATE_LIMIT_ENABLED or request.method == "OPTIONS":
        return await call_next(request)
    scope, limit = rate_limit_for_path(request.url.path)
    if limit <= 0:
        return await call_next(request)
    now = time.time()
    key = f"{scope}:{client_ip_from_request(request)}"
    bucket = rate_limit_buckets[key]
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

def load_payment_ledger() -> list:
    try:
        return storage_backend.load_payment_events()
    except Exception as exc:
        logger.warning(f"Could not load payment ledger: {exc}")
        return []

def load_payment_events_for_wallet(address: str) -> list:
    try:
        if hasattr(storage_backend, "load_payment_events_for_wallet"):
            return storage_backend.load_payment_events_for_wallet(address)
    except Exception as exc:
        logger.warning(f"Could not load wallet payment events: {exc}")
    normalized = normalize_address(address)
    return [
        event for event in load_payment_ledger()
        if normalize_address(event.get("payer_address")) == normalized
    ]

def load_payment_event_summaries(limit: int = 5000) -> list:
    try:
        if hasattr(storage_backend, "load_payment_event_summaries"):
            return storage_backend.load_payment_event_summaries(limit=limit)
    except Exception as exc:
        logger.warning(f"Could not load payment event summaries: {exc}")
    return sorted(load_payment_ledger(), key=lambda item: item.get("paid_at") or 0, reverse=True)[:limit]

def save_payment_ledger(events: list) -> None:
    try:
        storage_backend.save_payment_events(events)
    except Exception as exc:
        logger.warning(f"Could not save payment ledger: {exc}")

payment_events = load_payment_ledger()

def load_paid_reports() -> dict:
    try:
        return storage_backend.load_paid_reports()
    except Exception as exc:
        logger.warning(f"Could not load paid reports: {exc}")
        return {}

def load_paid_reports_for_wallet(
    address: str,
    *,
    symbol: Optional[str] = None,
    provider_id: Optional[str] = None,
) -> dict:
    try:
        if hasattr(storage_backend, "load_paid_reports_for_wallet"):
            return storage_backend.load_paid_reports_for_wallet(
                address,
                symbol=symbol,
                provider_id=provider_id,
            )
    except Exception as exc:
        logger.warning(f"Could not load wallet paid reports: {exc}")
    normalized = normalize_address(address)
    symbol_filter = str(symbol or "").strip().upper()
    return {
        entitlement_id: record for entitlement_id, record in load_paid_reports().items()
        if isinstance(record, dict)
        and normalize_address(record.get("payer_address")) == normalized
        and (not symbol_filter or str(record.get("symbol", "")).upper() == symbol_filter)
        and (not provider_id or record.get("provider_id", "funding_memory") == provider_id)
    }

def load_paid_report_summaries_for_wallet(
    address: str,
    *,
    symbol: Optional[str] = None,
    provider_id: Optional[str] = None,
) -> list:
    try:
        if hasattr(storage_backend, "load_paid_report_summaries_for_wallet"):
            return storage_backend.load_paid_report_summaries_for_wallet(
                address,
                symbol=symbol,
                provider_id=provider_id,
            )
    except Exception as exc:
        logger.warning(f"Could not load wallet report summaries: {exc}")
    return [
        {
            "entitlement_id": entitlement_id,
            "payer_address": record.get("payer_address"),
            "symbol": record.get("symbol"),
            "tier": record.get("tier"),
            "provider_id": record.get("provider_id", "funding_memory"),
            "query_hash": record.get("query_hash"),
            "settlement_id": record.get("settlement_id"),
            "paid_at": record.get("paid_at"),
            "saved_at": record.get("saved_at"),
            "has_report": isinstance(record.get("report"), dict),
        }
        for entitlement_id, record in load_paid_reports_for_wallet(
            address,
            symbol=symbol,
            provider_id=provider_id,
        ).items()
    ]

def load_paid_report_summaries(limit: int = 5000) -> list:
    try:
        if hasattr(storage_backend, "load_paid_report_summaries"):
            return storage_backend.load_paid_report_summaries(limit=limit)
    except Exception as exc:
        logger.warning(f"Could not load paid report summaries: {exc}")
    return [
        {
            "entitlement_id": entitlement_id,
            "payer_address": record.get("payer_address"),
            "symbol": record.get("symbol"),
            "tier": record.get("tier"),
            "provider_id": record.get("provider_id", "funding_memory"),
            "query_hash": record.get("query_hash"),
            "settlement_id": record.get("settlement_id"),
            "paid_at": record.get("paid_at"),
            "saved_at": record.get("saved_at"),
            "buyer_type": record.get("buyer_type", "human"),
            "gateway_status": record.get("gateway_status"),
            "transaction_hash": record.get("transaction_hash"),
            "explorer_url": record.get("explorer_url"),
            "amount_usdc": record.get("amount_usdc"),
            "has_report": isinstance(record.get("report"), dict),
        }
        for entitlement_id, record in list(load_paid_reports().items())[:limit]
    ]

def load_paid_report_by_id(address: str, entitlement_id: str) -> Optional[dict]:
    normalized = normalize_address(address)
    
    # Helper to clean up provider prefix if present
    def clean_id(eid: str) -> str:
        parts = eid.split(":")
        # If format is {provider}:{address}:{hash}:{tier}, strip the provider part
        if len(parts) == 4:
            return ":".join(parts[1:])
        return eid

    target_clean = clean_id(entitlement_id)
    
    # Try exact match first on the storage backend
    try:
        if hasattr(storage_backend, "load_paid_report_by_id"):
            record = storage_backend.load_paid_report_by_id(address, entitlement_id)
            if record:
                return record
            # Try with other possible prefix matches if exact match failed
            if entitlement_id != target_clean:
                # Direct match using stripped ID
                record = storage_backend.load_paid_report_by_id(address, target_clean)
                if record:
                    return record
            else:
                # It has no prefix, try with 'funding_memory' prefix
                record = storage_backend.load_paid_report_by_id(address, f"funding_memory:{entitlement_id}")
                if record:
                    return record
                record = storage_backend.load_paid_report_by_id(address, f"oi_memory:{entitlement_id}")
                if record:
                    return record
    except Exception as exc:
        logger.warning(f"Could not load paid report from backend: {exc}")

    # Fallback to scanning all reports loaded from the file/backend
    try:
        reports = load_paid_reports()
        for kid, rec in reports.items():
            if clean_id(kid) == target_clean:
                if isinstance(rec, dict) and normalize_address(rec.get("payer_address")) == normalized:
                    return rec
    except Exception as exc:
        logger.warning(f"Fallback scan failed: {exc}")

    return None

def save_paid_reports(reports: dict) -> None:
    try:
        storage_backend.save_paid_reports(reports)
    except Exception as exc:
        logger.warning(f"Could not save paid reports: {exc}")

paid_reports = load_paid_reports()

def load_invoices() -> dict:
    try:
        return storage_backend.load_invoices()
    except Exception as exc:
        logger.warning(f"Could not load invoices: {exc}")
        return {}

def load_paid_invoices_for_wallet(address: str) -> dict:
    try:
        if hasattr(storage_backend, "load_paid_invoices_for_wallet"):
            return storage_backend.load_paid_invoices_for_wallet(address)
    except Exception as exc:
        logger.warning(f"Could not load wallet paid invoices: {exc}")
    normalized = normalize_address(address)
    return {
        invoice_id: invoice for invoice_id, invoice in load_invoices().items()
        if isinstance(invoice, dict)
        and normalize_address(invoice.get("payer_address")) == normalized
        and invoice.get("status") == "paid"
    }

def paid_invoice_event(invoice: dict) -> dict:
    return {
        "invoice_id": invoice.get("invoice_id"),
        "symbol": invoice.get("symbol"),
        "provider_id": invoice.get("provider_id", "funding_memory"),
        "provider_owner_wallet": invoice.get("owner_wallet"),
        "buyer_type": invoice.get("buyer_type", "human"),
        "tier": invoice.get("tier", "full"),
        "resource_type": invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
        "payer_address": invoice.get("payer_address"),
        "seller_address": PAYMENT_WALLET_ADDRESS,
        "amount_usdc": invoice.get("amount"),
        "amount_raw": invoice.get("amount_raw"),
        "settlement_id": invoice.get("settlement_id"),
        "gateway_status": invoice.get("gateway_status"),
        "transaction_hash": invoice.get("transaction_hash"),
        "explorer_url": invoice.get("explorer_url"),
        "paid_at": invoice.get("paid_at"),
        "query_hash": invoice.get("query_hash"),
    }

def load_paid_invoice_events() -> list:
    try:
        if hasattr(storage_backend, "load_paid_invoice_events"):
            return storage_backend.load_paid_invoice_events()
    except Exception as exc:
        logger.warning(f"Could not load paid invoice events: {exc}")
    return [
        paid_invoice_event(invoice)
        for invoice in load_invoices().values()
        if isinstance(invoice, dict) and invoice.get("status") == "paid"
    ]

def save_invoice(invoice: dict) -> None:
    try:
        storage_backend.save_invoice(invoice)
    except Exception as exc:
        logger.warning(f"Could not save invoice: {exc}")

def load_creator_applications() -> dict:
    try:
        return storage_backend.load_creator_applications()
    except Exception as exc:
        logger.warning(f"Could not load creator applications: {exc}")
        return {}

def save_creator_application(application: dict) -> bool:
    try:
        storage_backend.save_creator_application(application)
        return True
    except Exception as exc:
        logger.warning(f"Could not save creator application: {exc}")
        return False

def load_provider_controls() -> dict:
    try:
        if hasattr(storage_backend, "load_provider_controls"):
            return storage_backend.load_provider_controls()
    except Exception as exc:
        logger.warning(f"Could not load provider controls: {exc}")
    return {}

def save_provider_control(provider_id: str, control: dict) -> bool:
    try:
        if hasattr(storage_backend, "save_provider_control"):
            storage_backend.save_provider_control(provider_id, control)
        return True
    except Exception as exc:
        logger.warning(f"Could not save provider control: {exc}")
        return False

# format: {invoice_id: {"status": "pending"|"paid", "created_at": float, "symbol": str}}
invoices_db: Dict[str, dict] = load_invoices()
creator_applications: Dict[str, dict] = load_creator_applications()
provider_runtime_controls.update(load_provider_controls())

def reload_persistent_state(include_reports: bool = True, include_invoices: bool = False) -> None:
    global payment_events, paid_reports, invoices_db
    payment_events = load_payment_ledger()
    if include_reports:
        paid_reports = load_paid_reports()
    if include_invoices:
        invoices_db = load_invoices()
    creator_applications.update(load_creator_applications())

# Simple Cache for Live MEXC Anomalies
live_anomalies_cache = {
    "data": [],
    "last_updated": 0.0
}
CACHE_TTL_SECONDS = 30.0
live_scan_lock = threading.Lock()
MEXC_FETCH_CONTRACT_DETAILS = os.getenv("QMA_MEXC_FETCH_CONTRACT_DETAILS", "false").lower() in ("true", "1", "yes")
MEXC_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "QMA-Lepton-Agent/1.0 (+https://qma-three.vercel.app)",
}

class QueryModel(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    fundingRate: float
    marketCap: float = Field(..., gt=0)
    FDV: float = Field(..., gt=0)
    circRatio: float = Field(..., gt=0, le=1.5)
    fromATH: float
    volume24h: float = Field(..., gt=0)
    amount: Optional[float] = Field(default=None, gt=0) # turnover proxy

class InvoiceRequest(QueryModel):
    provider_id: str = Field(default="funding_memory", max_length=64)
    tier: str = Field(default="full", pattern="^(preview|full)$")
    resource_type: str = Field(default="qma_signal_report", max_length=64)
    buyer_type: str = Field(default="human", pattern="^(human|agent)$")

class QuoteRequest(QueryModel):
    provider_id: str = Field(default="funding_memory", max_length=64)
    tier: str = Field(default="full", pattern="^(preview|full)$")

class PaymentVerifyRequest(BaseModel):
    settlement_id: str = Field(..., min_length=8)
    invoice_secret: str = Field(..., min_length=16)
    payer_address: Optional[str] = None
    amount_usdc: Optional[float] = None

class WalletProfileSessionRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=120)
    issued_at: int = Field(..., gt=0)
    signature: str = Field(..., min_length=20, max_length=300)

class CreatorApplicationRequest(BaseModel):
    creator_wallet: str = Field(..., min_length=8, max_length=80)
    provider_id: str = Field(..., min_length=3, max_length=64, pattern="^[a-z0-9_\\-]+$")
    provider_name: str = Field(..., min_length=3, max_length=120)
    contact: str = Field(..., min_length=3, max_length=160)
    category: str = Field(default="market_memory", max_length=64)
    description: str = Field(..., min_length=20, max_length=800)
    data_source: str = Field(..., min_length=3, max_length=240)
    api_base_url: Optional[str] = Field(default=None, max_length=240)
    sample_schema: Optional[str] = Field(default=None, max_length=1200)
    revenue_wallet: Optional[str] = Field(default=None, max_length=80)
    revenue_share_bps: int = Field(default=8000, ge=1000, le=9500)

class CreatorReviewRequest(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected|needs_changes|pending)$")
    admin_note: Optional[str] = Field(default=None, max_length=600)

class ProviderToggleRequest(BaseModel):
    enabled: bool
    admin_note: Optional[str] = Field(default=None, max_length=300)

def model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()

def canonical_query_payload(query: dict) -> dict:
    return paid_kit.canonical_query_payload(query)

def query_fingerprint(query: dict) -> str:
    return paid_kit.query_fingerprint(query)

def sign_access_token(payload: dict) -> str:
    return paid_kit.sign_access_token(payload, secret=ACCESS_TOKEN_SECRET, ttl_seconds=ACCESS_TOKEN_TTL_SECONDS)

def verify_access_token(token: str) -> dict:
    try:
        return paid_kit.verify_access_token(token, secret=ACCESS_TOKEN_SECRET)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

def wallet_profile_message(address: str, nonce: str, issued_at: int) -> str:
    normalized = paid_kit.normalize_address(address)
    return (
        "QMA Wallet Profile Access\n"
        f"Wallet: {normalized}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}\n"
        "Purpose: unlock-paid-report-snapshots"
    )

def verify_wallet_profile_token(address: str, token: str) -> dict:
    payload = verify_access_token(token or "")
    expected = paid_kit.normalize_address(address)
    actual = paid_kit.normalize_address(payload.get("wallet"))
    if payload.get("scope") != "wallet_profile" or actual != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Wallet profile token does not match this wallet.")
    return payload

def wallet_profile_token_payload(address: str, payload: WalletProfileSessionRequest) -> dict:
    if Account is None or encode_defunct is None:
        raise HTTPException(status_code=503, detail="eth_account is not installed; wallet profile signatures cannot be verified.")
    issued_at = int(payload.issued_at)
    now = int(time.time())
    if abs(now - issued_at) > 300:
        raise HTTPException(status_code=400, detail="Wallet profile signature is expired. Retry profile unlock.")
    message = wallet_profile_message(address, payload.nonce, issued_at)
    try:
        recovered = Account.recover_message(encode_defunct(text=message), signature=payload.signature)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid wallet profile signature: {exc}")
    expected = paid_kit.normalize_address(address)
    if paid_kit.normalize_address(recovered) != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Wallet profile signature does not match requested wallet.")
    return {
        "scope": "wallet_profile",
        "wallet": expected,
        "nonce": payload.nonce,
        "purpose": "unlock-paid-report-snapshots",
    }

def public_payment_row(row: dict) -> dict:
    blocked = {"entitlement_id", "has_report"}
    return {key: value for key, value in row.items() if key not in blocked}

def public_entitlement_row(record: dict) -> dict:
    return {
        "payer_address": record.get("payer_address"),
        "symbol": record.get("symbol"),
        "tier": record.get("tier"),
        "provider_id": record.get("provider_id"),
        "query_hash": record.get("query_hash"),
        "settlement_id": record.get("settlement_id"),
        "paid_at": record.get("paid_at"),
        "saved_at": record.get("saved_at"),
        "gateway_status": record.get("gateway_status") or record.get("report", {}).get("invoice", {}).get("gateway_status"),
        "transaction_hash": record.get("transaction_hash") or record.get("report", {}).get("invoice", {}).get("transaction_hash"),
        "explorer_url": record.get("explorer_url") or record.get("report", {}).get("invoice", {}).get("explorer_url"),
    }

def payment_requirement(
    invoice_id: Optional[str] = None,
    symbol: Optional[str] = None,
    amount_usdc: Optional[float] = None,
    tier: str = "full",
    resource_type: str = PAYMENT_RESOURCE_TYPE,
    provider_id: str = "funding_memory",
) -> dict:
    return paid_kit.payment_requirement(
        invoice_id=invoice_id,
        symbol=symbol,
        amount_usdc=float(amount_usdc if amount_usdc is not None else paid_kit.tier_price(tier)),
        tier=paid_kit.normalize_tier(tier),
        resource_type=resource_type,
        provider_id=provider_id,
        network=PAYMENT_NETWORK,
        network_name=PAYMENT_NETWORK_NAME,
        seller_address=PAYMENT_WALLET_ADDRESS,
        gateway_base_url=ARC_GATEWAY_BASE_URL,
        facilitator_url=ARC_GATEWAY_API,
        explorer_url=ARC_EXPLORER,
        ttl_seconds=INVOICE_TTL_SECONDS,
    )

def get_invoice_or_402(invoice_id: str) -> dict:
    invoice = invoices_db.get(invoice_id)
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "payment_required",
                "message": "Create and settle a USDC invoice before requesting this report.",
                "payment": payment_requirement(invoice_id=invoice_id),
            },
        )
    if time.time() > invoice["expires_at"]:
        invoice["status"] = "expired"
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "invoice_expired",
                "message": "Invoice expired. Create a fresh invoice.",
                "payment": payment_requirement(
                    symbol=invoice["symbol"],
                    amount_usdc=invoice.get("amount"),
                    tier=invoice.get("tier", "full"),
                    resource_type=invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
                    provider_id=invoice.get("provider_id", "funding_memory"),
                ),
            },
        )
    return invoice

def fetch_circle_settlement(settlement_id: str) -> dict:
    try:
        resp = requests.get(f"{ARC_GATEWAY_API}/v1/x402/transfers/{settlement_id}", timeout=10)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Circle Gateway lookup failed: {exc}")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Circle settlement not found")
    if not resp.ok:
        raise HTTPException(status_code=502, detail=f"Circle Gateway returned {resp.status_code}: {resp.text[:300]}")
    return resp.json()

def normalize_address(value: Optional[str]) -> str:
    return paid_kit.normalize_address(value)

def paid_report_key(
    payer_address: Optional[str],
    query_hash: Optional[str],
    tier: str = "full",
    provider_id: str = "funding_memory",
) -> str:
    return paid_kit.entitlement_key(payer_address, query_hash, tier, provider_id)

def raw_usdc_to_float(raw_amount: str) -> float:
    return int(raw_amount) / 1_000_000

def fetch_gateway_balance(address: str) -> dict:
    try:
        resp = requests.post(
            f"{ARC_GATEWAY_API}/v1/balances",
            json={
                "token": "USDC",
                "sources": [{"domain": 26, "depositor": address}],
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        return {"address": address, "available_usdc": None, "error": str(exc)}
    if not resp.ok:
        return {
            "address": address,
            "available_usdc": None,
            "error": f"{resp.status_code}: {resp.text[:200]}",
        }
    data = resp.json()
    balance = "0"
    pending = "0"
    balances = data.get("balances") or []
    if balances:
        balance = balances[0].get("balance", "0")
        pending = balances[0].get("pendingBatch", "0")
    return {
        "address": address,
        "available_usdc": float(balance),
        "pending_batch_usdc": float(pending),
        "raw": data,
    }

gateway_balance_cache: Dict[str, dict] = {}

def fetch_gateway_balance_cached(address: str, ttl_seconds: int = 15) -> dict:
    key = normalize_address(address)
    now = time.time()
    cached = gateway_balance_cache.get(key)
    if cached and now - cached.get("at", 0) < ttl_seconds:
        return cached["data"]
    data = fetch_gateway_balance(address)
    gateway_balance_cache[key] = {"at": now, "data": data}
    return data

def paginate_items(items: list, page: int, page_size: int) -> tuple[list, dict]:
    total = len(items)
    page_size = max(1, min(page_size, 100))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }

def payment_event_tier(event: dict) -> str:
    tier = str(event.get("tier") or "").strip().lower()
    if tier in {"preview", "full"}:
        return tier
    return "legacy"

def payment_event_key(event: dict) -> str:
    return str(event.get("settlement_id") or event.get("invoice_id") or event.get("event_id") or "")

def compact_payment_event(event: dict) -> dict:
    tier = payment_event_tier(event)
    return {
        "event_id": event.get("event_id"),
        "invoice_id": event.get("invoice_id"),
        "settlement_id": event.get("settlement_id"),
        "payer_address": event.get("payer_address"),
        "symbol": event.get("symbol"),
        "tier": event.get("tier"),
        "tier_category": tier,
        "provider_id": event.get("provider_id", "funding_memory"),
        "provider_owner_wallet": event.get("provider_owner_wallet"),
        "buyer_type": event.get("buyer_type", "human"),
        "amount_usdc": event.get("amount_usdc"),
        "gateway_status": event.get("gateway_status"),
        "transaction_hash": event.get("transaction_hash"),
        "explorer_url": event.get("explorer_url"),
        "paid_at": event.get("paid_at"),
        "query_hash": event.get("query_hash"),
    }

def attach_report_summaries(events: list, report_summaries: list) -> list:
    by_settlement = {
        item.get("settlement_id"): item
        for item in report_summaries
        if item.get("settlement_id")
    }
    by_query_tier = {
        (item.get("query_hash"), payment_event_tier(item), str(item.get("symbol") or "").upper()): item
        for item in report_summaries
        if item.get("query_hash")
    }
    enriched = []
    for event in events:
        row = compact_payment_event(event)
        summary = by_settlement.get(row.get("settlement_id"))
        if not summary:
            summary = by_query_tier.get((
                row.get("query_hash"),
                payment_event_tier(row),
                str(row.get("symbol") or "").upper(),
            ))
        if summary:
            row["entitlement_id"] = summary.get("entitlement_id")
            row["has_report"] = bool(summary.get("has_report", True))
            row["query_hash"] = row.get("query_hash") or summary.get("query_hash")
        else:
            row["has_report"] = False
        enriched.append(row)
    return enriched

def summarize_payment_events(events: list) -> dict:
    unique_events = {}
    for event in events:
        key = payment_event_key(event)
        if key:
            unique_events[key] = {**unique_events.get(key, {}), **event}
    sorted_events = sorted(unique_events.values(), key=lambda item: item.get("paid_at") or 0, reverse=True)
    unique_payers = {normalize_address(event.get("payer_address")) for event in sorted_events if event.get("payer_address")}
    tier_counts = {"preview": 0, "full": 0, "legacy": 0}
    buyer_type_counts = {"human": 0, "agent": 0}
    revenue_by_tier = {"preview": 0.0, "full": 0.0, "legacy": 0.0}
    revenue_by_provider = {}
    top_symbols = {}
    payer_stats = {}
    for event in sorted_events:
        tier = payment_event_tier(event)
        event["tier_category"] = tier
        amount = float(event.get("amount_usdc") or 0)
        provider_id = event.get("provider_id", "funding_memory")
        buyer_type = event.get("buyer_type", "human")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        buyer_type_counts[buyer_type] = buyer_type_counts.get(buyer_type, 0) + 1
        revenue_by_tier[tier] = revenue_by_tier.get(tier, 0.0) + amount
        provider_stats = revenue_by_provider.setdefault(provider_id, {
            "provider_id": provider_id,
            "owner_wallet": event.get("provider_owner_wallet") or event.get("seller_address"),
            "payments": 0,
            "revenue_usdc": 0.0,
        })
        provider_stats["payments"] += 1
        provider_stats["revenue_usdc"] += amount
        if event.get("symbol"):
            top_symbols[event["symbol"]] = top_symbols.get(event["symbol"], 0) + 1
        payer = normalize_address(event.get("payer_address"))
        if not payer:
            continue
        stats = payer_stats.setdefault(payer, {
            "payer_address": event.get("payer_address"),
            "payments": 0,
            "spent_usdc": 0.0,
            "symbols": set(),
            "preview_count": 0,
            "full_count": 0,
            "last_paid_at": None,
        })
        stats["payments"] += 1
        stats["spent_usdc"] += amount
        if tier == "preview":
            stats["preview_count"] += 1
        elif tier == "full":
            stats["full_count"] += 1
        if event.get("symbol"):
            stats["symbols"].add(event.get("symbol"))
        stats["last_paid_at"] = max(stats["last_paid_at"] or 0, event.get("paid_at") or 0)
    payer_breakdown = []
    for stats in payer_stats.values():
        stats["symbols"] = sorted(stats["symbols"])
        payer_breakdown.append(stats)
    current_paid_count = tier_counts.get("preview", 0) + tier_counts.get("full", 0)
    current_revenue = revenue_by_tier.get("preview", 0.0) + revenue_by_tier.get("full", 0.0)
    revenue = sum(float(event.get("amount_usdc") or 0) for event in sorted_events)
    return {
        "events": sorted_events,
        "paid_count": len(sorted_events),
        "current_paid_count": current_paid_count,
        "legacy_paid_count": tier_counts.get("legacy", 0),
        "unique_payers": len(unique_payers),
        "revenue_usdc": revenue,
        "current_revenue_usdc": current_revenue,
        "legacy_revenue_usdc": revenue_by_tier.get("legacy", 0.0),
        "tier_counts": tier_counts,
        "buyer_type_counts": buyer_type_counts,
        "revenue_by_tier": revenue_by_tier,
        "revenue_by_provider": sorted(
            revenue_by_provider.values(),
            key=lambda item: item["revenue_usdc"],
            reverse=True,
        ),
        "top_symbols": sorted(
            [{"symbol": symbol, "payments": count} for symbol, count in top_symbols.items()],
            key=lambda item: item["payments"],
            reverse=True,
        )[:10],
        "payer_breakdown": sorted(payer_breakdown, key=lambda item: item["spent_usdc"], reverse=True),
        "last_payment_key": payment_event_key(sorted_events[0]) if sorted_events else None,
        "last_paid_at": sorted_events[0].get("paid_at") if sorted_events else None,
    }

def merge_payment_sources(events: list, invoice_events: Optional[list] = None) -> list:
    unique_events = {}
    for event in list(events or []) + list(invoice_events or []):
        key = payment_event_key(event)
        if not key:
            continue
        current = unique_events.get(key, {})
        merged = {**current, **event}
        for field in ("seller_address", "amount_raw", "transaction_hash", "explorer_url", "gateway_status"):
            if current.get(field) and not event.get(field):
                merged[field] = current[field]
        if current.get("gateway_status") in {"completed", "confirmed"} and event.get("gateway_status") not in {"completed", "confirmed"}:
            merged["gateway_status"] = current["gateway_status"]
        unique_events[key] = merged
    return sorted(unique_events.values(), key=lambda item: item.get("paid_at") or 0, reverse=True)

def load_platform_payment_events(limit: int = 5000) -> list:
    events = load_payment_event_summaries(limit=limit)
    invoice_events = load_paid_invoice_events()
    merged = merge_payment_sources(events, invoice_events)
    if merged:
        return merged
    report_events = [
        {
            "event_id": item.get("entitlement_id"),
            "settlement_id": item.get("settlement_id"),
            "payer_address": item.get("payer_address"),
            "symbol": item.get("symbol"),
            "tier": item.get("tier"),
            "provider_id": item.get("provider_id", "funding_memory"),
            "buyer_type": item.get("buyer_type", "human"),
            "amount_usdc": item.get("amount_usdc"),
            "gateway_status": item.get("gateway_status") or "confirmed",
            "transaction_hash": item.get("transaction_hash"),
            "explorer_url": item.get("explorer_url"),
            "paid_at": item.get("paid_at") or item.get("saved_at"),
            "query_hash": item.get("query_hash"),
        }
        for item in load_paid_report_summaries(limit=limit)
    ]
    return merge_payment_sources(report_events)

def parse_iso_utc(value: str) -> float:
    if not value:
        return 0.0
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()

arc_batch_tx_cache = {"at": 0.0, "items": [], "error": None}

def load_arc_gateway_transactions(max_pages: int = 20) -> tuple[list, Optional[str]]:
    now = time.time()
    if now - arc_batch_tx_cache.get("at", 0) < ARC_BATCH_TX_CACHE_TTL_SECONDS:
        return arc_batch_tx_cache.get("items", []), arc_batch_tx_cache.get("error")

    transactions = []
    params = {"filter": "to"}
    error = None
    for _ in range(max(1, max_pages)):
        try:
            resp = requests.get(
                f"{ARC_EXPLORER}/api/v2/addresses/{ARC_GATEWAY_WALLET}/transactions",
                params=params,
                timeout=10,
            )
        except requests.RequestException as exc:
            error = f"Arcscan lookup failed: {exc}"
            break
        if not resp.ok:
            error = f"Arcscan returned {resp.status_code}"
            break
        data = resp.json()
        transactions.extend(data.get("items", []))
        next_params = data.get("next_page_params")
        if not next_params:
            break
        params = {**next_params, "filter": "to"}

    arc_batch_tx_cache.update({"at": now, "items": transactions, "error": error})
    return transactions, error

def find_arc_batch_tx(settlement: dict) -> dict:
    status_value = settlement.get("status")
    if status_value not in {"completed", "confirmed"}:
        return {
            "batch_tx": None,
            "explorer_url": None,
            "status": status_value,
            "message": "Circle accepted the payment authorization; on-chain batch tx is still pending.",
        }

    transactions, error = load_arc_gateway_transactions()
    if error:
        return {
            "batch_tx": None,
            "explorer_url": None,
            "status": status_value,
            "message": error,
        }

    updated_at = settlement.get("updatedAt")
    if not updated_at:
        return {"batch_tx": None, "explorer_url": None, "status": status_value}

    updated_ts = parse_iso_utc(updated_at)

    best_tx = None
    best_delta = None
    for tx in transactions:
        if tx.get("method") != "submitBatch":
            continue
        tx_ts = parse_iso_utc(tx.get("timestamp", ""))
        if not tx_ts:
            continue
        delta = abs(tx_ts - updated_ts)
        if delta <= 1800 and (best_delta is None or delta < best_delta):
            best_tx = tx
            best_delta = delta

    if best_tx:
        tx_hash = best_tx.get("hash")
        return {
            "batch_tx": tx_hash,
            "explorer_url": f"{ARC_EXPLORER}/tx/{tx_hash}" if tx_hash else None,
            "status": status_value,
        }

    return {
        "batch_tx": None,
        "explorer_url": None,
        "status": status_value,
        "message": "Settlement completed, but recent Arcscan index did not expose the matching submitBatch tx yet.",
    }

def refresh_event_batch_tx(event: dict) -> bool:
    """Backfills an existing ledger event with the Arcscan batch tx once Circle finalizes it."""
    if not event.get("settlement_id"):
        return False
    if event.get("transaction_hash") and event.get("explorer_url"):
        return False
    try:
        settlement = fetch_circle_settlement(event["settlement_id"])
        batch = find_arc_batch_tx(settlement)
    except HTTPException:
        return False

    changed = False
    gateway_status = settlement.get("status")
    if gateway_status and gateway_status != event.get("gateway_status"):
        event["gateway_status"] = gateway_status
        changed = True
    if batch.get("batch_tx"):
        event["transaction_hash"] = batch["batch_tx"]
        event["explorer_url"] = batch.get("explorer_url")
        changed = True
    return changed

def refresh_unresolved_payment_events(max_events: int = 20) -> None:
    unresolved = [
        event for event in sorted(payment_events, key=lambda item: item.get("paid_at") or 0, reverse=True)
        if event.get("settlement_id") and not event.get("transaction_hash")
    ][:max_events]
    changed = False
    for event in unresolved:
        changed = refresh_event_batch_tx(event) or changed
    if changed:
        save_payment_ledger(payment_events)

payment_event_refresh_state = {"at": 0.0}

def maybe_refresh_unresolved_payment_events(max_events: int = 8) -> None:
    now = time.time()
    if now - payment_event_refresh_state.get("at", 0) < PAYMENT_EVENT_REFRESH_TTL_SECONDS:
        return
    payment_event_refresh_state["at"] = now
    refresh_unresolved_payment_events(max_events=max_events)

def refresh_invoice_batch_tx(invoice: dict) -> None:
    if not invoice.get("settlement_id") or invoice.get("transaction_hash"):
        return
    temp_event = {
        "settlement_id": invoice.get("settlement_id"),
        "gateway_status": invoice.get("gateway_status"),
        "transaction_hash": invoice.get("transaction_hash"),
        "explorer_url": invoice.get("explorer_url"),
    }
    if refresh_event_batch_tx(temp_event):
        invoice["gateway_status"] = temp_event.get("gateway_status")
        invoice["transaction_hash"] = temp_event.get("transaction_hash")
        invoice["explorer_url"] = temp_event.get("explorer_url")

def validate_arc_payment(invoice: dict, settlement: dict, payer_address: Optional[str] = None) -> None:
    # In strict mode, only allow fully settled batches.
    if REQUIRE_COMPLETED_SETTLEMENT:
        accepted_statuses = {"completed", "confirmed"}
        rejected_msg = (f"Strict mode: QMA_REQUIRE_COMPLETED_SETTLEMENT=true. "
                        f"Settlement status is '{settlement.get('status')}'; "
                        f"wait for Circle to complete the on-chain batch before this report is unlocked.")
    else:
        accepted_statuses = {"received", "batched", "completed", "confirmed"}
        rejected_msg = (f"Settlement status is '{settlement.get('status')}'; "
                        f"payment has not been accepted by Circle yet.")

    if settlement.get("status") not in accepted_statuses:
        raise HTTPException(status_code=402, detail=rejected_msg)

    seller = normalize_address(settlement.get("toAddress"))
    if seller != normalize_address(PAYMENT_WALLET_ADDRESS):
        raise HTTPException(status_code=400, detail="Settlement seller address does not match QMA seller wallet.")

    paid_amount = raw_usdc_to_float(str(settlement.get("amount", "0")))
    expected_amount = float(invoice["amount"])
    if paid_amount + 1e-9 < expected_amount:
        raise HTTPException(status_code=400, detail=f"Settlement amount {paid_amount} USDC is below invoice amount {expected_amount} USDC.")

    if payer_address and normalize_address(settlement.get("fromAddress")) != normalize_address(payer_address):
        raise HTTPException(status_code=400, detail="Settlement payer does not match connected wallet.")

def fetch_json_or_none(url: str, *, params: Optional[dict] = None, timeout: float = 5.0, context: str = "request") -> Optional[dict]:
    try:
        resp = requests.get(url, params=params, headers=MEXC_HEADERS, timeout=timeout)
        content_type = (resp.headers.get("content-type") or "").lower()
        if resp.status_code >= 400:
            logger.warning("MEXC %s returned HTTP %s", context, resp.status_code)
            return None
        if "json" not in content_type and not resp.text.strip().startswith(("{", "[")):
            logger.warning("MEXC %s returned non-JSON content-type=%s", context, content_type or "unknown")
            return None
        return resp.json()
    except requests.Timeout:
        logger.warning("MEXC %s timed out", context)
    except ValueError:
        logger.warning("MEXC %s returned invalid JSON", context)
    except requests.RequestException as exc:
        logger.warning("MEXC %s request failed: %s", context, exc)
    return None


# Live Scanner Helpers
def scan_mexc_live() -> list:
    """Scans MEXC Futures tickers in real-time, using ticker fallbacks if metadata is unavailable."""
    try:
        ticker_resp = fetch_json_or_none(
            "https://futures.mexc.com/api/v1/contract/ticker",
            timeout=5,
            context="ticker scan",
        )
        if not ticker_resp:
            return live_anomalies_cache.get("data", [])
        tickers = ticker_resp.get("data", [])
        if not tickers:
            return live_anomalies_cache.get("data", [])
            
        anomalies = []
        def safe_float(value, default=0.0):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        # Filter for negative funding rate of <= -0.25% to catch signals
        filtered_tickers = [t for t in tickers if safe_float(t.get("fundingRate")) <= -0.0025]
        
        # Sort by most negative funding rate and take top 12 to prevent rate limits
        filtered_tickers = sorted(filtered_tickers, key=lambda x: safe_float(x.get("fundingRate")))[:12]

        for ticker in filtered_tickers:
            raw_symbol = ticker.get("symbol")
            if not raw_symbol:
                continue
            symbol = raw_symbol.replace("_USDT", "")
            contract_id = ticker.get("contractId")
            
            info = {}
            if MEXC_FETCH_CONTRACT_DETAILS and contract_id:
                intro_params = {"language": "vi-VN", "contractId": contract_id}
                intro_resp = fetch_json_or_none(
                    "https://www.mexc.com/api/activity/contract/coin/introduce/v2",
                    params=intro_params,
                    timeout=3,
                    context=f"contract info for {symbol}",
                )
                info = (intro_resp or {}).get("data", {}) if isinstance(intro_resp, dict) else {}

            last_price = safe_float(ticker.get("lastPrice"))
            funding_rate = safe_float(ticker.get("fundingRate"))
            hold_vol = safe_float(ticker.get("holdVol"))
            if last_price <= 0:
                continue

            # Read parameters with safe fallbacks
            volume_24h = safe_float(info.get("volume24h")) if info.get("volume24h") else hold_vol * last_price * 0.2
            circulation = safe_float(info.get("circulationAmount")) if info.get("circulationAmount") else 100000000.0
            issue = safe_float(info.get("issueAmount")) if info.get("issueAmount") else circulation * 1.5

            market_cap = circulation * last_price if circulation else 10000000.0
            fdv = issue * last_price if issue else market_cap * 1.5
            circ_ratio = (circulation / issue) if (circulation and issue) else 0.5

            ath = safe_float(info.get("historicalHigh")) if info.get("historicalHigh") else last_price * 2.0
            from_ath = (last_price / ath - 1) * 100 if ath else -50.0

            # OI amount
            oi = hold_vol * last_price

            anomalies.append({
                "symbol": symbol,
                "fundingRate": funding_rate,
                "price": last_price,
                "marketCap": market_cap,
                "FDV": fdv,
                "circRatio": circ_ratio,
                "fromATH": from_ath,
                "volume24h": volume_24h,
                "openInterest": oi,
                "amount": oi # amount proxy
            })
            
        return anomalies
    except Exception as e:
        logger.error(f"Failed to scan MEXC: {e}")
        return []

# Routes
def serve_html_file(filename: str, fallback: str, status_code: int = 200):
    html_path = os.path.join(os.path.dirname(__file__), filename)
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse(fallback, status_code=status_code)

@app.get("/", response_class=HTMLResponse)
def get_landing():
    """Serves the short Lepton landing page."""
    return serve_html_file("index.html", "<h1>QMA Landing File not found</h1>", status_code=404)

@app.get("/app", response_class=HTMLResponse)
def get_app():
    """Serves the front-end dashboard UI."""
    return serve_html_file("app.html", "<h1>QMA UI File not found</h1>", status_code=404)


@app.get("/user", response_class=HTMLResponse)
def get_user_profile():
    """Serves the wallet profile/history UI."""
    return serve_html_file("user.html", "<h1>QMA User Profile File not found</h1>", status_code=404)

@app.get("/profile", response_class=HTMLResponse)
def get_private_profile():
    """Serves the owner-only wallet profile UI."""
    return serve_html_file("user.html", "<h1>QMA User Profile File not found</h1>", status_code=404)

@app.get("/marketplace", response_class=HTMLResponse)
def get_marketplace():
    """Serves the creator/provider marketplace UI."""
    return serve_html_file("marketplace.html", "<h1>QMA Marketplace File not found</h1>", status_code=404)

@app.get("/api/v1/health")
def get_health():
    return {
        "status": "ok",
        "engine": "ready",
        "storage_backend": storage_backend.backend_name,
        "payment_network": PAYMENT_NETWORK,
        "payment_network_name": PAYMENT_NETWORK_NAME,
    }

@app.get("/api/v1/config")
def get_client_config():
    seller_balance = fetch_gateway_balance_cached(PAYMENT_WALLET_ADDRESS)
    return {
        "status": "ok",
        "engine": "ready",
        "storage_backend": storage_backend.backend_name,
        "dataset": engine.dataset_profile,
        "payment_network": PAYMENT_NETWORK,
        "payment_network_name": PAYMENT_NETWORK_NAME,
        "arc_gateway": ARC_GATEWAY_BASE_URL,
        "arc_gateway_contract": ARC_GATEWAY_WALLET,
        # seller_wallet = the EOA address where USDC eventually lands after batch settlement
        "seller_wallet": PAYMENT_WALLET_ADDRESS,
        # circle_deposit_contract = address buyers actually send funds to (Circle Gateway contract)
        "circle_deposit_contract": ARC_GATEWAY_WALLET,
        "seller_gateway_balance": seller_balance,
        "pricing": paid_kit.pricing_config(),
        "gateway_deposit": {
            "default_usdc": GATEWAY_DEFAULT_DEPOSIT_USDC,
            "default_approve_usdc": GATEWAY_DEFAULT_APPROVE_USDC,
        },
        "providers": [
            provider_metadata(provider_registry.require(provider["provider_id"]))
            for provider in provider_registry.list()
            if provider_control(provider["provider_id"])["enabled"]
        ],
        "require_completed_settlement": REQUIRE_COMPLETED_SETTLEMENT,
    }

@app.get("/api/v1/engine/profile")
def get_engine_profile():
    return {
        "status": "success",
        "dataset": engine.dataset_profile,
        "features": engine.feature_cols,
        "ood_reference": engine.empirical_nn_thresholds,
        "validation_warnings": engine.validation_warnings,
        "clusters": engine.cluster_meta,
    }

def configured_disabled_providers() -> set[str]:
    raw = os.getenv("QMA_DISABLED_PROVIDERS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}

def provider_control(provider_id: str) -> dict:
    provider_id = (provider_id or "").strip()
    env_disabled = provider_id in configured_disabled_providers()
    runtime = provider_runtime_controls.get(provider_id, {})
    enabled = bool(runtime.get("enabled")) if "enabled" in runtime else not env_disabled
    return {
        "enabled": enabled,
        "disabled_by_env": env_disabled,
        "admin_note": runtime.get("admin_note"),
        "updated_at": runtime.get("updated_at"),
    }

def provider_metadata(provider) -> dict:
    metadata = provider.metadata()
    metadata["enabled"] = provider_control(provider.provider_id)["enabled"]
    metadata["control"] = provider_control(provider.provider_id)
    return metadata

def get_provider_or_404(provider_id: str, *, allow_disabled: bool = False):
    try:
        provider = provider_registry.require(provider_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown intelligence provider: {provider_id}")
    if not allow_disabled and not provider_control(provider.provider_id)["enabled"]:
        raise HTTPException(status_code=403, detail=f"Provider is disabled: {provider.provider_id}")
    return provider

def require_admin_token(x_qma_admin_token: Optional[str] = None):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Admin token is not configured.")
    if not hmac.compare_digest(str(x_qma_admin_token or ""), ADMIN_TOKEN):
        raise HTTPException(status_code=403, detail="Admin token required.")
    return True

def has_admin_token(x_qma_admin_token: Optional[str] = None) -> bool:
    return bool(ADMIN_TOKEN) and hmac.compare_digest(str(x_qma_admin_token or ""), ADMIN_TOKEN)

def payment_events_for_provider(provider_id: str) -> list:
    reload_persistent_state(include_reports=False)
    paid_invoices = [
        invoice for invoice in invoices_db.values()
        if invoice.get("status") == "paid"
        and invoice.get("provider_id", "funding_memory") == provider_id
        and invoice.get("settlement_id")
    ]
    events = [
        event for event in payment_events
        if event.get("provider_id", "funding_memory") == provider_id
    ]
    for invoice in paid_invoices:
        if not any(event.get("settlement_id") == invoice.get("settlement_id") for event in events):
            events.append({
                "invoice_id": invoice.get("invoice_id"),
                "symbol": invoice.get("symbol"),
                "provider_id": invoice.get("provider_id", "funding_memory"),
                "provider_owner_wallet": invoice.get("owner_wallet"),
                "buyer_type": invoice.get("buyer_type", "human"),
                "tier": invoice.get("tier", "full"),
                "payer_address": invoice.get("payer_address"),
                "amount_usdc": invoice.get("amount"),
                "settlement_id": invoice.get("settlement_id"),
                "gateway_status": invoice.get("gateway_status"),
                "transaction_hash": invoice.get("transaction_hash"),
                "explorer_url": invoice.get("explorer_url"),
                "paid_at": invoice.get("paid_at"),
            })
    unique = {}
    for event in events:
        key = event.get("settlement_id") or event.get("invoice_id")
        if key:
            unique[key] = {**unique.get(key, {}), **event}
    return sorted(unique.values(), key=lambda item: item.get("paid_at") or 0, reverse=True)

def build_provider_stats(provider_id: str) -> dict:
    provider = get_provider_or_404(provider_id, allow_disabled=True)
    events = payment_events_for_provider(provider_id)
    revenue = sum(float(event.get("amount_usdc") or 0) for event in events)
    share_bps = int(getattr(provider, "revenue_share_bps", 8000))
    tier_counts = {"preview": 0, "full": 0, "legacy": 0}
    buyer_type_counts = {"human": 0, "agent": 0}
    top_symbols = {}
    for event in events:
        tier = payment_event_tier(event)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        buyer_type = event.get("buyer_type", "human")
        buyer_type_counts[buyer_type] = buyer_type_counts.get(buyer_type, 0) + 1
        if event.get("symbol"):
            top_symbols[event["symbol"]] = top_symbols.get(event["symbol"], 0) + 1
    return {
        "provider_id": provider_id,
        "provider_name": provider.provider_name,
        "owner_wallet": provider.owner_wallet,
        "status": getattr(provider, "status", "approved"),
        "payments": len(events),
        "revenue_usdc": round(revenue, 6),
        "creator_share_bps": share_bps,
        "creator_earned_usdc": round(revenue * share_bps / 10000, 6),
        "platform_fee_usdc": round(revenue * (10000 - share_bps) / 10000, 6),
        "tier_counts": tier_counts,
        "buyer_type_counts": buyer_type_counts,
        "top_symbols": sorted(
            [{"symbol": symbol, "payments": count} for symbol, count in top_symbols.items()],
            key=lambda item: item["payments"],
            reverse=True,
        )[:8],
        "recent_payments": events[:10],
    }

@app.get("/api/v1/providers")
def list_providers(
    include_disabled: bool = Query(default=False),
    x_qma_admin_token: Optional[str] = Header(default=None),
):
    """Lists paid intelligence providers available to buyers/agents.

    Disabled manual plugins are hidden by default. Admin UIs can pass
    include_disabled=true to inspect runtime controls without making those
    providers purchasable.
    """
    if include_disabled:
        require_admin_token(x_qma_admin_token)
    providers = []
    for provider in provider_registry.list():
        metadata = provider_metadata(provider_registry.require(provider["provider_id"]))
        if metadata.get("enabled") is False and not include_disabled:
            continue
        providers.append({
            **metadata,
            "stats": build_provider_stats(provider["provider_id"]),
        })
    return {
        "status": "success",
        "providers": providers,
    }

@app.get("/api/v1/providers/{provider_id}")
def get_provider(
    provider_id: str,
    include_disabled: bool = Query(default=False),
    x_qma_admin_token: Optional[str] = Header(default=None),
):
    """Returns provider metadata, pricing, schemas, owner wallet, and supported report types."""
    if include_disabled:
        require_admin_token(x_qma_admin_token)
    return {
        "status": "success",
        "provider": provider_metadata(get_provider_or_404(provider_id, allow_disabled=include_disabled)),
    }

@app.get("/api/v1/providers/{provider_id}/stats")
def get_provider_stats(
    provider_id: str,
    include_disabled: bool = Query(default=False),
    x_qma_admin_token: Optional[str] = Header(default=None),
):
    """Returns creator-facing sales, revenue split, and recent payment stats for one provider."""
    if include_disabled:
        require_admin_token(x_qma_admin_token)
    get_provider_or_404(provider_id, allow_disabled=include_disabled)
    return {
        "status": "success",
        "stats": build_provider_stats(provider_id),
    }

@app.get("/api/v1/admin/public-config")
def get_admin_public_config():
    """Public hints for showing admin/seller controls in the browser. Real writes still require QMA_ADMIN_TOKEN."""
    return {
        "status": "success",
        "seller_wallet": normalize_address(PAYMENT_WALLET_ADDRESS),
        "admin_wallet": normalize_address(ADMIN_WALLET_ADDRESS),
        "admin_token_required": True,
        "admin_token_configured": bool(ADMIN_TOKEN),
    }

@app.post("/api/v1/providers/{provider_id}/toggle")
def toggle_provider_plugin(
    provider_id: str,
    req: ProviderToggleRequest,
    x_qma_admin_token: Optional[str] = Header(default=None),
):
    """Admin-only runtime on/off switch for built-in provider plugins."""
    require_admin_token(x_qma_admin_token)
    provider = get_provider_or_404(provider_id, allow_disabled=True)
    control = {
        "enabled": req.enabled,
        "admin_note": req.admin_note,
        "updated_at": time.time(),
    }
    if not save_provider_control(provider.provider_id, control):
        raise HTTPException(
            status_code=503,
            detail="Provider control storage is not configured. Run the Supabase migration for qma_provider_controls, or use JSON storage locally.",
        )
    provider_runtime_controls[provider.provider_id] = control
    return {
        "status": "success",
        "provider": provider_metadata(provider),
    }

@app.post("/api/v1/creators/apply")
def apply_creator_provider(req: CreatorApplicationRequest):
    """Submits a new creator/provider application for admin review."""
    payload = model_to_dict(req)
    application_id = f"creator_{hashlib.sha256((payload['provider_id'] + payload['creator_wallet'] + str(time.time())).encode()).hexdigest()[:12]}"
    now = time.time()
    application = {
        **payload,
        "application_id": application_id,
        "creator_wallet": normalize_address(payload.get("creator_wallet")),
        "revenue_wallet": normalize_address(payload.get("revenue_wallet") or payload.get("creator_wallet")),
        "status": "pending",
        "runtime_status": "application_only",
        "provider_enabled": False,
        "created_at": now,
        "updated_at": now,
        "reviewed_at": None,
        "admin_note": None,
    }
    creator_applications[application_id] = application
    if not save_creator_application(application):
        raise HTTPException(status_code=503, detail="Creator application storage is not configured. Run the Supabase migration or use JSON storage locally.")
    return {
        "status": "success",
        "message": "Creator provider application submitted for review.",
        "application": application,
    }

@app.get("/api/v1/creators/applications")
def list_creator_applications(
    wallet: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    x_qma_admin_token: Optional[str] = Header(default=None),
):
    """Lists creator applications. Wallet can read its own; admin can read all."""
    reload_persistent_state(include_reports=False)
    is_admin = has_admin_token(x_qma_admin_token)
    if not wallet and not is_admin:
        raise HTTPException(status_code=403, detail="Pass wallet=0x... or admin token.")
    normalized_wallet = normalize_address(wallet)
    records = list(load_creator_applications().values())
    if wallet:
        records = [item for item in records if normalize_address(item.get("creator_wallet")) == normalized_wallet]
    if status_filter:
        records = [item for item in records if item.get("status") == status_filter]
    records = sorted(records, key=lambda item: item.get("created_at") or 0, reverse=True)
    return {
        "status": "success",
        "count": len(records),
        "applications": records[:100],
    }

@app.post("/api/v1/creators/applications/{application_id}/review")
def review_creator_application(
    application_id: str,
    req: CreatorReviewRequest,
    x_qma_admin_token: Optional[str] = Header(default=None),
):
    """Admin review endpoint for marketplace provider applications."""
    require_admin_token(x_qma_admin_token)
    applications = load_creator_applications()
    application = applications.get(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Creator application not found.")
    application["status"] = req.status
    application["runtime_status"] = "approved_needs_plugin" if req.status == "approved" else "application_only"
    application["provider_enabled"] = False
    application["admin_note"] = req.admin_note
    application["reviewed_at"] = time.time()
    application["updated_at"] = application["reviewed_at"]
    creator_applications[application_id] = application
    if not save_creator_application(application):
        raise HTTPException(status_code=503, detail="Creator application storage is not configured.")
    return {
        "status": "success",
        "application": application,
    }

@app.get("/api/v1/metrics")
def get_metrics(
    payment_page: int = Query(default=1, ge=1),
    payment_page_size: int = Query(default=10, ge=1, le=100),
    payer_page: int = Query(default=1, ge=1),
    payer_page_size: int = Query(default=10, ge=1, le=100),
):
    events = load_platform_payment_events()
    summary = summarize_payment_events(events)
    recent_payments, recent_payments_page = paginate_items(events, payment_page, payment_page_size)
    payer_breakdown_page_items, payer_breakdown_page = paginate_items(summary["payer_breakdown"], payer_page, payer_page_size)
    seller_balance = fetch_gateway_balance_cached(PAYMENT_WALLET_ADDRESS)
    return {
        "seller_address": PAYMENT_WALLET_ADDRESS,
        "seller_gateway_balance": seller_balance,
        "invoice_count": len(invoices_db),
        "paid_count": summary["paid_count"],
        "current_paid_count": summary["current_paid_count"],
        "legacy_paid_count": summary["legacy_paid_count"],
        "unique_payers": summary["unique_payers"],
        "revenue_usdc": summary["revenue_usdc"],
        "current_revenue_usdc": summary["current_revenue_usdc"],
        "legacy_revenue_usdc": summary["legacy_revenue_usdc"],
        "tier_counts": summary["tier_counts"],
        "buyer_type_counts": summary["buyer_type_counts"],
        "revenue_by_tier": summary["revenue_by_tier"],
        "revenue_by_provider": summary["revenue_by_provider"],
        "top_symbols": summary["top_symbols"],
        "last_payment_key": summary["last_payment_key"],
        "last_paid_at": summary["last_paid_at"],
        "payer_breakdown": payer_breakdown_page_items,
        "payer_breakdown_page": payer_breakdown_page,
        "recent_payments": recent_payments,
        "recent_payments_page": recent_payments_page,
    }

@app.get("/api/v1/platform/summary")
def get_platform_summary():
    maybe_refresh_unresolved_payment_events()
    events = load_platform_payment_events()
    summary = summarize_payment_events(events)
    return {
        "seller_address": PAYMENT_WALLET_ADDRESS,
        "seller_gateway_balance": fetch_gateway_balance_cached(PAYMENT_WALLET_ADDRESS),
        "invoice_count": len(invoices_db),
        "paid_count": summary["paid_count"],
        "current_paid_count": summary["current_paid_count"],
        "legacy_paid_count": summary["legacy_paid_count"],
        "unique_payers": summary["unique_payers"],
        "revenue_usdc": summary["revenue_usdc"],
        "current_revenue_usdc": summary["current_revenue_usdc"],
        "legacy_revenue_usdc": summary["legacy_revenue_usdc"],
        "tier_counts": summary["tier_counts"],
        "buyer_type_counts": summary["buyer_type_counts"],
        "revenue_by_tier": summary["revenue_by_tier"],
        "top_symbols": summary["top_symbols"],
        "last_payment_key": summary["last_payment_key"],
        "last_paid_at": summary["last_paid_at"],
    }

@app.get("/api/v1/platform/payments")
def get_platform_payments(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    events = load_platform_payment_events()
    page_items, meta = paginate_items(events, page, page_size)
    return {
        "recent_payments": [compact_payment_event(event) for event in page_items],
        "recent_payments_page": meta,
    }

@app.get("/api/v1/platform/payers")
def get_platform_payers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
):
    events = load_platform_payment_events()
    summary = summarize_payment_events(events)
    items, meta = paginate_items(summary["payer_breakdown"], page, page_size)
    return {
        "payer_breakdown": items,
        "payer_breakdown_page": meta,
    }

@app.get("/api/v1/metrics/wallet/{address}")
def get_wallet_metrics(
    address: str,
    payment_page: int = Query(default=1, ge=1),
    payment_page_size: int = Query(default=10, ge=1, le=100),
    entitlement_page: int = Query(default=1, ge=1),
    entitlement_page_size: int = Query(default=50, ge=1, le=100),
    qma_wallet_token: Optional[str] = Header(default=None, alias="X-QMA-Wallet-Token"),
    wallet_token: Optional[str] = Query(default=None),
):
    events = load_payment_events_for_wallet(address)
    paid_invoices = list(load_paid_invoices_for_wallet(address).values())
    for invoice in paid_invoices:
        if not any(event.get("settlement_id") == invoice.get("settlement_id") for event in events):
            events.append({
                "invoice_id": invoice.get("invoice_id"),
                "symbol": invoice.get("symbol"),
                "provider_id": invoice.get("provider_id", "funding_memory"),
                "provider_owner_wallet": invoice.get("owner_wallet"),
                "buyer_type": invoice.get("buyer_type", "human"),
                "tier": invoice.get("tier", "full"),
                "resource_type": invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
                "payer_address": invoice.get("payer_address"),
                "seller_address": PAYMENT_WALLET_ADDRESS,
                "amount_usdc": invoice.get("amount"),
                "amount_raw": invoice.get("amount_raw"),
                "settlement_id": invoice.get("settlement_id"),
                "gateway_status": invoice.get("gateway_status"),
                "transaction_hash": invoice.get("transaction_hash"),
                "explorer_url": invoice.get("explorer_url"),
                "paid_at": invoice.get("paid_at"),
            })
    events = sorted(events, key=lambda item: item.get("paid_at") or 0, reverse=True)
    spent = sum(float(event.get("amount_usdc") or 0) for event in events)
    purchased_symbols = sorted({event.get("symbol") for event in events if event.get("symbol")})
    tier_counts = {"preview": 0, "full": 0, "legacy": 0}
    buyer_type_counts = {"human": 0, "agent": 0}
    provider_counts = {}
    for event in events:
        tier = payment_event_tier(event)
        event["tier_category"] = tier
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        buyer_type = event.get("buyer_type", "human")
        buyer_type_counts[buyer_type] = buyer_type_counts.get(buyer_type, 0) + 1
        provider_id = event.get("provider_id", "funding_memory")
        provider_counts[provider_id] = provider_counts.get(provider_id, 0) + 1
    wallet_reports = load_paid_reports_for_wallet(address)
    entitlements = paid_kit.list_wallet_entitlements(wallet_reports, address)
    token = qma_wallet_token or wallet_token
    if token:
        verify_wallet_profile_token(address, token)
    else:
        entitlements = [public_entitlement_row(record) for record in entitlements]
    recent_payments, recent_payments_page = paginate_items(events, payment_page, payment_page_size)
    entitlement_items, entitlements_page = paginate_items(entitlements, entitlement_page, entitlement_page_size)
    return {
        "address": address,
        "access": "private" if token else "public",
        "gateway_balance": fetch_gateway_balance(address),
        "payments": len(events),
        "current_payments": tier_counts.get("preview", 0) + tier_counts.get("full", 0),
        "legacy_payments": tier_counts.get("legacy", 0),
        "spent_usdc": spent,
        "tier_counts": tier_counts,
        "buyer_type_counts": buyer_type_counts,
        "provider_counts": provider_counts,
        "purchased_symbols": purchased_symbols,
        "entitlements": entitlement_items,
        "entitlements_page": entitlements_page,
        "recent_payments": recent_payments,
        "recent_payments_page": recent_payments_page,
    }

def wallet_events_with_invoice_fallback(address: str) -> list:
    events = load_payment_events_for_wallet(address)
    paid_invoices = list(load_paid_invoices_for_wallet(address).values())
    existing_keys = {payment_event_key(event) for event in events}
    for invoice in paid_invoices:
        key = str(invoice.get("settlement_id") or invoice.get("invoice_id") or "")
        if key and key not in existing_keys:
            events.append({
                "invoice_id": invoice.get("invoice_id"),
                "symbol": invoice.get("symbol"),
                "provider_id": invoice.get("provider_id", "funding_memory"),
                "provider_owner_wallet": invoice.get("owner_wallet"),
                "buyer_type": invoice.get("buyer_type", "human"),
                "tier": invoice.get("tier", "full"),
                "resource_type": invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
                "payer_address": invoice.get("payer_address"),
                "seller_address": PAYMENT_WALLET_ADDRESS,
                "amount_usdc": invoice.get("amount"),
                "amount_raw": invoice.get("amount_raw"),
                "settlement_id": invoice.get("settlement_id"),
                "gateway_status": invoice.get("gateway_status"),
                "transaction_hash": invoice.get("transaction_hash"),
                "explorer_url": invoice.get("explorer_url"),
                "paid_at": invoice.get("paid_at"),
                "query_hash": invoice.get("query_hash"),
            })
            existing_keys.add(key)
    for report in load_paid_report_summaries_for_wallet(address):
        key = str(report.get("settlement_id") or report.get("entitlement_id") or report.get("query_hash") or "")
        if key and key not in existing_keys:
            events.append({
                "event_id": report.get("entitlement_id"),
                "settlement_id": report.get("settlement_id"),
                "payer_address": report.get("payer_address"),
                "symbol": report.get("symbol"),
                "tier": report.get("tier"),
                "provider_id": report.get("provider_id", "funding_memory"),
                "buyer_type": report.get("buyer_type", "human"),
                "amount_usdc": report.get("amount_usdc"),
                "gateway_status": report.get("gateway_status") or "confirmed",
                "transaction_hash": report.get("transaction_hash"),
                "explorer_url": report.get("explorer_url"),
                "paid_at": report.get("paid_at") or report.get("saved_at"),
                "query_hash": report.get("query_hash"),
            })
            existing_keys.add(key)
    return sorted(events, key=lambda item: item.get("paid_at") or 0, reverse=True)

@app.get("/api/v1/wallets/{address}/summary")
def get_wallet_summary(address: str):
    maybe_refresh_unresolved_payment_events()
    events = wallet_events_with_invoice_fallback(address)
    summary = summarize_payment_events(events)
    purchased_symbols = sorted({event.get("symbol") for event in events if event.get("symbol")})
    provider_counts = {}
    for event in events:
        provider_id = event.get("provider_id", "funding_memory")
        provider_counts[provider_id] = provider_counts.get(provider_id, 0) + 1
    return {
        "address": address,
        "gateway_balance": fetch_gateway_balance_cached(address),
        "payments": summary["paid_count"],
        "current_payments": summary["current_paid_count"],
        "legacy_payments": summary["legacy_paid_count"],
        "spent_usdc": summary["revenue_usdc"],
        "tier_counts": summary["tier_counts"],
        "buyer_type_counts": summary["buyer_type_counts"],
        "provider_counts": provider_counts,
        "purchased_symbols": purchased_symbols,
        "last_payment_key": summary["last_payment_key"],
        "last_paid_at": summary["last_paid_at"],
    }

@app.get("/api/v1/wallets/{address}/payments")
def get_wallet_payments(
    address: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    qma_wallet_token: Optional[str] = Header(default=None, alias="X-QMA-Wallet-Token"),
    wallet_token: Optional[str] = Query(default=None),
):
    events = wallet_events_with_invoice_fallback(address)
    token = qma_wallet_token or wallet_token
    if token:
        verify_wallet_profile_token(address, token)
        report_summaries = load_paid_report_summaries_for_wallet(address)
        rows = attach_report_summaries(events, report_summaries)
    else:
        rows = [public_payment_row(compact_payment_event(event)) for event in events]
    page_items, meta = paginate_items(rows, page, page_size)
    return {
        "address": address,
        "access": "private" if token else "public",
        "recent_payments": page_items,
        "recent_payments_page": meta,
    }

@app.post("/api/v1/wallets/{address}/session")
def create_wallet_profile_session(address: str, payload: WalletProfileSessionRequest):
    token_payload = wallet_profile_token_payload(address, payload)
    return {
        "address": paid_kit.normalize_address(address),
        "wallet_token": paid_kit.sign_access_token(
            token_payload,
            secret=ACCESS_TOKEN_SECRET,
            ttl_seconds=WALLET_PROFILE_TOKEN_TTL_SECONDS,
        ),
        "expires_in": WALLET_PROFILE_TOKEN_TTL_SECONDS,
        "message": wallet_profile_message(address, payload.nonce, payload.issued_at),
    }

@app.get("/api/v1/wallets/{address}/reports/{entitlement_id}")
def get_wallet_report_detail(
    address: str,
    entitlement_id: str,
    qma_wallet_token: Optional[str] = Header(default=None, alias="X-QMA-Wallet-Token"),
    wallet_token: Optional[str] = Query(default=None),
):
    verify_wallet_profile_token(address, qma_wallet_token or wallet_token or "")
    record = load_paid_report_by_id(address, entitlement_id)
    if not record:
        raise HTTPException(status_code=404, detail="Paid report snapshot not found for this wallet.")
    return {
        "address": address,
        "entitlement": record,
    }

@app.get("/api/v1/entitlements/wallet/{address}")
def get_wallet_entitlements(
    address: str,
    symbol: Optional[str] = Query(default=None),
    provider_id: Optional[str] = Query(default=None),
    qma_wallet_token: Optional[str] = Header(default=None, alias="X-QMA-Wallet-Token"),
    wallet_token: Optional[str] = Query(default=None),
):
    wallet_reports = load_paid_reports_for_wallet(address, symbol=symbol, provider_id=provider_id)
    records = paid_kit.list_wallet_entitlements(wallet_reports, address, symbol=symbol, provider_id=provider_id)
    token = qma_wallet_token or wallet_token
    if token:
        verify_wallet_profile_token(address, token)
    else:
        records = [public_entitlement_row(record) for record in records]
    return {
        "address": address,
        "symbol": symbol,
        "provider_id": provider_id,
        "count": len(records),
        "access": "private" if token else "public",
        "entitlements": records[:100],
    }

@app.get("/api/v1/live-anomalies")
def get_live_anomalies():
    """Returns real-time MEXC funding anomalies with caching"""
    now = time.time()
    if now - live_anomalies_cache["last_updated"] > CACHE_TTL_SECONDS:
        with live_scan_lock:
            now = time.time()
            if now - live_anomalies_cache["last_updated"] > CACHE_TTL_SECONDS:
                logger.info("Cache expired. Scanning MEXC live...")
                live_anomalies_cache["data"] = scan_mexc_live()
                live_anomalies_cache["last_updated"] = time.time()
    else:
        logger.info("Serving live anomalies from cache.")
        
    return {
        "status": "success",
        "last_updated": live_anomalies_cache["last_updated"],
        "count": len(live_anomalies_cache["data"]),
        "anomalies": live_anomalies_cache["data"]
    }

@app.get("/api/v1/agent/recommendations")
def get_agent_recommendations(limit: int = Query(default=8, ge=1, le=25)):
    """Ranks live anomalies as user-confirmed paid report candidates."""
    live = get_live_anomalies()
    anomalies = live.get("anomalies", [])
    picks = []
    enabled_providers = [
        provider_registry.require(item["provider_id"])
        for item in provider_registry.list()
        if provider_control(item["provider_id"])["enabled"]
    ]
    for item in anomalies:
        funding_pct = abs(float(item.get("fundingRate") or 0) * 100)
        volume = float(item.get("volume24h") or 0)
        market_cap = max(float(item.get("marketCap") or 0), 1)
        circ = float(item.get("circRatio") or 0)
        ath = abs(float(item.get("fromATH") or 0))
        query_payload = canonical_query_payload(item)
        for provider in enabled_providers:
            turnover_pct = (volume / market_cap) * 100
            structure_score = min(20.0, max(0.0, 1.0 - abs(circ - 0.65)) * 20)
            discount_score = min(10.0, ath / 10)
            reasons = []
            if provider.provider_id == "oi_memory":
                turnover_score = min(55.0, turnover_pct * 8)
                funding_score = min(15.0, funding_pct * 6)
                score = round(min(100.0, turnover_score + funding_score + structure_score + discount_score), 1)
                if turnover_pct >= 8:
                    reasons.append("very high turnover / OI proxy")
                elif turnover_pct >= 3:
                    reasons.append("elevated turnover / OI proxy")
                elif turnover_pct >= 1:
                    reasons.append("usable turnover context")
                if funding_pct >= 0.25:
                    reasons.append("funding used as secondary context")
            else:
                volume_score = min(25.0, turnover_pct)
                funding_score = min(45.0, funding_pct * 18)
                score = round(min(100.0, funding_score + volume_score + structure_score + discount_score), 1)
                if funding_pct >= 0.5:
                    reasons.append("extreme negative funding")
                elif funding_pct >= 0.25:
                    reasons.append("notable funding anomaly")
                if turnover_pct >= 2:
                    reasons.append("meaningful turnover")
            if 0.2 <= circ <= 1.0:
                reasons.append("usable circulating supply profile")
            if ath >= 50:
                reasons.append("deep drawdown context")
            suggested_tier = "full" if score >= 65 else "preview"
            quote = provider.quote_price(query_payload, suggested_tier)
            picks.append({
                "provider_id": provider.provider_id,
                "provider_name": provider.provider_name,
                "provider_category": provider.category,
                "symbol": item.get("symbol"),
                "score": score,
                "suggested_tier": suggested_tier,
                "suggested_price_usdc": quote["amount_usdc"],
                "complexity_score": quote["complexity_score"],
                "estimated_value": "High" if score >= 70 else "Medium" if score >= 45 else "Exploratory",
                "reasons": reasons[:4] or ["fresh live anomaly"],
                "query": query_payload,
                "live": item,
            })
    picks = sorted(picks, key=lambda item: item["score"], reverse=True)[:limit]
    return {
        "status": "success",
        "mode": "suggest_then_pay",
        "provider_strategy": "single_provider_invoice",
        "pricing": paid_kit.pricing_config(),
        "last_updated": live.get("last_updated"),
        "recommendations": picks,
    }

@app.post("/api/v1/payment/quote")
def quote_payment(req: QuoteRequest):
    """Returns the complexity-adjusted USDC price for an exact signal snapshot."""
    req_data = model_to_dict(req)
    provider_id = req_data.pop("provider_id", "funding_memory")
    tier = paid_kit.normalize_tier(req_data.pop("tier", "full"))
    provider = get_provider_or_404(provider_id)
    quote = provider.quote_price(req_data, tier)
    return {
        "status": "success",
        "pricing": paid_kit.pricing_config(),
        **quote,
    }

@app.post("/api/v1/payment/invoice")
def create_invoice(req: InvoiceRequest):
    """Creates a QMA invoice bound to a Circle x402 Arc Testnet payment."""
    req_data = model_to_dict(req)
    provider_id = req_data.pop("provider_id", "funding_memory")
    buyer_type = req_data.pop("buyer_type", "human")
    tier = paid_kit.normalize_tier(req_data.pop("tier", "full"))
    resource_type = req_data.pop("resource_type", PAYMENT_RESOURCE_TYPE) or PAYMENT_RESOURCE_TYPE
    provider = get_provider_or_404(provider_id)
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
    )
    invoices_db[invoice["invoice_id"]] = invoice
    save_invoice(invoice)
    return {
        "invoice_id": invoice["invoice_id"],
        "amount": invoice["amount"],
        "currency": "USDC",
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
        "provider_owner_wallet": invoice["owner_wallet"],
        "expires_at": invoice["expires_at"],
        "nonce": invoice["nonce"],
        "invoice_secret": invoice["invoice_secret"],
        "query_hash": invoice["query_hash"],
        "payment_requirement": requirement,
        "arc_gateway_url": requirement["resource"],
    }

@app.post("/api/v1/payment/verify")
def verify_payment(invoice_id: str = Query(...), proof: Optional[PaymentVerifyRequest] = None):
    """Verifies a real Circle Gateway x402 settlement on Arc Testnet."""
    if proof is None:
        raise HTTPException(status_code=400, detail="settlement_id is required.")
    invoice = get_invoice_or_402(invoice_id)
    if not hmac.compare_digest(str(proof.invoice_secret), str(invoice.get("invoice_secret"))):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invoice secret mismatch.")
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
    save_invoice(invoice)

    reload_persistent_state(include_reports=False)
    if not any(event.get("settlement_id") == proof.settlement_id for event in payment_events):
        payment_events.append({
            "invoice_id": invoice_id,
            "symbol": invoice.get("symbol"),
            "provider_id": invoice.get("provider_id", "funding_memory"),
            "provider_owner_wallet": invoice.get("owner_wallet"),
            "buyer_type": invoice.get("buyer_type", "human"),
            "tier": invoice.get("tier", "full"),
            "resource_type": invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
            "query": invoice.get("query"),
            "query_hash": invoice.get("query_hash"),
            "payer_address": invoice.get("payer_address"),
            "seller_address": PAYMENT_WALLET_ADDRESS,
            "amount_usdc": invoice.get("amount"),
            "amount_raw": invoice.get("amount_raw"),
            "settlement_id": invoice.get("settlement_id"),
            "gateway_status": invoice.get("gateway_status"),
            "transaction_hash": invoice.get("transaction_hash"),
            "explorer_url": invoice.get("explorer_url"),
            "paid_at": invoice.get("paid_at"),
        })
        save_payment_ledger(payment_events)
        save_invoice(invoice)

    # Fetch seller gateway balance breakdown so UI can display where funds are
    seller_balance = fetch_gateway_balance(PAYMENT_WALLET_ADDRESS)
    access_token = sign_access_token({
        "invoice_id": invoice_id,
        "settlement_id": invoice.get("settlement_id"),
        "payer_address": normalize_address(invoice.get("payer_address")),
        "symbol": invoice.get("symbol"),
        "query_hash": invoice.get("query_hash"),
        "provider_id": invoice.get("provider_id", "funding_memory"),
        "buyer_type": invoice.get("buyer_type", "human"),
        "tier": invoice.get("tier", "full"),
        "resource_type": invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
        "amount": invoice.get("amount"),
    })
    return {
        "invoice_id": invoice_id,
        "status": invoice["status"],
        # gateway_status: received = Circle accepted signature; completed = on-chain batch finalised
        "gateway_status": invoice["gateway_status"],
        "settlement_id": invoice["settlement_id"],
        "payer_address": invoice["payer_address"],
        "provider_id": invoice.get("provider_id", "funding_memory"),
        "buyer_type": invoice.get("buyer_type", "human"),
        "tier": invoice.get("tier", "full"),
        "tier_label": paid_kit.SUPPORTED_TIERS[paid_kit.normalize_tier(invoice.get("tier", "full"))]["label"],
        "resource_type": invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
        "provider_owner_wallet": invoice.get("owner_wallet"),
        # seller_wallet: EOA that will receive USDC after batch. NOT the deposit address.
        "seller_wallet": PAYMENT_WALLET_ADDRESS,
        # circle_deposit_contract: address buyers deposit to / Circle Gateway contract
        "circle_deposit_contract": ARC_GATEWAY_WALLET,
        "seller_gateway_available_usdc": seller_balance.get("available_usdc"),
        "seller_gateway_pending_batch_usdc": seller_balance.get("pending_batch_usdc"),
        "transaction_hash": invoice.get("transaction_hash"),
        "explorer_url": invoice.get("explorer_url"),
        "verification_mode": invoice["verification_mode"],
        "access_token": access_token,
        "access_token_expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "require_completed_settlement": REQUIRE_COMPLETED_SETTLEMENT,
        "message": (
            "Circle Gateway settlement verified and on-chain batch confirmed."
            if invoice["gateway_status"] in {"completed", "confirmed"}
            else "Circle accepted payment authorization. On-chain batch settlement is pending — report access is already granted."
        ),
    }

@app.get("/api/v1/payment/settlement/{settlement_id}")
def get_payment_settlement(settlement_id: str):
    settlement = fetch_circle_settlement(settlement_id)
    batch = find_arc_batch_tx(settlement)
    return {
        "settlement": settlement,
        "batch": batch,
    }

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    invoice_id: str
    message: str
    history: Optional[List[ChatMessage]] = Field(default_factory=list)

@app.post("/api/v1/chat")
def handle_chat_request(payload: ChatRequest):
    """Answers interactive user queries regarding a paid report, using OpenAI if available or fallback heuristic."""
    invoice_id = payload.invoice_id
    user_message = payload.message
    history = payload.history or []

    reload_persistent_state()
    
    invoice = invoices_db.get(invoice_id)
    report_record = None
    
    if invoice:
        settlement_id = invoice.get("settlement_id")
        for record in paid_reports.values():
            rec_report = record.get("report") or {}
            rec_inv = rec_report.get("invoice") or {}
            if rec_inv.get("invoice_id") == invoice_id or (settlement_id and record.get("settlement_id") == settlement_id):
                report_record = record
                break
    else:
        for record in paid_reports.values():
            rec_report = record.get("report") or {}
            rec_inv = rec_report.get("invoice") or {}
            if rec_inv.get("invoice_id") == invoice_id:
                report_record = record
                invoice = rec_inv
                break

    if not invoice or invoice.get("status") != "paid":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="A valid, paid invoice is required to use AI Chat."
        )

    if not report_record or not report_record.get("report"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report data not found for this invoice. Settle and retrieve the report first."
        )

    report = report_record["report"]
    symbol = report.get("query_symbol") or report.get("query", {}).get("symbol") or "this asset"
    tier = report.get("tier", "full")
    regime_cluster = report.get("regime_cluster", "Unknown")
    regime_description = report.get("regime_description", "No description available.")
    
    win_rate = report.get("weighted_win_rate") or report.get("rough_win_rate") or 0.0
    avg_profit = report.get("weighted_avg_profit") or report.get("rough_avg_profit") or 0.0
    
    ci_win = report.get("ci_win_rate_95") or [0.0, 0.0]
    ci_profit = report.get("ci_avg_profit_95") or [0.0, 0.0]
    
    ci_win_str = f"[{ci_win[0]:.1f}% - {ci_win[1]:.1f}%]"
    ci_profit_str = f"[{ci_profit[0]:.2f}% - {ci_profit[1]:.2f}%]"
    
    perc = report.get("percentiles") or {}
    p10 = perc.get("P10", 0.0)
    p25 = perc.get("P25", 0.0)
    p50 = perc.get("P50_median", 0.0)
    p75 = perc.get("P75", 0.0)
    p90 = perc.get("P90", 0.0)
    worst = perc.get("worst_case_max_loss") or report.get("worst_case_max_loss") or 0.0
    
    is_ood = report.get("is_ood", False)
    ood_p = report.get("ood_p_value", 1.0)
    novelty_status = "High Novelty (Out-of-Distribution)" if is_ood else "Familiar Pattern (In-Distribution)"
    
    analogs = report.get("analogs") or report.get("top_analogs") or []
    analogs_list = ", ".join([a.get("symbol", "") for a in analogs[:4] if a.get("symbol")])
    if not analogs_list:
        analogs_list = "None"
        
    warnings = report.get("validation_warnings") or []
    risk_flags = report.get("risk_flags") or []

    # Heuristic report explainer
    msg_lower = user_message.lower()
    
    if any(k in msg_lower for k in ["risk", "loss", "drawdown", "worst", "danger", "safe", "liquidat", "warning"]):
        warnings_str = "\n".join([f"- {w}" for w in (warnings + risk_flags)])
        if not warnings_str:
            warnings_str = "- No critical statistical anomalies flagged."
        answer = f"""Regarding the risk profile for {symbol}, our backtest of the **{regime_cluster}** shows a historical worst-case maximum loss of **{worst * 100:.1f}%** (or P10 outcome of **{p10:.1f}%**) among the closest historical analogs.

Additionally, our validation pipeline flagged these diagnostics:
{warnings_str}

In this regime, anomalous negative funding rates can mean-revert violently or persist if the asset has structural sell pressure. We advise keeping position sizes conservative and using strict stop-losses. Past performance does not guarantee future results."""

    elif any(k in msg_lower for k in ["win", "rate", "percent", "probability", "chance", "profit", "earn", "return"]):
        answer = f"""The historical win rate of **{win_rate:.1f}%** is calculated across **{len(analogs)}** similar historical events, weighted by similarity score and time-decay. This indicates that situations matching {symbol}'s current parameters (funding rate, market cap, and volume) had a high frequency of positive outcomes in our backtest window.

Specifically, the 95% confidence interval for the win rate is **{ci_win_str}**, with a median outcome of **{p50:.1f}%** and an average peak profit of **{avg_profit:.2f}%** (CI: {ci_profit_str}). However, outlier outcomes are common in high-novelty situations. Past performance does not guarantee future results."""

    elif any(k in msg_lower for k in ["regime", "cluster", "context", "market", "situation", "analog", "similar"]):
        answer = f"""The asset {symbol} currently falls under the **{regime_cluster}** cluster. This regime is described as: *{regime_description}*.

The novelty check shows a p-value of **{ood_p:.5f}**, classifying this signal as a **{novelty_status}**. The closest historical analogs matched in this regime include: **{analogs_list}**. Past performance does not guarantee future results."""

    else:
        answer = f"""Here is a quantitative executive summary for the {symbol} anomaly report:
- **Market Regime:** {regime_cluster} ({novelty_status})
- **Backtest Win Rate:** {win_rate:.1f}% ({ci_win_str} 95% CI)
- **Average Peak Outcome:** {avg_profit:+.2f}% (95% CI: {ci_profit_str})
- **Top Historical Analogs:** {analogs_list}

Feel free to ask me details about:
1. What are the main **risks and warnings** for this anomaly?
2. How is the **win rate** and percentiles computed?
3. What are the **closest historical analogs** matched?

Past performance does not guarantee future results."""

    return {"answer": answer, "engine": "heuristic"}

@app.post("/api/v1/payment/withdraw")
def submit_withdraw(payload: dict):
    """Submits a signed BurnIntent authorization to Circle Gateway for withdrawal."""
    burn_intent = payload.get("burnIntent")
    signature = payload.get("signature")
    if not burn_intent or not signature:
        raise HTTPException(status_code=400, detail="burnIntent and signature are required")

    try:
        resp = requests.post(
            f"{ARC_GATEWAY_API}/v1/transfer",
            json=[{
                "burnIntent": burn_intent,
                "signature": signature
            }],
            timeout=15
        )
        if resp.ok:
            data = resp.json()
            if data.get("success") is False or data.get("error") or not data.get("attestation") or not data.get("signature"):
                raise HTTPException(
                    status_code=502,
                    detail=f"Circle Gateway did not return a mint attestation: {json.dumps(data)[:300]}",
                )
            return data
        raise HTTPException(
            status_code=502,
            detail=f"Circle Gateway transfer API returned {resp.status_code}: {resp.text[:300]}",
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        logger.warning(f"Circle transfer API failed: {exc}.")
        raise HTTPException(status_code=502, detail=f"Circle Gateway transfer API failed: {exc}")

def authorize_paid_invoice(
    *,
    query: QueryModel,
    invoice_id: str,
    token: Optional[str],
    required_tier: str,
    provider_id: str = "funding_memory",
) -> dict:
    invoice = get_invoice_or_402(invoice_id)
    if invoice.get("provider_id", "funding_memory") != provider_id:
        raise HTTPException(status_code=400, detail="Invoice provider does not match requested provider.")
    if invoice["status"] != "paid":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "payment_not_settled",
                "message": f"Invoice is {invoice['status']}. Complete the USDC payment before analysis.",
                "payment": payment_requirement(
                    invoice_id=invoice_id,
                    symbol=invoice["symbol"],
                    amount_usdc=invoice.get("amount"),
                    tier=invoice.get("tier", required_tier),
                    resource_type=invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
                    provider_id=invoice.get("provider_id", provider_id),
                ),
            },
        )
    if invoice["symbol"].upper() != query.symbol.upper():
        raise HTTPException(status_code=400, detail="Invoice symbol does not match query symbol.")
    current_query_hash = query_fingerprint(model_to_dict(query))
    if invoice.get("query_hash") != current_query_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Paid invoice is bound to a different query snapshot. Create a fresh invoice for changed signal data.",
        )
    token_payload = verify_access_token(token or "")
    try:
        paid_kit.require_access(token_payload, invoice, required_tier=required_tier)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return invoice

def build_preview_report(full_report: dict, invoice: dict) -> dict:
    analogs = full_report.get("analogs", [])[:3]
    win_rate = float(full_report.get("weighted_win_rate") or 0)
    if win_rate >= 70:
        win_rate_band = "high"
    elif win_rate >= 50:
        win_rate_band = "medium"
    else:
        win_rate_band = "low"
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
            {
                "symbol": item.get("symbol"),
                "fundingRate": item.get("fundingRate"),
                "similarity": item.get("similarity"),
                "profit_pct": item.get("profit_pct"),
            }
            for item in analogs
        ],
        "upgrade_cta": "Upgrade to the full report for all analogs, weighted percentiles, confidence intervals, and evidence diagnostics.",
        "invoice": full_report.get("invoice"),
    }

def invoice_report_meta(invoice_id: str, invoice: dict) -> dict:
    return {
        "invoice_id": invoice_id,
        "status": "paid",
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
        "network": invoice.get("network"),
        "verification_mode": invoice.get("verification_mode"),
    }

def run_paid_provider_report(
    *,
    provider_id: str,
    query: QueryModel,
    invoice_id: str,
    token: Optional[str],
    required_tier: str,
) -> dict:
    provider = get_provider_or_404(provider_id)
    invoice = authorize_paid_invoice(
        query=query,
        invoice_id=invoice_id,
        token=token,
        required_tier=required_tier,
        provider_id=provider.provider_id,
    )
    refresh_invoice_batch_tx(invoice)
    full_report = provider.full_report(model_to_dict(query))
    full_report["query"] = invoice.get("query") or canonical_query_payload(model_to_dict(query))
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
    save_invoice(invoice)
    paid_kit.record_entitlement(paid_reports, invoice=invoice, report=jsonable_encoder(report))
    save_paid_reports(paid_reports)
    return report

@app.post("/api/v1/providers/{provider_id}/preview")
def provider_preview_signal(
    provider_id: str,
    query: QueryModel,
    invoice_id: str = Query(...),
    qma_access_token: Optional[str] = Header(default=None, alias="X-QMA-Access-Token"),
    access_token: Optional[str] = Query(default=None),
):
    """Returns a paid provider preview for the exact query snapshot bound to the invoice."""
    try:
        return run_paid_provider_report(
            provider_id=provider_id,
            query=query,
            invoice_id=invoice_id,
            token=qma_access_token or access_token,
            required_tier="preview",
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error running provider preview: {e}")
        raise HTTPException(status_code=500, detail=f"Provider preview failure: {str(e)}")

@app.post("/api/v1/providers/{provider_id}/full-report")
def provider_full_report(
    provider_id: str,
    query: QueryModel,
    invoice_id: str = Query(...),
    qma_access_token: Optional[str] = Header(default=None, alias="X-QMA-Access-Token"),
    access_token: Optional[str] = Query(default=None),
):
    """Returns a paid provider full report for the exact query snapshot bound to the invoice."""
    try:
        return run_paid_provider_report(
            provider_id=provider_id,
            query=query,
            invoice_id=invoice_id,
            token=qma_access_token or access_token,
            required_tier="full",
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error running provider full report: {e}")
        raise HTTPException(status_code=500, detail=f"Provider full report failure: {str(e)}")

@app.post("/api/v1/preview")
def preview_signal(
    query: QueryModel,
    invoice_id: str = Query(...),
    qma_access_token: Optional[str] = Header(default=None, alias="X-QMA-Access-Token"),
    access_token: Optional[str] = Query(default=None),
):
    """Backward-compatible Funding Memory preview endpoint."""
    return provider_preview_signal(
        provider_id="funding_memory",
        query=query,
        invoice_id=invoice_id,
        qma_access_token=qma_access_token,
        access_token=access_token,
    )

@app.post("/api/v1/analyze")
def analyze_signal(
    query: QueryModel,
    invoice_id: str = Query(...),
    qma_access_token: Optional[str] = Header(default=None, alias="X-QMA-Access-Token"),
    access_token: Optional[str] = Query(default=None),
):
    """Backward-compatible Funding Memory full report endpoint."""
    return provider_full_report(
        provider_id="funding_memory",
        query=query,
        invoice_id=invoice_id,
        qma_access_token=qma_access_token,
        access_token=access_token,
    )

if __name__ == "__main__":
    import uvicorn
    import sys
    # Ensure parent directory is in Python path for uvicorn imports
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    uvicorn.run("qma.main:app", host="0.0.0.0", port=8000, reload=False)

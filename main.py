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
from pydantic import BaseModel, ConfigDict, Field

# Import QMA Engine
from qma_engine import QMAEngine
import paid_intelligence_kit as paid_kit
from market_data import create_market_data_adapter
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
CREATOR_CLAIMS_PATH = os.path.join(os.path.dirname(__file__), "creator_claims.json")
PAYMENT_AMOUNT_USDC = float(os.getenv("QMA_PAYMENT_AMOUNT_USDC", os.getenv("QMA_PRICE_FULL_USDC", "0.005")))
PAYMENT_RESOURCE_TYPE = os.getenv("QMA_PAYMENT_RESOURCE_TYPE", "qma_signal_report")
PAYMENT_NETWORK = os.getenv("QMA_PAYMENT_NETWORK", "eip155:5042002")
PAYMENT_NETWORK_NAME = os.getenv("QMA_PAYMENT_NETWORK_NAME", "Arc Testnet")
PAYMENT_WALLET_ADDRESS = os.getenv("QMA_ARC_SELLER_ADDRESS", "0x933a2405f84c224be1ef373ba16e992e1f459682")
PLATFORM_TREASURY_ADDRESS = os.getenv("QMA_PLATFORM_TREASURY_ADDRESS", PAYMENT_WALLET_ADDRESS)
ARC_GATEWAY_BASE_URL = os.getenv("QMA_ARC_GATEWAY_URL", "http://127.0.0.1:3000")
ARC_GATEWAY_API = os.getenv("QMA_CIRCLE_GATEWAY_API", "https://gateway-api-testnet.circle.com")
ARC_EXPLORER = os.getenv("QMA_ARC_EXPLORER", "https://testnet.arcscan.app")
ARC_GATEWAY_WALLET = os.getenv("QMA_ARC_GATEWAY_WALLET", "0x0077777d7EBA4688BDeF3E311b846F25870A19B9")
ARC_TESTNET_USDC = os.getenv("QMA_ARC_USDC_ADDRESS", "0x3600000000000000000000000000000000000000")
ARC_GATEWAY_MINTER = os.getenv("QMA_ARC_GATEWAY_MINTER", "0x0022222ABE238Cc2C7Bb1f21003F0a260052475B")
WITHDRAW_MODE = os.getenv("QMA_WITHDRAW_MODE", "seller_wallet").strip().lower()
WITHDRAW_RELAYER_ADDRESS = os.getenv("QMA_WITHDRAW_RELAYER_ADDRESS", "")
WITHDRAW_MIN_USDC = float(os.getenv("QMA_MIN_PROVIDER_WITHDRAW_USDC", "0"))
WITHDRAW_RELAY_DAILY_LIMIT = int(os.getenv("QMA_PROVIDER_WITHDRAW_DAILY_LIMIT", "1"))
CREATOR_CLAIM_MIN_USDC = float(os.getenv("QMA_CREATOR_CLAIM_MIN_USDC", "0"))
CREATOR_CLAIM_INTENT_TTL_SECONDS = int(os.getenv("QMA_CREATOR_CLAIM_INTENT_TTL_SECONDS", "600"))
ARC_GATEWAY_INTERNAL_SECRET = os.getenv("QMA_ARC_GATEWAY_INTERNAL_SECRET", "")
DEFAULT_SETTLEMENT_MODE = os.getenv("QMA_DEFAULT_SETTLEMENT_MODE", "x402_direct_split").strip().lower()
SPLIT_INVOICE_TTL_SECONDS = int(os.getenv("QMA_SPLIT_INVOICE_TTL_SECONDS", "1800"))
SETTLEMENT_RAIL = os.getenv("QMA_SETTLEMENT_RAIL", paid_kit.DEFAULT_SETTLEMENT_RAIL)
SETTLEMENT_CURRENCY = "USDC"
SUPPORTED_SETTLEMENT_ASSETS = ["USDC"]
INVOICE_TTL_SECONDS = int(os.getenv("QMA_INVOICE_TTL_SECONDS", "900"))
ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("QMA_ACCESS_TOKEN_TTL_SECONDS", "300"))
WALLET_PROFILE_TOKEN_TTL_SECONDS = int(os.getenv("QMA_WALLET_PROFILE_TOKEN_TTL_SECONDS", "3600"))
ACCESS_TOKEN_SECRET = os.getenv("QMA_ACCESS_TOKEN_SECRET") or os.getenv("QMA_SESSION_SECRET") or "qma-local-demo-secret-change-me"
SPLIT_LEG_URL_SECRET = os.getenv("QMA_SPLIT_LEG_URL_SECRET") or f"split-url:{ACCESS_TOKEN_SECRET}"
SPLIT_RECEIPT_SECRET = os.getenv("QMA_SPLIT_RECEIPT_SECRET") or f"split-receipt:{ACCESS_TOKEN_SECRET}"
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
    try:
        if hasattr(storage_backend, "load_paid_report_by_id"):
            return storage_backend.load_paid_report_by_id(address, entitlement_id)
    except Exception as exc:
        logger.warning(f"Could not load paid report by id: {exc}")
    normalized = normalize_address(address)
    record = load_paid_reports().get(entitlement_id)
    if isinstance(record, dict) and normalize_address(record.get("payer_address")) == normalized:
        return record
    return None

def save_paid_reports(reports: dict) -> None:
    try:
        storage_backend.save_paid_reports(reports)
    except Exception as exc:
        logger.warning(f"Could not save paid reports: {exc}")

paid_reports = load_paid_reports()

def invoice_payment_schema(amount: Optional[float], *, settlement: Optional[dict] = None) -> dict:
    amount_value = float(amount or 0)
    current_settlement = settlement or paid_kit.settlement_profile(
        amount_usdc=amount_value,
        network_name=PAYMENT_NETWORK_NAME,
        rail=SETTLEMENT_RAIL,
        currency=SETTLEMENT_CURRENCY,
        token_address=ARC_TESTNET_USDC,
        decimals=6,
        gateway_supported=True,
    )
    return {
        "pricing": paid_kit.pricing_profile(amount_usdc=amount_value),
        "settlement": current_settlement,
        "accounting": paid_kit.accounting_profile(
            amount_usdc=amount_value,
            currency=current_settlement.get("currency", "USDC"),
        ),
    }

def hydrate_payment_schema(record: Optional[dict]) -> dict:
    if not isinstance(record, dict):
        return {}
    amount = record.get("amount", record.get("amount_usdc", 0))
    schema = invoice_payment_schema(amount, settlement=record.get("settlement"))
    record.setdefault("pricing", schema["pricing"])
    record.setdefault("settlement", schema["settlement"])
    record.setdefault("accounting", schema["accounting"])
    return record

def usdc_to_raw(amount_usdc: float) -> int:
    return int(round(float(amount_usdc) * 1_000_000))

def raw_usdc_str(raw_amount: int | str) -> str:
    return str(int(raw_amount))

def raw_usdc_to_decimal_string(raw_amount: int | str) -> str:
    return f"{int(raw_amount) / 1_000_000:.6f}".rstrip("0").rstrip(".")

def split_hmac_payload(parts: list[str]) -> str:
    return "/".join(str(part) for part in parts)

def sign_split_leg_url(*, invoice_id: str, provider_id: str, tier: str, leg_id: str, amount_raw: str, pay_to: str, expires_at: float) -> str:
    payload = split_hmac_payload([
        invoice_id,
        provider_id,
        tier,
        leg_id,
        raw_usdc_str(amount_raw),
        normalize_address(pay_to),
        str(int(expires_at)),
    ])
    return hmac.new(SPLIT_LEG_URL_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

def verify_split_leg_url_sig(*, invoice_id: str, provider_id: str, tier: str, leg_id: str, amount_raw: str, pay_to: str, expires_at: float, sig: str) -> bool:
    expected = sign_split_leg_url(
        invoice_id=invoice_id,
        provider_id=provider_id,
        tier=tier,
        leg_id=leg_id,
        amount_raw=amount_raw,
        pay_to=pay_to,
        expires_at=expires_at,
    )
    return hmac.compare_digest(str(sig or ""), expected)

def sign_split_receipt(*, invoice_id: str, leg_id: str, pay_to: str, settled_amount_raw: str, settlement_id: str) -> str:
    payload = split_hmac_payload([
        invoice_id,
        leg_id,
        normalize_address(pay_to),
        raw_usdc_str(settled_amount_raw),
        settlement_id,
    ])
    return hmac.new(SPLIT_RECEIPT_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

def verify_split_receipt(*, invoice_id: str, leg_id: str, pay_to: str, settled_amount_raw: str, settlement_id: str, receipt: str) -> bool:
    expected = sign_split_receipt(
        invoice_id=invoice_id,
        leg_id=leg_id,
        pay_to=pay_to,
        settled_amount_raw=settled_amount_raw,
        settlement_id=settlement_id,
    )
    return hmac.compare_digest(str(receipt or ""), expected)

def allocate_split_legs_raw(total_raw: int, creator_bps: int, platform_bps: int) -> dict:
    weights = [max(0, int(creator_bps)), max(0, int(platform_bps))]
    if sum(weights) != 10000:
        raise HTTPException(status_code=400, detail="Creator/platform split must total 10000 bps.")
    if total_raw <= 0:
        raise HTTPException(status_code=400, detail="Invoice amount must be greater than 0.")
    ideals = [(total_raw * weight) / 10000 for weight in weights]
    floors = [int(value) for value in ideals]
    leftover = total_raw - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: ideals[i] - floors[i], reverse=True)
    for index in order[:leftover]:
        floors[index] += 1
    if any(weight > 0 and amount < 1 for weight, amount in zip(weights, floors)):
        raise HTTPException(
            status_code=400,
            detail="Invoice amount is too small to produce valid nonzero creator and platform split legs.",
        )
    return {"creator": floors[0], "platform": floors[1]}

def provider_settlement_mode(provider) -> str:
    return str(getattr(provider, "settlement_mode", DEFAULT_SETTLEMENT_MODE) or DEFAULT_SETTLEMENT_MODE).strip().lower()

def provider_revenue_wallet(provider) -> str:
    return normalize_address(getattr(provider, "revenue_wallet", None) or getattr(provider, "owner_wallet", None))

def build_invoice_split(*, invoice_id: str, provider, tier: str, amount_usdc: float, expires_at: float) -> dict:
    creator_share_bps = int(getattr(provider, "revenue_share_bps", 8000))
    platform_share_bps = 10000 - creator_share_bps
    total_raw = usdc_to_raw(amount_usdc)
    raw_allocations = allocate_split_legs_raw(total_raw, creator_share_bps, platform_share_bps)
    creator_wallet = provider_revenue_wallet(provider)
    platform_wallet = normalize_address(PLATFORM_TREASURY_ADDRESS)
    if not creator_wallet:
        raise HTTPException(status_code=400, detail=f"Provider {provider.provider_id} has no revenue wallet.")
    if not platform_wallet:
        raise HTTPException(status_code=500, detail="Platform treasury wallet is not configured.")
    legs = []
    for leg_id, role, pay_to in [
        ("creator", "creator", creator_wallet),
        ("platform", "platform", platform_wallet),
    ]:
        amount_raw = raw_usdc_str(raw_allocations[leg_id])
        amount_usdc_str = raw_usdc_to_decimal_string(amount_raw)
        sig = sign_split_leg_url(
            invoice_id=invoice_id,
            provider_id=provider.provider_id,
            tier=tier,
            leg_id=leg_id,
            amount_raw=amount_raw,
            pay_to=pay_to,
            expires_at=expires_at,
        )
        url = (
            f"{ARC_GATEWAY_BASE_URL.rstrip('/')}/qma-access/split-leg"
            f"?invoice_id={invoice_id}&provider_id={provider.provider_id}&tier={tier}"
            f"&leg_id={leg_id}&amount_raw={amount_raw}&pay_to={pay_to}"
            f"&expires_at={int(expires_at)}&sig={sig}"
        )
        legs.append({
            "leg_id": leg_id,
            "role": role,
            "pay_to": pay_to,
            "amount_usdc": amount_usdc_str,
            "amount_raw": amount_raw,
            "status": "pending",
            "settlement_id": None,
            "expires_at": expires_at,
            "resource": url,
        })
    return {
        "mode": "x402_direct_split",
        "creator_share_bps": creator_share_bps,
        "platform_share_bps": platform_share_bps,
        "total_amount_raw": raw_usdc_str(total_raw),
        "legs": legs,
    }

def split_leg_by_id(invoice: dict, leg_id: str) -> Optional[dict]:
    split = invoice.get("split") or {}
    for leg in split.get("legs") or []:
        if leg.get("leg_id") == leg_id:
            return leg
    return None

def invoice_required_split_legs(invoice: dict) -> list[dict]:
    return list((invoice.get("split") or {}).get("legs") or [])

def invoice_split_mode(invoice: dict) -> str:
    return str((invoice.get("settlement") or {}).get("mode") or (invoice.get("split") or {}).get("mode") or "treasury_ledger")

def refresh_split_invoice_status(invoice: dict) -> str:
    if invoice_split_mode(invoice) != "x402_direct_split":
        return invoice.get("status", "pending")
    legs = invoice_required_split_legs(invoice)
    settled_count = sum(1 for leg in legs if leg.get("status") == "paid" and leg.get("settlement_id"))
    if settled_count == len(legs) and legs:
        invoice["status"] = "paid"
    elif settled_count > 0:
        invoice["status"] = "partial_paid"
    elif time.time() > float(invoice.get("expires_at") or 0):
        invoice["status"] = "expired"
    else:
        invoice["status"] = "pending"
    return invoice["status"]

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
    hydrate_payment_schema(invoice)
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
        "pricing": invoice.get("pricing"),
        "settlement": invoice.get("settlement"),
        "accounting": invoice.get("accounting"),
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
    events = []
    for invoice in load_invoices().values():
        if not isinstance(invoice, dict) or invoice.get("status") != "paid":
            continue
        if invoice_split_mode(invoice) == "x402_direct_split":
            for leg in invoice_required_split_legs(invoice):
                if leg.get("status") == "paid" and leg.get("settlement_id"):
                    events.append(split_leg_event(invoice, leg))
        else:
            events.append(paid_invoice_event(invoice))
    return events

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

def load_creator_claims() -> list:
    try:
        if hasattr(storage_backend, "load_creator_claims"):
            records = storage_backend.load_creator_claims()
            if isinstance(records, list):
                return records
    except Exception as exc:
        logger.warning(f"Could not load creator claims from storage backend: {exc}")
    try:
        if os.path.exists(CREATOR_CLAIMS_PATH):
            with open(CREATOR_CLAIMS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as exc:
        logger.warning(f"Could not load local creator claims: {exc}")
    return []

def save_creator_claim_record(record: dict) -> bool:
    saved = False
    try:
        if hasattr(storage_backend, "save_creator_claim"):
            storage_backend.save_creator_claim(record)
            saved = True
    except Exception as exc:
        logger.warning(f"Could not save creator claim to storage backend: {exc}")
    try:
        records = []
        if os.path.exists(CREATOR_CLAIMS_PATH):
            with open(CREATOR_CLAIMS_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
            records = existing if isinstance(existing, list) else []
        claim_id = record.get("claim_id")
        replaced = False
        for idx, item in enumerate(records):
            if item.get("claim_id") == claim_id:
                records[idx] = record
                replaced = True
                break
        if not replaced:
            records.append(record)
        with open(CREATOR_CLAIMS_PATH, "w", encoding="utf-8") as f:
            json.dump(records[-1000:], f, indent=2)
        saved = True
    except Exception as exc:
        logger.warning(f"Could not save local creator claim: {exc}")
    return saved

# format: {invoice_id: {"status": "pending"|"paid", "created_at": float, "symbol": str}}
invoices_db: Dict[str, dict] = load_invoices()
creator_applications: Dict[str, dict] = load_creator_applications()
provider_runtime_controls.update(load_provider_controls())
creator_claims_db: list = load_creator_claims()

def reload_persistent_state(include_reports: bool = True, include_invoices: bool = False) -> None:
    global payment_events, paid_reports, invoices_db, creator_claims_db
    payment_events = load_payment_ledger()
    if include_reports:
        paid_reports = load_paid_reports()
    if include_invoices:
        invoices_db = load_invoices()
    creator_applications.update(load_creator_applications())
    provider_runtime_controls.update(load_provider_controls())
    creator_claims_db = load_creator_claims()

# Simple Cache for Live MEXC Anomalies
live_anomalies_cache = {
    "data": [],
    "last_updated": 0.0
}
CACHE_TTL_SECONDS = 30.0
live_scan_lock = threading.Lock()
creator_claim_lock = threading.Lock()
split_leg_lock = threading.Lock()
market_data_adapter = create_market_data_adapter(os.getenv("QMA_MARKET_DATA_SOURCE", "mexc_futures"))

class QueryModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str = Field(..., min_length=1, max_length=32)
    fundingRate: Optional[float] = 0.0
    marketCap: Optional[float] = Field(default=None, gt=0)
    FDV: Optional[float] = Field(default=None, gt=0)
    circRatio: Optional[float] = Field(default=None, gt=0, le=1.5)
    fromATH: Optional[float] = None
    volume24h: Optional[float] = Field(default=None, gt=0)
    amount: Optional[float] = Field(default=None, gt=0) # turnover proxy
    openInterest: Optional[float] = Field(default=None, gt=0)
    openInterestChange24h: Optional[float] = None
    longShortRatio: Optional[float] = Field(default=None, gt=0)
    price: Optional[float] = Field(default=None, gt=0)

class InvoiceRequest(QueryModel):
    provider_id: str = Field(default="funding_memory", max_length=64)
    tier: str = Field(default="full", pattern="^(preview|full)$")
    resource_type: str = Field(default="qma_signal_report", max_length=64)
    buyer_type: str = Field(default="human", pattern="^(human|agent)$")
    synthetic: bool = False
    agent_label: Optional[str] = Field(default=None, max_length=120)
    run_source: Optional[str] = Field(default=None, max_length=120)

class QuoteRequest(QueryModel):
    provider_id: str = Field(default="funding_memory", max_length=64)
    tier: str = Field(default="full", pattern="^(preview|full)$")

class SplitSettlementProof(BaseModel):
    leg_id: str = Field(..., min_length=2, max_length=32)
    settlement_id: str = Field(..., min_length=8)
    pay_to: str = Field(..., min_length=8, max_length=80)
    amount_raw: str = Field(..., min_length=1, max_length=80)
    sidecar_receipt: str = Field(..., min_length=20, max_length=300)

class PaymentVerifyRequest(BaseModel):
    settlement_id: Optional[str] = Field(default=None, min_length=8)
    invoice_secret: str = Field(..., min_length=16)
    payer_address: Optional[str] = None
    amount_usdc: Optional[float] = None
    split_settlements: List[SplitSettlementProof] = Field(default_factory=list)

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

class CreatorClaimRequest(BaseModel):
    claimant_address: str = Field(..., min_length=8, max_length=80)
    provider_ids: List[str] = Field(default_factory=list)
    amount_usdc: Optional[float] = Field(default=None, gt=0)
    nonce: str = Field(..., min_length=8, max_length=120)
    issued_at: int = Field(..., gt=0)
    signature: str = Field(..., min_length=20, max_length=300)

class WalletProfileSessionRequest(BaseModel):
    nonce: str = Field(..., min_length=8, max_length=120)
    issued_at: int = Field(..., gt=0)
    signature: str = Field(..., min_length=20, max_length=300)

def model_to_dict(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()

def normalize_query_for_provider(provider, query: dict) -> dict:
    if hasattr(provider, "normalize_query"):
        return provider.normalize_query(query)
    return canonical_query_payload(query)

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
        "entitlement_id": record.get("entitlement_id"),
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
        "has_report": isinstance(record.get("report"), dict),
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
        settlement_rail=SETTLEMENT_RAIL,
        settlement_currency=SETTLEMENT_CURRENCY,
        settlement_token_address=ARC_TESTNET_USDC,
        settlement_decimals=6,
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
    hydrate_payment_schema(invoice)
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

def bytes32_to_address(value: Optional[str]) -> str:
    raw = str(value or "").strip().lower()
    if not raw.startswith("0x") or len(raw) != 66:
        raise HTTPException(status_code=400, detail="Malformed bytes32 address in withdraw intent")
    try:
        int(raw[2:], 16)
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed bytes32 address in withdraw intent")
    return "0x" + raw[-40:]

def address_to_bytes32(address: str) -> str:
    return "0x" + normalize_address(address).replace("0x", "").rjust(64, "0")

def same_address(left: Optional[str], right: Optional[str]) -> bool:
    return normalize_address(left) == normalize_address(right)

def canonical_provider_ids(provider_ids: list[str]) -> list[str]:
    clean = []
    for provider_id in provider_ids or []:
        value = str(provider_id or "").strip()
        if value and value not in clean:
            clean.append(value)
    return sorted(clean)

def build_creator_claim_message(
    *,
    claimant_address: str,
    provider_ids: list[str],
    amount_usdc: float,
    nonce: str,
    issued_at: int,
) -> str:
    providers = ",".join(canonical_provider_ids(provider_ids))
    return "\n".join([
        "QMA Creator Claim",
        f"claimant: {normalize_address(claimant_address)}",
        f"providers: {providers}",
        f"amount_usdc: {float(amount_usdc):.6f}",
        f"nonce: {nonce}",
        f"issued_at: {int(issued_at)}",
        f"network: {PAYMENT_NETWORK_NAME}",
    ])

def recover_creator_claim_signer(message: str, signature: str) -> str:
    if Account is None or encode_defunct is None:
        raise HTTPException(status_code=503, detail="eth_account is not installed; creator claim signatures cannot be verified.")
    try:
        recovered = Account.recover_message(encode_defunct(text=message), signature=signature)
        return normalize_address(recovered)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid creator claim signature: {exc}")

def validate_withdraw_intent(burn_intent: dict, *, expected_depositor: str) -> dict:
    spec = (burn_intent or {}).get("spec") or {}
    required = [
        "sourceDomain", "destinationDomain", "sourceContract", "destinationContract",
        "sourceToken", "destinationToken", "sourceDepositor", "destinationRecipient",
        "sourceSigner", "destinationCaller", "value",
    ]
    missing = [key for key in required if key not in spec]
    if missing:
        raise HTTPException(status_code=400, detail=f"Withdraw intent is missing fields: {', '.join(missing)}")

    depositor = bytes32_to_address(spec.get("sourceDepositor"))
    signer = bytes32_to_address(spec.get("sourceSigner"))
    recipient = bytes32_to_address(spec.get("destinationRecipient"))
    source_contract = bytes32_to_address(spec.get("sourceContract"))
    destination_contract = bytes32_to_address(spec.get("destinationContract"))
    source_token = bytes32_to_address(spec.get("sourceToken"))
    destination_token = bytes32_to_address(spec.get("destinationToken"))
    destination_caller = bytes32_to_address(spec.get("destinationCaller"))

    if not same_address(depositor, expected_depositor):
        raise HTTPException(status_code=403, detail="Withdraw intent depositor does not match the authorized Gateway balance owner")
    if not same_address(signer, depositor):
        raise HTTPException(status_code=403, detail="Withdraw intent signer must match depositor")
    if not same_address(recipient, expected_depositor):
        raise HTTPException(status_code=403, detail="Withdraw recipient must match the authorized Gateway balance owner")
    try:
        source_domain = int(spec.get("sourceDomain"))
        destination_domain = int(spec.get("destinationDomain"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Withdraw intent domain is invalid")
    if source_domain != 26 or destination_domain != 26:
        raise HTTPException(status_code=400, detail="Withdraw intent must target Arc Testnet Gateway domain 26")
    if not same_address(source_contract, ARC_GATEWAY_WALLET) or not same_address(destination_contract, ARC_GATEWAY_MINTER):
        raise HTTPException(status_code=400, detail="Withdraw intent targets an unexpected Gateway contract")
    if not same_address(source_token, ARC_TESTNET_USDC) or not same_address(destination_token, ARC_TESTNET_USDC):
        raise HTTPException(status_code=400, detail="Withdraw intent targets an unsupported token")
    if not same_address(destination_caller, "0x0000000000000000000000000000000000000000"):
        raise HTTPException(status_code=400, detail="Withdraw intent mint is not permissionless")

    try:
        value_raw = int(spec.get("value"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Withdraw intent amount is invalid")
    if value_raw <= 0:
        raise HTTPException(status_code=400, detail="Withdraw amount must be greater than zero")
    amount_usdc = raw_usdc_to_float(str(value_raw))
    return {
        "depositor": depositor,
        "signer": signer,
        "recipient": recipient,
        "amount_usdc": amount_usdc,
        "value_raw": str(value_raw),
    }

def enforce_withdraw_relay_policy(intent: dict) -> None:
    if WITHDRAW_MIN_USDC > 0 and float(intent.get("amount_usdc") or 0) < WITHDRAW_MIN_USDC:
        raise HTTPException(
            status_code=400,
            detail=f"Minimum platform-relayed withdraw is {WITHDRAW_MIN_USDC:.6f} USDC",
        )
    if WITHDRAW_RELAY_DAILY_LIMIT <= 0:
        return
    now = time.time()
    key = normalize_address(intent.get("depositor"))
    bucket = withdraw_relay_daily_events[key]
    while bucket and now - bucket[0] > 86400:
        bucket.popleft()
    if len(bucket) >= WITHDRAW_RELAY_DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Daily platform-relayed withdraw limit reached ({WITHDRAW_RELAY_DAILY_LIMIT}/day)",
        )

def record_withdraw_relay(intent: dict) -> None:
    if WITHDRAW_RELAY_DAILY_LIMIT <= 0:
        return
    withdraw_relay_daily_events[normalize_address(intent.get("depositor"))].append(time.time())

def paid_report_key(
    payer_address: Optional[str],
    query_hash: Optional[str],
    tier: str = "full",
    provider_id: str = "funding_memory",
) -> str:
    return paid_kit.entitlement_key(payer_address, query_hash, tier, provider_id)

def raw_usdc_to_float(raw_amount: str) -> float:
    return int(raw_amount) / 1_000_000

def raw_token_to_float(raw_amount: str, decimals: int = 6) -> float:
    return int(raw_amount) / float(10 ** int(decimals))

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
gateway_info_cache: Dict[str, dict] = {}
withdraw_relay_daily_events = defaultdict(deque)

def fetch_gateway_balance_cached(address: str, ttl_seconds: int = 15) -> dict:
    key = normalize_address(address)
    now = time.time()
    cached = gateway_balance_cache.get(key)
    if cached and now - cached.get("at", 0) < ttl_seconds:
        return cached["data"]
    data = fetch_gateway_balance(address)
    gateway_balance_cache[key] = {"at": now, "data": data}
    return data

def summarize_gateway_info(data: Optional[dict] = None, *, include_raw: bool = False) -> dict:
    raw = data if isinstance(data, dict) else {}
    domains = []
    for item in raw.get("domains") or []:
        wallet_contract = item.get("walletContract") or {}
        minter_contract = item.get("minterContract") or {}
        domains.append({
            "domain": item.get("domain"),
            "chain": item.get("chain"),
            "network": item.get("network"),
            "wallet_contract": wallet_contract.get("address"),
            "minter_contract": minter_contract.get("address"),
            "wallet_supported_tokens": wallet_contract.get("supportedTokens") or [],
            "minter_supported_tokens": minter_contract.get("supportedTokens") or [],
            "processed_height": item.get("processedHeight"),
            "burn_intent_expiration_height": item.get("burnIntentExpirationHeight"),
        })
    arc_domain = next((item for item in domains if item.get("domain") == 26), None)
    result = {
        "status": "ok" if raw else "unavailable",
        "api": ARC_GATEWAY_API,
        "runtime_rail": SETTLEMENT_RAIL,
        "runtime_currency": SETTLEMENT_CURRENCY,
        "runtime_supported_assets": SUPPORTED_SETTLEMENT_ASSETS,
        "runtime_gateway_supported": True,
        "funding_visibility_only": ["EURC", "cirBTC"],
        "domains": domains,
        "domain_count": len(domains),
        "arc_testnet": arc_domain or {
            "domain": 26,
            "chain": "Arc",
            "network": "testnet",
            "wallet_contract": ARC_GATEWAY_WALLET,
            "minter_contract": "0x0022222ABE238Cc2C7Bb1f21003F0a260052475B",
            "wallet_supported_tokens": [ARC_TESTNET_USDC],
            "minter_supported_tokens": [ARC_TESTNET_USDC],
        },
        "notes": [
            "QMA runtime settlement remains USDC-only on Circle Gateway x402.",
            "EURC/cirBTC are funding visibility assets only until Gateway settlement support is explicitly enabled.",
            "Creator/platform split is an accounting ledger over USDC receipts, not an on-chain split contract yet.",
        ],
    }
    if include_raw:
        result["raw"] = raw
    return result

def fetch_gateway_info() -> dict:
    try:
        resp = requests.get(f"{ARC_GATEWAY_API}/v1/info", timeout=10)
    except requests.RequestException as exc:
        return {**summarize_gateway_info(), "error": str(exc)}
    if not resp.ok:
        return {
            **summarize_gateway_info(),
            "error": f"{resp.status_code}: {resp.text[:200]}",
        }
    try:
        return summarize_gateway_info(resp.json(), include_raw=True)
    except ValueError as exc:
        return {**summarize_gateway_info(), "error": f"Invalid Gateway info JSON: {exc}"}

def fetch_gateway_info_cached(ttl_seconds: int = 300, *, include_raw: bool = False) -> dict:
    now = time.time()
    cached = gateway_info_cache.get("gateway")
    if cached and now - cached.get("at", 0) < ttl_seconds:
        data = cached["data"]
    else:
        data = fetch_gateway_info()
        gateway_info_cache["gateway"] = {"at": now, "data": data}
    if include_raw:
        return data
    compact = {key: value for key, value in data.items() if key != "raw"}
    return compact

def fetch_creator_claim_status_cached(ttl_seconds: int = 15) -> dict:
    now = time.time()
    cached = gateway_info_cache.get("creator_claim")
    if cached and now - cached.get("at", 0) < ttl_seconds:
        return cached["data"]
    try:
        resp = requests.get(f"{ARC_GATEWAY_BASE_URL.rstrip('/')}/api/creator/claim/status", timeout=5)
        data = resp.json() if resp.ok else {
            "configured": False,
            "error": f"{resp.status_code}: {resp.text[:200]}",
        }
    except requests.RequestException as exc:
        data = {"configured": False, "error": str(exc)}
    gateway_info_cache["creator_claim"] = {"at": now, "data": data}
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
        "split_leg": event.get("split_leg"),
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

def provider_split_metadata(provider_id: str, fallback_owner: Optional[str] = None) -> dict:
    try:
        provider = provider_registry.require(provider_id)
        provider_name = provider.provider_name
        owner_wallet = provider.owner_wallet or fallback_owner
        share_bps = int(getattr(provider, "revenue_share_bps", 8000))
    except Exception:
        provider_name = provider_id
        owner_wallet = fallback_owner
        share_bps = 8000
    share_bps = max(0, min(10000, share_bps))
    return {
        "provider_name": provider_name,
        "owner_wallet": owner_wallet,
        "creator_share_bps": share_bps,
        "platform_share_bps": 10000 - share_bps,
    }

CLAIM_RESERVED_STATUSES = {"requested", "submitted", "paid"}

def creator_claim_records_for_provider(provider_id: str, owner_wallet: Optional[str] = None) -> list:
    owner = normalize_address(owner_wallet) if owner_wallet else ""
    return [
        record for record in creator_claims_db
        if provider_id in (record.get("provider_ids") or [])
        and (not owner or same_address(record.get("claimant_address"), owner))
    ]

def creator_claim_amounts(provider_id: str, owner_wallet: Optional[str] = None) -> dict:
    records = creator_claim_records_for_provider(provider_id, owner_wallet)
    paid = 0.0
    pending = 0.0
    failed = 0.0
    for record in records:
        allocations = record.get("allocations") or {}
        amount = float(allocations.get(provider_id, 0) or 0)
        status_value = str(record.get("status") or "").lower()
        if status_value == "paid":
            paid += amount
        elif status_value in CLAIM_RESERVED_STATUSES:
            pending += amount
        elif status_value == "failed":
            failed += amount
    return {
        "paid_usdc": round(paid, 6),
        "pending_usdc": round(pending, 6),
        "failed_usdc": round(failed, 6),
        "reserved_usdc": round(paid + pending, 6),
        "records": records,
    }

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
    seen_report_keys = set()
    top_symbols = {}
    payer_stats = {}
    for event in sorted_events:
        tier = payment_event_tier(event)
        event["tier_category"] = tier
        amount = float(event.get("amount_usdc") or 0)
        provider_id = event.get("provider_id", "funding_memory")
        buyer_type = event.get("buyer_type", "human")
        report_key = event.get("invoice_id") or payment_event_key(event)
        first_report_event = report_key not in seen_report_keys
        if first_report_event:
            seen_report_keys.add(report_key)
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            buyer_type_counts[buyer_type] = buyer_type_counts.get(buyer_type, 0) + 1
        revenue_by_tier[tier] = revenue_by_tier.get(tier, 0.0) + amount
        split_meta = provider_split_metadata(
            provider_id,
            event.get("provider_owner_wallet") or event.get("seller_address"),
        )
        provider_stats = revenue_by_provider.setdefault(provider_id, {
            "provider_id": provider_id,
            "provider_name": split_meta["provider_name"],
            "owner_wallet": split_meta["owner_wallet"],
            "creator_share_bps": split_meta["creator_share_bps"],
            "platform_share_bps": split_meta["platform_share_bps"],
            "payments": 0,
            "revenue_usdc": 0.0,
            "creator_earned_usdc": 0.0,
            "platform_fee_usdc": 0.0,
            "creator_claimable_usdc": 0.0,
            "withdrawal_mode": "creator_initiated_claim_planned",
            "settlement_currency": "USDC",
            "_invoice_ids": set(),
        })
        provider_stats["_invoice_ids"].add(report_key)
        provider_stats["payments"] = len(provider_stats["_invoice_ids"])
        provider_stats["revenue_usdc"] += amount
        split_leg = event.get("split_leg") or {}
        split_role = split_leg.get("role")
        if split_role == "creator":
            provider_stats["creator_earned_usdc"] += amount
            provider_stats["withdrawal_mode"] = "direct_gateway_split"
        elif split_role == "platform":
            provider_stats["platform_fee_usdc"] += amount
            provider_stats["withdrawal_mode"] = "direct_gateway_split"
        else:
            provider_stats["creator_earned_usdc"] += amount * provider_stats["creator_share_bps"] / 10000
            provider_stats["platform_fee_usdc"] += amount * provider_stats["platform_share_bps"] / 10000
        claim_amounts = creator_claim_amounts(provider_id, provider_stats.get("owner_wallet"))
        provider_stats["creator_claimed_usdc"] = claim_amounts["paid_usdc"]
        provider_stats["creator_claim_pending_usdc"] = claim_amounts["pending_usdc"]
        provider_stats["creator_claimable_usdc"] = 0.0 if provider_stats["withdrawal_mode"] == "direct_gateway_split" else max(
            0.0,
            provider_stats["creator_earned_usdc"] - claim_amounts["reserved_usdc"],
        )
        if first_report_event and event.get("symbol"):
            top_symbols[event["symbol"]] = top_symbols.get(event["symbol"], 0) + 1
        payer = normalize_address(event.get("payer_address"))
        if not payer:
            continue
        stats = payer_stats.setdefault(payer, {
            "payer_address": event.get("payer_address"),
            "payments": 0,
            "spent_usdc": 0.0,
            "symbols": set(),
            "providers": set(),
            "preview_count": 0,
            "full_count": 0,
            "last_paid_at": None,
        })
        if first_report_event:
            stats["payments"] += 1
        stats["spent_usdc"] += amount
        if first_report_event and tier == "preview":
            stats["preview_count"] += 1
        elif first_report_event and tier == "full":
            stats["full_count"] += 1
        if event.get("symbol"):
            stats["symbols"].add(event.get("symbol"))
        if event.get("provider_id"):
            stats["providers"].add(event.get("provider_id"))
        stats["last_paid_at"] = max(stats["last_paid_at"] or 0, event.get("paid_at") or 0)
    payer_breakdown = []
    for stats in payer_stats.values():
        stats["symbols"] = sorted(stats["symbols"])
        stats["providers"] = sorted(stats["providers"])
        payer_breakdown.append(stats)
    current_paid_count = tier_counts.get("preview", 0) + tier_counts.get("full", 0)
    current_revenue = revenue_by_tier.get("preview", 0.0) + revenue_by_tier.get("full", 0.0)
    revenue = sum(float(event.get("amount_usdc") or 0) for event in sorted_events)
    provider_breakdown = []
    for stats in revenue_by_provider.values():
        stats.pop("_invoice_ids", None)
        direct_split = stats.get("withdrawal_mode") == "direct_gateway_split"
        provider_breakdown.append({
            **stats,
            "revenue_usdc": round(stats["revenue_usdc"], 6),
            "creator_earned_usdc": round(stats["creator_earned_usdc"], 6),
            "platform_fee_usdc": round(stats["platform_fee_usdc"], 6),
            "creator_claimable_usdc": round(stats["creator_claimable_usdc"], 6),
            "creator_claimed_usdc": round(stats.get("creator_claimed_usdc", 0), 6),
            "creator_claim_pending_usdc": round(stats.get("creator_claim_pending_usdc", 0), 6),
            "split_note": (
                "Direct Gateway split. Creator leg settles to provider Gateway balance."
                if direct_split else
                "Ledger estimate only. Funds settle to platform treasury; creator claim execution is not live yet."
            ),
        })
    return {
        "events": sorted_events,
        "paid_count": len(seen_report_keys),
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
            provider_breakdown,
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
    hydrate_payment_schema(invoice)
    settlement_meta = invoice.get("settlement") or {}
    settlement_currency = settlement_meta.get("currency", "USDC")
    if settlement_currency != "USDC" or settlement_meta.get("gateway_supported") is False:
        raise HTTPException(
            status_code=400,
            detail=f"{settlement_currency} settlement is not enabled for Circle Gateway runtime.",
        )

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

    paid_amount = raw_token_to_float(str(settlement.get("amount", "0")), settlement_meta.get("decimals", 6))
    expected_amount = float(invoice["amount"])
    if paid_amount + 1e-9 < expected_amount:
        raise HTTPException(status_code=400, detail=f"Settlement amount {paid_amount} {settlement_currency} is below invoice amount {expected_amount} {settlement_currency}.")

    if payer_address and normalize_address(settlement.get("fromAddress")) != normalize_address(payer_address):
        raise HTTPException(status_code=400, detail="Settlement payer does not match connected wallet.")

def validate_arc_split_leg_payment(invoice: dict, leg: dict, settlement: dict, payer_address: Optional[str] = None) -> None:
    hydrate_payment_schema(invoice)
    if REQUIRE_COMPLETED_SETTLEMENT:
        accepted_statuses = {"completed", "confirmed"}
        rejected_msg = f"Strict mode: settlement status is '{settlement.get('status')}'."
    else:
        accepted_statuses = {"received", "batched", "completed", "confirmed"}
        rejected_msg = f"Settlement status is '{settlement.get('status')}'; payment has not been accepted by Circle yet."
    if settlement.get("status") not in accepted_statuses:
        raise HTTPException(status_code=402, detail=rejected_msg)
    if normalize_address(settlement.get("toAddress")) != normalize_address(leg.get("pay_to")):
        raise HTTPException(status_code=400, detail=f"Settlement pay_to does not match split leg {leg.get('leg_id')}.")
    if raw_usdc_str(settlement.get("amount", "0")) != raw_usdc_str(leg.get("amount_raw")):
        raise HTTPException(status_code=400, detail=f"Settlement amount does not exactly match split leg {leg.get('leg_id')}.")
    if payer_address and normalize_address(settlement.get("fromAddress")) != normalize_address(payer_address):
        raise HTTPException(status_code=400, detail="Settlement payer does not match connected wallet.")

def split_leg_event(invoice: dict, leg: dict) -> dict:
    return {
        "event_id": f"{invoice.get('invoice_id')}:{leg.get('leg_id')}",
        "invoice_id": invoice.get("invoice_id"),
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
        "payer_address": leg.get("payer_address") or invoice.get("payer_address"),
        "seller_address": leg.get("pay_to"),
        "amount_usdc": raw_usdc_to_decimal_string(leg.get("amount_raw")),
        "amount_raw": raw_usdc_str(leg.get("amount_raw")),
        "pricing": {"amount_usdc": raw_usdc_to_decimal_string(leg.get("amount_raw"))},
        "settlement": invoice.get("settlement"),
        "accounting": invoice.get("accounting"),
        "split_leg": {
            "leg_id": leg.get("leg_id"),
            "role": leg.get("role"),
            "pay_to": leg.get("pay_to"),
            "amount_raw": raw_usdc_str(leg.get("amount_raw")),
            "amount_usdc": raw_usdc_to_decimal_string(leg.get("amount_raw")),
        },
        "settlement_id": leg.get("settlement_id"),
        "gateway_status": leg.get("gateway_status"),
        "transaction_hash": leg.get("transaction_hash"),
        "explorer_url": leg.get("explorer_url"),
        "paid_at": leg.get("paid_at") or invoice.get("paid_at"),
    }

def upsert_payment_event(event: dict) -> None:
    key = payment_event_key(event)
    if not key:
        return
    for idx, existing in enumerate(payment_events):
        if payment_event_key(existing) == key:
            payment_events[idx] = {**existing, **event}
            return
    payment_events.append(event)

# Live Scanner Helpers
def scan_mexc_live() -> list:
    """Returns canonical live market signals from the active market-data adapter."""
    try:
        data = market_data_adapter.scan_anomalies()
        return data or live_anomalies_cache.get("data", [])
    except Exception as e:
        logger.error(f"Failed to scan live market data: {e}")
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
    seller_balance = fetch_gateway_balance_cached(PLATFORM_TREASURY_ADDRESS)
    gateway_info = fetch_gateway_info_cached()
    creator_claim_status = fetch_creator_claim_status_cached()
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
        "seller_wallet": PLATFORM_TREASURY_ADDRESS,
        "platform_treasury_wallet": PLATFORM_TREASURY_ADDRESS,
        # circle_deposit_contract = address buyers actually send funds to (Circle Gateway contract)
        "circle_deposit_contract": ARC_GATEWAY_WALLET,
        "seller_gateway_balance": seller_balance,
        "gateway_info": gateway_info,
        "pricing": paid_kit.pricing_config(),
        "settlement": {
            "runtime_currency": SETTLEMENT_CURRENCY,
            "supported_assets": SUPPORTED_SETTLEMENT_ASSETS,
            "rail": SETTLEMENT_RAIL,
            "token_address": ARC_TESTNET_USDC,
            "decimals": 6,
            "gateway_supported": True,
            "funding_visibility_only": ["EURC", "cirBTC"],
            "default_mode": DEFAULT_SETTLEMENT_MODE,
        },
        "split_payments": {
            "mode": DEFAULT_SETTLEMENT_MODE,
            "url_secret_configured": bool(SPLIT_LEG_URL_SECRET),
            "internal_secret_configured": bool(ARC_GATEWAY_INTERNAL_SECRET),
            "separate_secrets": SPLIT_LEG_URL_SECRET != ARC_GATEWAY_INTERNAL_SECRET,
            "ttl_seconds": SPLIT_INVOICE_TTL_SECONDS,
        },
        "gateway_deposit": {
            "default_usdc": GATEWAY_DEFAULT_DEPOSIT_USDC,
            "default_approve_usdc": GATEWAY_DEFAULT_APPROVE_USDC,
        },
        "withdraw": {
            "mode": WITHDRAW_MODE,
            "relayer_address": normalize_address(WITHDRAW_RELAYER_ADDRESS),
            "gateway_minter": ARC_GATEWAY_MINTER,
            "min_usdc": WITHDRAW_MIN_USDC,
            "daily_limit": WITHDRAW_RELAY_DAILY_LIMIT,
        },
        "creator_claim": {
            "mode": creator_claim_status.get("mode", "creator_initiated_hot_wallet_transfer"),
            "configured": bool(creator_claim_status.get("configured")),
            "executor": normalize_address(creator_claim_status.get("executor")),
            "relayer": normalize_address(creator_claim_status.get("relayer")),
            "treasury": normalize_address(creator_claim_status.get("treasury") or PLATFORM_TREASURY_ADDRESS),
            "min_usdc": CREATOR_CLAIM_MIN_USDC,
            "error": creator_claim_status.get("error"),
        },
        "roles": {
            "seller_wallet": normalize_address(PLATFORM_TREASURY_ADDRESS),
            "platform_treasury_wallet": normalize_address(PLATFORM_TREASURY_ADDRESS),
            "admin_wallet": normalize_address(ADMIN_WALLET_ADDRESS),
            "withdraw_relayer_address": normalize_address(WITHDRAW_RELAYER_ADDRESS),
        },
        "providers": [
            provider_metadata(provider_registry.require(provider["provider_id"]))
            for provider in provider_registry.list()
            if provider_control(provider["provider_id"])["enabled"]
        ],
        "require_completed_settlement": REQUIRE_COMPLETED_SETTLEMENT,
    }

@app.get("/api/v1/gateway/info")
def get_gateway_info(include_raw: bool = Query(default=False)):
    """Returns Circle Gateway capability diagnostics for QMA's current USDC-only runtime."""
    return fetch_gateway_info_cached(include_raw=include_raw)

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
        hydrate_payment_schema(invoice)
        if invoice_split_mode(invoice) == "x402_direct_split":
            for leg in invoice_required_split_legs(invoice):
                if leg.get("status") == "paid" and leg.get("settlement_id") and not any(event.get("settlement_id") == leg.get("settlement_id") for event in events):
                    events.append(split_leg_event(invoice, leg))
            continue
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
                "pricing": invoice.get("pricing"),
                "settlement": invoice.get("settlement"),
                "accounting": invoice.get("accounting"),
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
    creator_direct = sum(float(event.get("amount_usdc") or 0) for event in events if (event.get("split_leg") or {}).get("role") == "creator")
    platform_direct = sum(float(event.get("amount_usdc") or 0) for event in events if (event.get("split_leg") or {}).get("role") == "platform")
    direct_split = creator_direct > 0 or platform_direct > 0
    report_count = len({event.get("invoice_id") or payment_event_key(event) for event in events})
    earned = creator_direct if direct_split else revenue * share_bps / 10000
    claim_amounts = creator_claim_amounts(provider_id, provider.owner_wallet)
    claimable = 0.0 if direct_split else max(0.0, earned - claim_amounts["reserved_usdc"])
    revenue_wallet = provider_revenue_wallet(provider)
    creator_gateway_balance = fetch_gateway_balance_cached(revenue_wallet) if direct_split and revenue_wallet else None
    tier_counts = {"preview": 0, "full": 0, "legacy": 0}
    buyer_type_counts = {"human": 0, "agent": 0}
    top_symbols = {}
    for event in events:
        tier = payment_event_tier(event)
        report_key = event.get("invoice_id") or payment_event_key(event)
        if report_key not in tier_counts.setdefault("_seen", set()):
            tier_counts["_seen"].add(report_key)
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            buyer_type = event.get("buyer_type", "human")
            buyer_type_counts[buyer_type] = buyer_type_counts.get(buyer_type, 0) + 1
        if event.get("symbol"):
            top_symbols[event["symbol"]] = top_symbols.get(event["symbol"], 0) + 1
    tier_counts.pop("_seen", None)
    return {
        "provider_id": provider_id,
        "provider_name": provider.provider_name,
        "owner_wallet": provider.owner_wallet,
        "revenue_wallet": revenue_wallet,
        "status": getattr(provider, "status", "approved"),
        "payments": report_count,
        "revenue_usdc": round(revenue, 6),
        "creator_share_bps": share_bps,
        "creator_earned_usdc": round(earned, 6),
        "platform_fee_usdc": round(platform_direct if direct_split else revenue * (10000 - share_bps) / 10000, 6),
        "creator_claimable_usdc": round(claimable, 6),
        "creator_claimed_usdc": claim_amounts["paid_usdc"],
        "creator_claim_pending_usdc": claim_amounts["pending_usdc"],
        "creator_gateway_balance": creator_gateway_balance,
        "withdrawal_mode": "direct_gateway_split" if direct_split else "creator_initiated_claim_planned",
        "split_note": (
            "Direct Gateway split. Creator earnings settle directly to provider Gateway balance."
            if direct_split else
            "Ledger-backed creator claim. Gateway settles to platform treasury; payout execution is performed by the claim executor."
        ),
        "recent_claims": sorted(
            claim_amounts["records"],
            key=lambda item: item.get("requested_at") or 0,
            reverse=True,
        )[:10],
        "tier_counts": tier_counts,
        "buyer_type_counts": buyer_type_counts,
        "top_symbols": sorted(
            [{"symbol": symbol, "payments": count} for symbol, count in top_symbols.items()],
            key=lambda item: item["payments"],
            reverse=True,
        )[:8],
        "recent_payments": events[:10],
    }

def provider_ids_owned_by(address: str) -> list[str]:
    owner = normalize_address(address)
    owned = []
    for item in provider_registry.list():
        provider_id = item.get("provider_id")
        if not provider_id:
            continue
        try:
            provider = provider_registry.require(provider_id)
        except Exception:
            continue
        if same_address(provider.owner_wallet, owner):
            owned.append(provider_id)
    return sorted(owned)

def provider_ids_by_revenue_wallet(address: str) -> list[str]:
    wallet = normalize_address(address)
    matched = []
    for item in provider_registry.list():
        provider_id = item.get("provider_id")
        if not provider_id:
            continue
        try:
            provider = provider_registry.require(provider_id)
        except Exception:
            continue
        if same_address(provider_revenue_wallet(provider), wallet):
            matched.append(provider_id)
    return sorted(matched)

def authorized_gateway_withdraw_depositor(address: str) -> dict:
    depositor = normalize_address(address)
    if same_address(depositor, PAYMENT_WALLET_ADDRESS) or same_address(depositor, PLATFORM_TREASURY_ADDRESS):
        return {"address": depositor, "role": "platform_treasury", "provider_ids": []}
    provider_ids = provider_ids_by_revenue_wallet(depositor)
    if provider_ids:
        return {"address": depositor, "role": "provider_revenue_wallet", "provider_ids": provider_ids}
    raise HTTPException(status_code=403, detail="This wallet is not authorized to withdraw QMA Gateway balance.")

def allocate_creator_claim(provider_ids: list[str], amount_usdc: float) -> tuple[dict, list[dict]]:
    remaining = round(float(amount_usdc), 6)
    allocations = {}
    stats_rows = []
    for provider_id in provider_ids:
        stats = build_provider_stats(provider_id)
        available = round(float(stats.get("creator_claimable_usdc") or 0), 6)
        stats_rows.append(stats)
        if remaining <= 0:
            allocations[provider_id] = 0.0
            continue
        allocation = min(available, remaining)
        allocations[provider_id] = round(allocation, 6)
        remaining = round(remaining - allocation, 6)
    if remaining > 0.000001:
        raise HTTPException(status_code=400, detail="Claim amount exceeds available creator earnings.")
    return allocations, stats_rows

@app.post("/api/v1/creators/claim")
def create_creator_claim(payload: CreatorClaimRequest):
    """Creator-initiated claim: verify owner signature, debit ledger, and execute USDC payout."""
    claimant = normalize_address(payload.claimant_address)
    now = int(time.time())
    if payload.issued_at > now + 60 or now - payload.issued_at > CREATOR_CLAIM_INTENT_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="Creator claim intent expired. Reopen the claim modal and sign again.")

    requested_provider_ids = canonical_provider_ids(payload.provider_ids)
    owned_provider_ids = provider_ids_owned_by(claimant)
    if not owned_provider_ids:
        raise HTTPException(status_code=403, detail="This wallet does not own any approved QMA provider.")
    provider_ids = requested_provider_ids or owned_provider_ids
    unowned = [provider_id for provider_id in provider_ids if provider_id not in owned_provider_ids]
    if unowned:
        raise HTTPException(status_code=403, detail=f"Wallet does not own provider(s): {', '.join(unowned)}")

    with creator_claim_lock:
        reload_persistent_state(include_reports=False)
        stats_rows = [build_provider_stats(provider_id) for provider_id in provider_ids]
        total_available = round(sum(float(row.get("creator_claimable_usdc") or 0) for row in stats_rows), 6)
        requested_amount = round(float(payload.amount_usdc or total_available), 6)
        if requested_amount <= 0:
            raise HTTPException(status_code=400, detail="No creator earnings are available to claim.")
        if CREATOR_CLAIM_MIN_USDC > 0 and requested_amount < CREATOR_CLAIM_MIN_USDC:
            raise HTTPException(
                status_code=400,
                detail=f"Minimum creator claim is {CREATOR_CLAIM_MIN_USDC:.6f} USDC.",
            )
        if requested_amount > total_available + 0.000001:
            raise HTTPException(status_code=400, detail="Claim amount exceeds available creator earnings.")

        message = build_creator_claim_message(
            claimant_address=claimant,
            provider_ids=provider_ids,
            amount_usdc=requested_amount,
            nonce=payload.nonce,
            issued_at=payload.issued_at,
        )
        signer = recover_creator_claim_signer(message, payload.signature)
        if not same_address(signer, claimant):
            raise HTTPException(status_code=403, detail="Creator claim signature does not match claimant wallet.")

        allocations, stats_rows = allocate_creator_claim(provider_ids, requested_amount)
        claim_id = f"claim_{uuid.uuid4().hex}"
        record = {
            "claim_id": claim_id,
            "claimant_address": claimant,
            "provider_ids": provider_ids,
            "amount_usdc": requested_amount,
            "allocations": allocations,
            "status": "requested",
            "requested_at": time.time(),
            "nonce": payload.nonce,
            "signature": payload.signature,
            "message": message,
        }
        creator_claims_db.append(record)
        if not save_creator_claim_record(record):
            raise HTTPException(status_code=500, detail="Could not persist creator claim request.")

    try:
        headers = {"Content-Type": "application/json"}
        if ARC_GATEWAY_INTERNAL_SECRET:
            headers["x-qma-internal-secret"] = ARC_GATEWAY_INTERNAL_SECRET
        resp = requests.post(
            f"{ARC_GATEWAY_BASE_URL.rstrip('/')}/api/creator/claim",
            json={
                "claimId": record["claim_id"],
                "recipient": claimant,
                "amountUsdc": f"{requested_amount:.6f}",
                "providerIds": provider_ids,
            },
            headers=headers,
            timeout=120,
        )
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if not resp.ok or data.get("error"):
            raise HTTPException(
                status_code=502,
                detail=data.get("error") or f"Claim payout executor returned {resp.status_code}: {resp.text[:240]}",
            )
        record.update({
            "status": "paid",
            "paid_at": time.time(),
            "transaction_hash": data.get("transaction_hash"),
            "explorer_url": data.get("explorer_url"),
            "payout_executor": data.get("payout_executor") or data.get("relayer"),
        })
        save_creator_claim_record(record)
        reload_persistent_state(include_reports=False)
        return {
            "status": "success",
            "claim": record,
            "message": "Creator claim paid on-chain.",
        }
    except HTTPException as exc:
        record.update({
            "status": "failed",
            "failed_at": time.time(),
            "error": exc.detail,
        })
        save_creator_claim_record(record)
        reload_persistent_state(include_reports=False)
        raise
    except Exception as exc:
        record.update({
            "status": "failed",
            "failed_at": time.time(),
            "error": str(exc),
        })
        save_creator_claim_record(record)
        reload_persistent_state(include_reports=False)
        raise HTTPException(status_code=502, detail=f"Creator claim payout failed: {exc}")

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
        "revenue_by_provider": summary["revenue_by_provider"],
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
        hydrate_payment_schema(invoice)
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
                "pricing": invoice.get("pricing"),
                "settlement": invoice.get("settlement"),
                "accounting": invoice.get("accounting"),
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
        hydrate_payment_schema(invoice)
        key = str(invoice.get("settlement_id") or invoice.get("invoice_id") or "")
        if key and key not in existing_keys:
            # For split invoices, derive aggregate gateway_status from legs instead of
            # the frozen "received" status that was written at verify time.
            invoice_gateway_status = invoice.get("gateway_status")
            if invoice_split_mode(invoice) == "x402_direct_split":
                legs = invoice_required_split_legs(invoice)
                paid_legs = [leg for leg in legs if leg.get("status") == "paid"]
                if paid_legs and len(paid_legs) == len(legs):
                    leg_statuses = {str(leg.get("gateway_status") or "").lower() for leg in paid_legs}
                    if leg_statuses <= {"completed", "confirmed"}:
                        invoice_gateway_status = "completed"
                    elif leg_statuses & {"completed", "confirmed", "batched"}:
                        invoice_gateway_status = "batched"
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
                "pricing": invoice.get("pricing"),
                "settlement": invoice.get("settlement"),
                "accounting": invoice.get("accounting"),
                "settlement_id": invoice.get("settlement_id"),
                "gateway_status": invoice_gateway_status,
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

@app.get("/api/v1/market-data/cache")
def get_market_data_cache(
    symbol: Optional[str] = Query(default=None),
    refresh: bool = Query(default=False),
):
    """Debugs the active market-data adapter cache, e.g. MEXC detailV2 contract size (cs)."""
    normalized_symbol = str(symbol or "").strip().upper() or None
    if normalized_symbol and "_" not in normalized_symbol:
        normalized_symbol = f"{normalized_symbol}_USDT"
    if not hasattr(market_data_adapter, "cache_status"):
        return {
            "source": getattr(market_data_adapter, "source_id", "unknown"),
            "cache_supported": False,
        }
    return market_data_adapter.cache_status(symbol=normalized_symbol, refresh=refresh)

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
        for provider in enabled_providers:
            query_payload = normalize_query_for_provider(provider, item)
            turnover_pct = (volume / market_cap) * 100
            open_interest = float(query_payload.get("amount") or query_payload.get("openInterest") or 0)
            oi_pct = (open_interest / market_cap) * 100
            structure_score = min(20.0, max(0.0, 1.0 - abs(circ - 0.65)) * 20)
            discount_score = min(10.0, ath / 10)
            reasons = []
            if provider.provider_id == "oi_memory":
                turnover_score = min(55.0, oi_pct * 3)
                funding_score = min(15.0, funding_pct * 6)
                volume_score = min(10.0, turnover_pct * 0.5)
                score = round(min(100.0, turnover_score + volume_score + funding_score + structure_score + discount_score), 1)
                if oi_pct >= 20:
                    reasons.append("very high open-interest crowding")
                elif oi_pct >= 8:
                    reasons.append("elevated open-interest crowding")
                elif oi_pct >= 2:
                    reasons.append("usable open-interest context")
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
    req_data = normalize_query_for_provider(provider, req_data)
    quote = provider.quote_price(req_data, tier)
    return {
        "status": "success",
        "pricing": paid_kit.pricing_config(),
        **quote,
    }

def require_internal_gateway_secret(x_qma_internal_secret: Optional[str] = None):
    if not ARC_GATEWAY_INTERNAL_SECRET:
        raise HTTPException(status_code=503, detail="QMA_ARC_GATEWAY_INTERNAL_SECRET is not configured.")
    if not hmac.compare_digest(str(x_qma_internal_secret or ""), ARC_GATEWAY_INTERNAL_SECRET):
        raise HTTPException(status_code=403, detail="Internal gateway secret required.")
    return True

@app.get("/api/internal/invoices/{invoice_id}/split-leg/{leg_id}")
def get_internal_split_leg(
    invoice_id: str,
    leg_id: str,
    x_qma_internal_secret: Optional[str] = Header(default=None),
):
    require_internal_gateway_secret(x_qma_internal_secret)
    invoice = invoices_db.get(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    refresh_split_invoice_status(invoice)
    leg = split_leg_by_id(invoice, leg_id)
    if not leg:
        raise HTTPException(status_code=404, detail="Split leg not found.")
    save_invoice(invoice)
    return {
        "status": "success",
        "invoice": {
            "invoice_id": invoice_id,
            "status": invoice.get("status"),
            "provider_id": invoice.get("provider_id"),
            "tier": invoice.get("tier"),
            "expires_at": invoice.get("expires_at"),
            "settlement_mode": invoice_split_mode(invoice),
        },
        "leg": leg,
    }

@app.post("/api/internal/invoices/{invoice_id}/split-leg/{leg_id}/reserve")
def reserve_internal_split_leg(
    invoice_id: str,
    leg_id: str,
    x_qma_internal_secret: Optional[str] = Header(default=None),
):
    require_internal_gateway_secret(x_qma_internal_secret)
    with split_leg_lock:
        invoice = invoices_db.get(invoice_id)
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found.")
        status_value = refresh_split_invoice_status(invoice)
        if status_value in {"paid", "expired"}:
            save_invoice(invoice)
            raise HTTPException(status_code=409, detail=f"Invoice is {status_value}.")
        leg = split_leg_by_id(invoice, leg_id)
        if not leg:
            raise HTTPException(status_code=404, detail="Split leg not found.")
        if leg.get("status") == "paid" and leg.get("settlement_id"):
            raise HTTPException(status_code=409, detail="Split leg is already settled.")
        processing_until = float(leg.get("processing_until") or 0)
        if leg.get("status") == "processing" and processing_until > time.time():
            raise HTTPException(status_code=409, detail="Split leg settlement is already in progress.")
        leg["status"] = "processing"
        leg["processing_until"] = time.time() + 120
        leg["reserved_at"] = time.time()
        save_invoice(invoice)
        return {"status": "reserved", "invoice_id": invoice_id, "leg_id": leg_id, "leg": leg}

@app.post("/api/internal/invoices/{invoice_id}/split-leg/{leg_id}/release")
def release_internal_split_leg(
    invoice_id: str,
    leg_id: str,
    x_qma_internal_secret: Optional[str] = Header(default=None),
):
    require_internal_gateway_secret(x_qma_internal_secret)
    with split_leg_lock:
        invoice = invoices_db.get(invoice_id)
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found.")
        leg = split_leg_by_id(invoice, leg_id)
        if not leg:
            raise HTTPException(status_code=404, detail="Split leg not found.")
        if leg.get("status") == "processing":
            leg["status"] = "pending"
            leg.pop("processing_until", None)
        refresh_split_invoice_status(invoice)
        save_invoice(invoice)
        return {"status": "released", "invoice_id": invoice_id, "leg_id": leg_id, "leg": leg}

@app.post("/api/internal/invoices/{invoice_id}/split-leg/{leg_id}/record")
def record_internal_split_leg(
    invoice_id: str,
    leg_id: str,
    payload: dict,
    x_qma_internal_secret: Optional[str] = Header(default=None),
):
    require_internal_gateway_secret(x_qma_internal_secret)
    with split_leg_lock:
        invoice = invoices_db.get(invoice_id)
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found.")
        leg = split_leg_by_id(invoice, leg_id)
        if not leg:
            raise HTTPException(status_code=404, detail="Split leg not found.")
        if leg.get("status") == "paid" and leg.get("settlement_id"):
            raise HTTPException(status_code=409, detail="Split leg is already settled.")
        settled_amount_raw = raw_usdc_str(payload.get("amount_raw") or payload.get("settled_amount_raw") or "0")
        if settled_amount_raw != raw_usdc_str(leg.get("amount_raw")):
            raise HTTPException(status_code=400, detail="Settled split leg amount does not match invoice leg.")
        if normalize_address(payload.get("pay_to")) != normalize_address(leg.get("pay_to")):
            raise HTTPException(status_code=400, detail="Settled split leg pay_to does not match invoice leg.")
        settlement_id = str(payload.get("settlement_id") or "")
        if not settlement_id:
            raise HTTPException(status_code=400, detail="settlement_id is required.")
        receipt = str(payload.get("sidecar_receipt") or "")
        if not verify_split_receipt(
            invoice_id=invoice_id,
            leg_id=leg_id,
            pay_to=leg.get("pay_to"),
            settled_amount_raw=settled_amount_raw,
            settlement_id=settlement_id,
            receipt=receipt,
        ):
            raise HTTPException(status_code=400, detail="Invalid split leg sidecar receipt.")
        leg.update({
            "status": "paid",
            "settlement_id": settlement_id,
            "payer_address": normalize_address(payload.get("payer_address")),
            "gateway_status": payload.get("gateway_status"),
            "transaction_hash": payload.get("transaction_hash"),
            "explorer_url": payload.get("explorer_url"),
            "paid_at": time.time(),
            "sidecar_receipt": receipt,
        })
        leg.pop("processing_until", None)
        refresh_split_invoice_status(invoice)
        save_invoice(invoice)
        return {"status": "recorded", "invoice_id": invoice_id, "leg_id": leg_id, "invoice_status": invoice.get("status"), "leg": leg}

@app.post("/api/v1/payment/invoice")
def create_invoice(req: InvoiceRequest):
    """Creates a QMA invoice bound to a Circle x402 Arc Testnet payment."""
    req_data = model_to_dict(req)
    provider_id = req_data.pop("provider_id", "funding_memory")
    buyer_type = req_data.pop("buyer_type", "human")
    tier = paid_kit.normalize_tier(req_data.pop("tier", "full"))
    resource_type = req_data.pop("resource_type", PAYMENT_RESOURCE_TYPE) or PAYMENT_RESOURCE_TYPE
    synthetic = bool(req_data.pop("synthetic", False))
    agent_label = req_data.pop("agent_label", None)
    run_source = req_data.pop("run_source", None)
    provider = get_provider_or_404(provider_id)
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
    settlement_mode = provider_settlement_mode(provider)
    invoice["settlement"]["mode"] = settlement_mode
    invoice["accounting"] = {
        **invoice.get("accounting", {}),
        "settlement_mode": settlement_mode,
        "creator_wallet": provider_revenue_wallet(provider),
        "creator_share_bps": int(getattr(provider, "revenue_share_bps", 8000)),
        "platform_share_bps": 10000 - int(getattr(provider, "revenue_share_bps", 8000)),
    }
    invoice["wallet_address"] = PLATFORM_TREASURY_ADDRESS
    invoice["platform_treasury_wallet"] = normalize_address(PLATFORM_TREASURY_ADDRESS)
    invoice["synthetic"] = synthetic
    invoice["agent_label"] = agent_label
    invoice["run_source"] = run_source
    if settlement_mode == "x402_direct_split":
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
        requirement["settlement"]["mode"] = settlement_mode
        requirement["pay_to"] = None
    invoices_db[invoice["invoice_id"]] = invoice
    save_invoice(invoice)
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

def verify_split_payment(invoice_id: str, invoice: dict, proof: PaymentVerifyRequest):
    refresh_split_invoice_status(invoice)
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
        save_invoice(invoice)
        raise HTTPException(status_code=402, detail=f"Missing split settlement leg(s): {', '.join(missing)}")

    payer = normalize_address(proof.payer_address)
    verified_legs = []
    with split_leg_lock:
        for leg in required_legs:
            leg_id = leg.get("leg_id")
            submitted = provided.get(leg_id)
            if not submitted:
                continue
            if raw_usdc_str(submitted.amount_raw) != raw_usdc_str(leg.get("amount_raw")):
                raise HTTPException(status_code=400, detail=f"Split leg {leg_id} amount does not match invoice.")
            if normalize_address(submitted.pay_to) != normalize_address(leg.get("pay_to")):
                raise HTTPException(status_code=400, detail=f"Split leg {leg_id} pay_to does not match invoice.")
            if not verify_split_receipt(
                invoice_id=invoice_id,
                leg_id=leg_id,
                pay_to=leg.get("pay_to"),
                settled_amount_raw=submitted.amount_raw,
                settlement_id=submitted.settlement_id,
                receipt=submitted.sidecar_receipt,
            ):
                raise HTTPException(status_code=400, detail=f"Invalid sidecar receipt for split leg {leg_id}.")
            settlement = fetch_circle_settlement(submitted.settlement_id)
            validate_arc_split_leg_payment(invoice, leg, settlement, payer_address=proof.payer_address)
            settlement_payer = normalize_address(settlement.get("fromAddress"))
            if payer and settlement_payer != payer:
                raise HTTPException(status_code=400, detail="Split settlement payer mismatch.")
            payer = payer or settlement_payer
            batch = find_arc_batch_tx(settlement)
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
            save_invoice(invoice)
            raise HTTPException(status_code=402, detail="Invoice is partially paid. Complete all split legs before unlock.")

        invoice["status"] = "paid"
        invoice["paid_at"] = time.time()
        invoice["payer_address"] = payer
        invoice["settlement_id"] = f"split:{invoice_id}"
        invoice["split_settlement_ids"] = [leg.get("settlement_id") for leg in required_legs]
        invoice["gateway_status"] = "received"
        invoice["amount_raw"] = (invoice.get("split") or {}).get("total_amount_raw")
        invoice["verification_mode"] = "circle-gateway-x402-direct-split"
        save_invoice(invoice)

    reload_persistent_state(include_reports=False)
    for leg in required_legs:
        upsert_payment_event(split_leg_event(invoice, leg))
    save_payment_ledger(payment_events)
    save_invoice(invoice)

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
        "settlement": invoice.get("settlement"),
        "accounting": invoice.get("accounting"),
    })
    return {
        "invoice_id": invoice_id,
        "status": invoice["status"],
        "amount": invoice.get("amount"),
        "amount_usdc": invoice.get("amount"),
        "currency": invoice.get("settlement", {}).get("currency", "USDC"),
        "pricing": invoice.get("pricing"),
        "settlement": invoice.get("settlement"),
        "split": invoice.get("split"),
        "accounting": invoice.get("accounting"),
        "gateway_status": invoice.get("gateway_status"),
        "settlement_id": invoice.get("settlement_id"),
        "split_settlement_ids": invoice.get("split_settlement_ids"),
        "payer_address": invoice.get("payer_address"),
        "provider_id": invoice.get("provider_id", "funding_memory"),
        "buyer_type": invoice.get("buyer_type", "human"),
        "tier": invoice.get("tier", "full"),
        "tier_label": paid_kit.SUPPORTED_TIERS[paid_kit.normalize_tier(invoice.get("tier", "full"))]["label"],
        "resource_type": invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
        "provider_owner_wallet": invoice.get("owner_wallet"),
        "seller_wallet": PLATFORM_TREASURY_ADDRESS,
        "circle_deposit_contract": ARC_GATEWAY_WALLET,
        "transaction_hash": None,
        "explorer_url": None,
        "verification_mode": invoice["verification_mode"],
        "access_token": access_token,
        "access_token_expires_in": ACCESS_TOKEN_TTL_SECONDS,
        "require_completed_settlement": REQUIRE_COMPLETED_SETTLEMENT,
        "message": "Direct x402 split verified. Creator and platform legs settled.",
    }

@app.post("/api/v1/payment/verify")
def verify_payment(invoice_id: str = Query(...), proof: Optional[PaymentVerifyRequest] = None):
    """Verifies a real Circle Gateway x402 settlement on Arc Testnet."""
    if proof is None:
        raise HTTPException(status_code=400, detail="payment proof is required.")
    invoice = get_invoice_or_402(invoice_id)
    hydrate_payment_schema(invoice)
    if not hmac.compare_digest(str(proof.invoice_secret), str(invoice.get("invoice_secret"))):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invoice secret mismatch.")
    if invoice_split_mode(invoice) == "x402_direct_split" or proof.split_settlements:
        return verify_split_payment(invoice_id, invoice, proof)
    if not proof.settlement_id:
        raise HTTPException(status_code=400, detail="settlement_id is required.")
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
        "settlement": invoice.get("settlement"),
        "accounting": invoice.get("accounting"),
    })
    return {
        "invoice_id": invoice_id,
        "status": invoice["status"],
        "amount": invoice.get("amount"),
        "amount_usdc": invoice.get("amount"),
        "currency": invoice.get("settlement", {}).get("currency", "USDC"),
        "pricing": invoice.get("pricing"),
        "settlement": invoice.get("settlement"),
        "accounting": invoice.get("accounting"),
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
    """Submits a signed BurnIntent authorization to Circle Gateway for withdrawal.

    In seller_wallet mode, the browser receives a mint attestation and sends
    gatewayMint itself. In platform_relayed mode, the Arc sidecar relays
    gatewayMint with the platform hot wallet so the seller does not pay gas.
    """
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
                json={
                    "burnIntent": burn_intent,
                    "signature": signature,
                    "expectedDepositor": expected_depositor,
                },
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
            return {
                **data,
                "withdraw_mode": "seller_wallet",
                "relayed": False,
                "amount_usdc": f"{intent['amount_usdc']:.6f}",
                "withdraw_owner": withdraw_owner,
            }
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
    query: dict,
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
    if invoice["symbol"].upper() != str(query.get("symbol", "")).upper():
        raise HTTPException(status_code=400, detail="Invoice symbol does not match query symbol.")
    current_query_hash = query_fingerprint(query)
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
        "provider_note": full_report.get("provider_note"),
        "analysis_focus": full_report.get("analysis_focus"),
        "turnover_context": full_report.get("turnover_context"),
        "provider_diagnostics": full_report.get("provider_diagnostics"),
    }

def invoice_report_meta(invoice_id: str, invoice: dict) -> dict:
    hydrate_payment_schema(invoice)
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
        "pricing": invoice.get("pricing"),
        "settlement": invoice.get("settlement"),
        "accounting": invoice.get("accounting"),
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
    normalized_query = normalize_query_for_provider(provider, model_to_dict(query))
    invoice = authorize_paid_invoice(
        query=normalized_query,
        invoice_id=invoice_id,
        token=token,
        required_tier=required_tier,
        provider_id=provider.provider_id,
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

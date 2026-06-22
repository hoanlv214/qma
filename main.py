import os
import time
import uuid
import requests
import logging
import json
import base64
import hashlib
import hmac
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException, status, Query, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Import QMA Engine
try:
    from qma_engine import QMAEngine
except ImportError:
    from qma.qma_engine import QMAEngine

try:
    import paid_intelligence_kit as paid_kit
except ImportError:
    from qma import paid_intelligence_kit as paid_kit

try:
    from providers import create_default_registry
except ImportError:
    from qma.providers import create_default_registry

try:
    from storage import create_storage_backend
except ImportError:
    from qma.storage import create_storage_backend

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
ACCESS_TOKEN_SECRET = os.getenv("QMA_ACCESS_TOKEN_SECRET") or os.getenv("QMA_SESSION_SECRET") or "qma-local-demo-secret-change-me"
ADMIN_TOKEN = os.getenv("QMA_ADMIN_TOKEN", "")
RATE_LIMIT_ENABLED = os.getenv("QMA_RATE_LIMIT_ENABLED", "true").lower() not in ("false", "0", "no")
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("QMA_RATE_LIMIT_WINDOW_SECONDS", "60"))
# Strict mode: if True, /analyze is blocked until Circle batch is "completed"/"confirmed".
# Default False = unlock immediately on "received" (x402 UX). Set to "true" in .env for strict.
REQUIRE_COMPLETED_SETTLEMENT = os.getenv("QMA_REQUIRE_COMPLETED_SETTLEMENT", "false").lower() in ("true", "1", "yes")
provider_registry = create_default_registry(engine=engine, default_owner_wallet=PAYMENT_WALLET_ADDRESS)
storage_backend = create_storage_backend(
    ledger_path=PAYMENT_LEDGER_PATH,
    reports_path=PAID_REPORTS_PATH,
    invoices_path=INVOICES_PATH,
    creators_path=CREATOR_APPLICATIONS_PATH,
)

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

# format: {invoice_id: {"status": "pending"|"paid", "created_at": float, "symbol": str}}
invoices_db: Dict[str, dict] = load_invoices()
creator_applications: Dict[str, dict] = load_creator_applications()

def reload_persistent_state(include_invoices: bool = False) -> None:
    global payment_events, paid_reports, invoices_db
    payment_events = load_payment_ledger()
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

class PaymentVerifyRequest(BaseModel):
    settlement_id: str = Field(..., min_length=8)
    invoice_secret: str = Field(..., min_length=16)
    payer_address: Optional[str] = None
    amount_usdc: Optional[float] = None

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

def find_arc_batch_tx(settlement: dict) -> dict:
    status_value = settlement.get("status")
    if status_value not in {"completed", "confirmed"}:
        return {
            "batch_tx": None,
            "explorer_url": None,
            "status": status_value,
            "message": "Circle accepted the payment authorization; on-chain batch tx is still pending.",
        }

    try:
        resp = requests.get(
            f"{ARC_EXPLORER}/api/v2/addresses/{ARC_GATEWAY_WALLET}/transactions",
            params={"filter": "to"},
            timeout=10,
        )
    except requests.RequestException as exc:
        return {
            "batch_tx": None,
            "explorer_url": None,
            "status": status_value,
            "message": f"Arcscan lookup failed: {exc}",
        }
    if not resp.ok:
        return {
            "batch_tx": None,
            "explorer_url": None,
            "status": status_value,
            "message": f"Arcscan returned {resp.status_code}",
        }

    updated_at = settlement.get("updatedAt")
    if not updated_at:
        return {"batch_tx": None, "explorer_url": None, "status": status_value}

    updated_ts = parse_iso_utc(updated_at)

    for tx in resp.json().get("items", []):
        if tx.get("method") != "submitBatch":
            continue
        tx_ts = parse_iso_utc(tx.get("timestamp", ""))
        if not tx_ts:
            continue
        if tx_ts <= updated_ts + 5:
            tx_hash = tx.get("hash")
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

# Live Scanner Helpers
def scan_mexc_live() -> list:
    """Scans MEXC Futures tickers in real-time, matching against introduce parameters"""
    try:
        ticker_resp = requests.get("https://futures.mexc.com/api/v1/contract/ticker", timeout=5).json()
        tickers = ticker_resp.get("data", [])
        if not tickers:
            return []
            
        anomalies = []
        # Filter for negative funding rate of <= -0.25% to catch signals
        filtered_tickers = [t for t in tickers if float(t.get("fundingRate", 0)) <= -0.0025]
        
        # Sort by most negative funding rate and take top 12 to prevent rate limits
        filtered_tickers = sorted(filtered_tickers, key=lambda x: float(x.get("fundingRate", 0)))[:12]

        for ticker in filtered_tickers:
            symbol = ticker["symbol"].replace("_USDT", "")
            contract_id = ticker["contractId"]
            
            # Fetch coin details
            try:
                intro_params = {"language": "vi-VN", "contractId": contract_id}
                intro_resp = requests.get("https://www.mexc.com/api/activity/contract/coin/introduce/v2", params=intro_params, timeout=3).json()
                info = intro_resp.get("data", {})
            except Exception as e:
                logger.error(f"Error fetching contract info for {symbol}: {e}")
                info = {}

            last_price = float(ticker["lastPrice"])
            funding_rate = float(ticker["fundingRate"])
            hold_vol = float(ticker["holdVol"])

            # Read parameters with safe fallbacks
            volume_24h = float(info.get("volume24h", 0)) if info.get("volume24h") else hold_vol * last_price * 0.2
            circulation = float(info.get("circulationAmount", 0)) if info.get("circulationAmount") else 100000000.0
            issue = float(info.get("issueAmount", 0)) if info.get("issueAmount") else circulation * 1.5

            market_cap = circulation * last_price if circulation else 10000000.0
            fdv = issue * last_price if issue else market_cap * 1.5
            circ_ratio = (circulation / issue) if (circulation and issue) else 0.5

            ath = float(info.get("historicalHigh", 0)) if info.get("historicalHigh") else last_price * 2.0
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

@app.get("/marketplace", response_class=HTMLResponse)
def get_marketplace():
    """Serves the creator/provider marketplace UI."""
    return serve_html_file("marketplace.html", "<h1>QMA Marketplace File not found</h1>", status_code=404)

@app.get("/api/v1/health")
def get_health():
    seller_balance = fetch_gateway_balance(PAYMENT_WALLET_ADDRESS)
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
        "pricing": {
            "preview_usdc": paid_kit.tier_price("preview"),
            "full_usdc": paid_kit.tier_price("full"),
        },
        "providers": provider_registry.list(),
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

def get_provider_or_404(provider_id: str):
    try:
        return provider_registry.require(provider_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown intelligence provider: {provider_id}")

def require_admin_token(x_qma_admin_token: Optional[str] = None):
    if ADMIN_TOKEN and not hmac.compare_digest(str(x_qma_admin_token or ""), ADMIN_TOKEN):
        raise HTTPException(status_code=403, detail="Admin token required.")
    return True

def payment_events_for_provider(provider_id: str) -> list:
    reload_persistent_state()
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
    provider = get_provider_or_404(provider_id)
    events = payment_events_for_provider(provider_id)
    revenue = sum(float(event.get("amount_usdc") or 0) for event in events)
    share_bps = int(getattr(provider, "revenue_share_bps", 8000))
    tier_counts = {"preview": 0, "full": 0}
    buyer_type_counts = {"human": 0, "agent": 0}
    top_symbols = {}
    for event in events:
        tier = paid_kit.normalize_tier(event.get("tier") or "full")
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
def list_providers():
    """Lists paid intelligence providers available to human users and external agents."""
    return {
        "status": "success",
        "providers": [
            {
                **provider,
                "stats": build_provider_stats(provider["provider_id"]),
            }
            for provider in provider_registry.list()
        ],
    }

@app.get("/api/v1/providers/{provider_id}")
def get_provider(provider_id: str):
    """Returns provider metadata, pricing, schemas, owner wallet, and supported report types."""
    return {
        "status": "success",
        "provider": get_provider_or_404(provider_id).metadata(),
    }

@app.get("/api/v1/providers/{provider_id}/stats")
def get_provider_stats(provider_id: str):
    """Returns creator-facing sales, revenue split, and recent payment stats for one provider."""
    return {
        "status": "success",
        "stats": build_provider_stats(provider_id),
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
    reload_persistent_state()
    is_admin = bool(ADMIN_TOKEN and hmac.compare_digest(str(x_qma_admin_token or ""), ADMIN_TOKEN))
    if not wallet and not is_admin:
        raise HTTPException(status_code=403, detail="Pass wallet=0x... or admin token.")
    normalized_wallet = normalize_address(wallet)
    records = list(load_creator_applications().values())
    if wallet and not is_admin:
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
    reload_persistent_state()
    refresh_unresolved_payment_events()
    paid_invoices = [invoice for invoice in invoices_db.values() if invoice.get("status") == "paid"]
    all_events = payment_events + [
        {
            "invoice_id": invoice.get("invoice_id"),
            "symbol": invoice.get("symbol"),
            "provider_id": invoice.get("provider_id", "funding_memory"),
            "provider_owner_wallet": invoice.get("owner_wallet"),
            "buyer_type": invoice.get("buyer_type", "human"),
            "tier": invoice.get("tier", "full"),
            "resource_type": invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
            "payer_address": invoice.get("payer_address"),
            "amount_usdc": invoice.get("amount"),
            "settlement_id": invoice.get("settlement_id"),
            "gateway_status": invoice.get("gateway_status"),
            "paid_at": invoice.get("paid_at"),
        }
        for invoice in paid_invoices
        if invoice.get("settlement_id")
    ]
    unique_events = {}
    for event in all_events:
        key = event.get("settlement_id") or event.get("invoice_id")
        if key:
            current = unique_events.get(key, {})
            merged = {**current, **event}
            for field in ("seller_address", "amount_raw", "transaction_hash", "explorer_url"):
                if current.get(field) and not event.get(field):
                    merged[field] = current[field]
            if current.get("gateway_status") == "completed" and event.get("gateway_status") != "completed":
                merged["gateway_status"] = current["gateway_status"]
            unique_events[key] = merged
    events = sorted(unique_events.values(), key=lambda item: item.get("paid_at") or 0, reverse=True)
    unique_payers = {normalize_address(event.get("payer_address")) for event in events if event.get("payer_address")}
    revenue = sum(float(event.get("amount_usdc") or 0) for event in events)
    tier_counts = {"preview": 0, "full": 0}
    buyer_type_counts = {"human": 0, "agent": 0}
    revenue_by_tier = {"preview": 0.0, "full": 0.0}
    revenue_by_provider = {}
    top_symbols = {}
    payer_stats = {}
    for event in events:
        tier = paid_kit.normalize_tier(event.get("tier") or "full")
        provider_id = event.get("provider_id", "funding_memory")
        buyer_type = event.get("buyer_type", "human")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        buyer_type_counts[buyer_type] = buyer_type_counts.get(buyer_type, 0) + 1
        revenue_by_tier[tier] = revenue_by_tier.get(tier, 0.0) + float(event.get("amount_usdc") or 0)
        provider_stats = revenue_by_provider.setdefault(provider_id, {
            "provider_id": provider_id,
            "owner_wallet": event.get("provider_owner_wallet") or event.get("seller_address"),
            "payments": 0,
            "revenue_usdc": 0.0,
        })
        provider_stats["payments"] += 1
        provider_stats["revenue_usdc"] += float(event.get("amount_usdc") or 0)
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
        stats["spent_usdc"] += float(event.get("amount_usdc") or 0)
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
    payer_breakdown = sorted(payer_breakdown, key=lambda item: item["spent_usdc"], reverse=True)
    recent_payments, recent_payments_page = paginate_items(events, payment_page, payment_page_size)
    payer_breakdown_page_items, payer_breakdown_page = paginate_items(payer_breakdown, payer_page, payer_page_size)
    seller_balance = fetch_gateway_balance(PAYMENT_WALLET_ADDRESS)
    return {
        "seller_address": PAYMENT_WALLET_ADDRESS,
        "seller_gateway_balance": seller_balance,
        "invoice_count": len(invoices_db),
        "paid_count": len(events),
        "unique_payers": len(unique_payers),
        "revenue_usdc": revenue,
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
        "payer_breakdown": payer_breakdown_page_items,
        "payer_breakdown_page": payer_breakdown_page,
        "recent_payments": recent_payments,
        "recent_payments_page": recent_payments_page,
    }

@app.get("/api/v1/metrics/wallet/{address}")
def get_wallet_metrics(
    address: str,
    payment_page: int = Query(default=1, ge=1),
    payment_page_size: int = Query(default=10, ge=1, le=100),
    entitlement_page: int = Query(default=1, ge=1),
    entitlement_page_size: int = Query(default=50, ge=1, le=100),
):
    reload_persistent_state()
    refresh_unresolved_payment_events()
    normalized = normalize_address(address)
    events = [
        event for event in payment_events
        if normalize_address(event.get("payer_address")) == normalized
    ]
    paid_invoices = [
        invoice for invoice in invoices_db.values()
        if normalize_address(invoice.get("payer_address")) == normalized
        and invoice.get("status") == "paid"
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
    tier_counts = {"preview": 0, "full": 0}
    buyer_type_counts = {"human": 0, "agent": 0}
    provider_counts = {}
    for event in events:
        tier = paid_kit.normalize_tier(event.get("tier") or "full")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        buyer_type = event.get("buyer_type", "human")
        buyer_type_counts[buyer_type] = buyer_type_counts.get(buyer_type, 0) + 1
        provider_id = event.get("provider_id", "funding_memory")
        provider_counts[provider_id] = provider_counts.get(provider_id, 0) + 1
    entitlements = paid_kit.list_wallet_entitlements(paid_reports, address)
    recent_payments, recent_payments_page = paginate_items(events, payment_page, payment_page_size)
    entitlement_items, entitlements_page = paginate_items(entitlements, entitlement_page, entitlement_page_size)
    return {
        "address": address,
        "gateway_balance": fetch_gateway_balance(address),
        "payments": len(events),
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

@app.get("/api/v1/entitlements/wallet/{address}")
def get_wallet_entitlements(
    address: str,
    symbol: Optional[str] = Query(default=None),
    provider_id: Optional[str] = Query(default=None),
):
    reload_persistent_state()
    records = paid_kit.list_wallet_entitlements(paid_reports, address, symbol=symbol, provider_id=provider_id)
    return {
        "address": address,
        "symbol": symbol,
        "provider_id": provider_id,
        "count": len(records),
        "entitlements": records[:100],
    }

@app.get("/api/v1/live-anomalies")
def get_live_anomalies():
    """Returns real-time MEXC funding anomalies with caching"""
    now = time.time()
    if now - live_anomalies_cache["last_updated"] > CACHE_TTL_SECONDS:
        logger.info("Cache expired. Scanning MEXC live...")
        live_anomalies_cache["data"] = scan_mexc_live()
        live_anomalies_cache["last_updated"] = now
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
    for item in anomalies:
        funding_pct = abs(float(item.get("fundingRate") or 0) * 100)
        volume = float(item.get("volume24h") or 0)
        market_cap = max(float(item.get("marketCap") or 0), 1)
        circ = float(item.get("circRatio") or 0)
        ath = abs(float(item.get("fromATH") or 0))
        volume_score = min(25.0, (volume / market_cap) * 100)
        funding_score = min(45.0, funding_pct * 18)
        structure_score = min(20.0, max(0.0, 1.0 - abs(circ - 0.65)) * 20)
        discount_score = min(10.0, ath / 10)
        score = round(min(100.0, funding_score + volume_score + structure_score + discount_score), 1)
        reasons = []
        if funding_pct >= 0.5:
            reasons.append("extreme negative funding")
        elif funding_pct >= 0.25:
            reasons.append("notable funding anomaly")
        if volume / market_cap >= 0.02:
            reasons.append("meaningful turnover")
        if 0.2 <= circ <= 1.0:
            reasons.append("usable circulating supply profile")
        if ath >= 50:
            reasons.append("deep drawdown context")
        suggested_tier = "full" if score >= 65 else "preview"
        picks.append({
            "provider_id": "funding_memory",
            "provider_name": get_provider_or_404("funding_memory").provider_name,
            "symbol": item.get("symbol"),
            "score": score,
            "suggested_tier": suggested_tier,
            "suggested_price_usdc": paid_kit.tier_price(suggested_tier),
            "estimated_value": "High" if score >= 70 else "Medium" if score >= 45 else "Exploratory",
            "reasons": reasons[:4] or ["fresh live anomaly"],
            "query": canonical_query_payload(item),
            "live": item,
        })
    picks = sorted(picks, key=lambda item: item["score"], reverse=True)[:limit]
    return {
        "status": "success",
        "mode": "suggest_then_pay",
        "pricing": {
            "preview_usdc": paid_kit.tier_price("preview"),
            "full_usdc": paid_kit.tier_price("full"),
        },
        "last_updated": live.get("last_updated"),
        "recommendations": picks,
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
    invoice, requirement = paid_kit.create_invoice(
        query=req_data,
        tier=tier,
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

    reload_persistent_state()
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
    uvicorn.run("qma.main:app", host="127.0.0.1", port=8000, reload=False)

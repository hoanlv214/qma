import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Optional


SUPPORTED_TIERS = {
    "preview": {
        "rank": 1,
        "label": "Preview",
        "env": "QMA_PRICE_PREVIEW_USDC",
        "default": "0.001",
    },
    "full": {
        "rank": 2,
        "label": "Full Report",
        "env": "QMA_PRICE_FULL_USDC",
        "default": "0.005",
    },
}


def normalize_address(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def normalize_tier(value: Optional[str]) -> str:
    tier = (value or "full").strip().lower()
    if tier not in SUPPORTED_TIERS:
        raise ValueError(f"Unsupported paid intelligence tier: {value}")
    return tier


def tier_price(tier: Optional[str]) -> float:
    normalized = normalize_tier(tier)
    meta = SUPPORTED_TIERS[normalized]
    return float(os.getenv(meta["env"], meta["default"]))


def has_tier_access(purchased_tier: Optional[str], required_tier: Optional[str]) -> bool:
    purchased = SUPPORTED_TIERS.get(normalize_tier(purchased_tier), {}).get("rank", 0)
    required = SUPPORTED_TIERS.get(normalize_tier(required_tier), {}).get("rank", 0)
    return purchased >= required


def canonical_query_payload(query: dict) -> dict:
    """Stable query payload so paid access cannot be reused for changed inputs."""

    def as_float(value):
        if value is None:
            return None
        return round(float(value), 12)

    return {
        "symbol": str(query.get("symbol", "")).upper(),
        "fundingRate": as_float(query.get("fundingRate")),
        "marketCap": as_float(query.get("marketCap")),
        "FDV": as_float(query.get("FDV")),
        "circRatio": as_float(query.get("circRatio")),
        "fromATH": as_float(query.get("fromATH")),
        "volume24h": as_float(query.get("volume24h")),
        "amount": as_float(query.get("amount")),
    }


def query_fingerprint(query: dict) -> str:
    canonical = canonical_query_payload(query)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def payment_requirement(
    *,
    invoice_id: Optional[str],
    symbol: Optional[str],
    amount_usdc: float,
    tier: str,
    resource_type: str,
    provider_id: str = "funding_memory",
    network: str,
    network_name: str,
    seller_address: str,
    gateway_base_url: str,
    facilitator_url: str,
    explorer_url: str,
    ttl_seconds: int,
) -> dict:
    memo = f"QMA:{provider_id}:{tier}:{invoice_id}" if invoice_id else f"QMA:{provider_id}:{tier}:invoice-required"
    resource = f"{gateway_base_url}/qma-access"
    if invoice_id or symbol:
        resource += (
            f"?invoice_id={invoice_id or ''}&symbol={symbol or ''}"
            f"&provider_id={provider_id}&tier={tier}&amount_usdc={amount_usdc}"
        )
    return {
        "scheme": "circle-x402-batching",
        "network": network,
        "network_name": network_name,
        "asset": "USDC",
        "amount": amount_usdc,
        "tier": tier,
        "provider_id": provider_id,
        "resource_type": resource_type,
        "pay_to": seller_address,
        "memo": memo,
        "resource": resource,
        "invoice_id": invoice_id,
        "symbol": symbol,
        "facilitator": facilitator_url,
        "explorer": explorer_url,
        "expires_in_seconds": ttl_seconds,
    }


def create_invoice(
    *,
    query: dict,
    tier: Optional[str],
    resource_type: str,
    provider_id: str = "funding_memory",
    buyer_type: str = "human",
    owner_wallet: Optional[str] = None,
    network: str,
    network_name: str,
    seller_address: str,
    gateway_base_url: str,
    facilitator_url: str,
    explorer_url: str,
    ttl_seconds: int,
) -> tuple[dict, dict]:
    normalized_tier = normalize_tier(tier)
    query_payload = canonical_query_payload(query)
    amount = tier_price(normalized_tier)
    invoice_id = f"inv_{uuid.uuid4().hex[:12]}"
    now = time.time()
    requirement = payment_requirement(
        invoice_id=invoice_id,
        symbol=query_payload["symbol"],
        amount_usdc=amount,
        tier=normalized_tier,
        resource_type=resource_type,
        provider_id=provider_id,
        network=network,
        network_name=network_name,
        seller_address=seller_address,
        gateway_base_url=gateway_base_url,
        facilitator_url=facilitator_url,
        explorer_url=explorer_url,
        ttl_seconds=ttl_seconds,
    )
    invoice = {
        "invoice_id": invoice_id,
        "status": "pending",
        "amount": amount,
        "currency": "USDC",
        "provider_id": provider_id,
        "buyer_type": buyer_type,
        "owner_wallet": owner_wallet or seller_address,
        "tier": normalized_tier,
        "resource_type": resource_type,
        "symbol": query_payload["symbol"],
        "network": network,
        "network_name": network_name,
        "wallet_address": seller_address,
        "created_at": now,
        "expires_at": now + ttl_seconds,
        "nonce": uuid.uuid4().hex,
        "invoice_secret": uuid.uuid4().hex,
        "query": query_payload,
        "query_hash": query_fingerprint(query_payload),
    }
    return invoice, requirement


def sign_access_token(payload: dict, *, secret: str, ttl_seconds: int) -> str:
    body = {
        **payload,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    encoded_sig = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"{encoded}.{encoded_sig}"


def verify_access_token(token: str, *, secret: str) -> dict:
    if not token or "." not in token:
        raise ValueError("Missing or invalid paid intelligence access token.")
    encoded, encoded_sig = token.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    try:
        actual = base64.urlsafe_b64decode(encoded_sig + "=" * (-len(encoded_sig) % 4))
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Malformed paid intelligence access token.") from exc
    if not hmac.compare_digest(actual, expected):
        raise ValueError("Paid intelligence access token signature is invalid.")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("Paid intelligence access token expired.")
    return payload


def require_access(token_payload: dict, invoice: dict, *, required_tier: str) -> None:
    if token_payload.get("invoice_id") != invoice.get("invoice_id"):
        raise PermissionError("Access token invoice mismatch.")
    if token_payload.get("provider_id", "funding_memory") != invoice.get("provider_id", "funding_memory"):
        raise PermissionError("Access token provider mismatch.")
    if token_payload.get("query_hash") != invoice.get("query_hash"):
        raise PermissionError("Access token query mismatch.")
    if token_payload.get("settlement_id") != invoice.get("settlement_id"):
        raise PermissionError("Access token settlement mismatch.")
    if not has_tier_access(token_payload.get("tier") or invoice.get("tier"), required_tier):
        raise PermissionError(f"Paid tier does not unlock {required_tier}.")


def entitlement_key(
    payer_address: Optional[str],
    query_hash: Optional[str],
    tier: Optional[str],
    provider_id: Optional[str] = "funding_memory",
) -> str:
    return f"{provider_id or 'funding_memory'}:{normalize_address(payer_address)}:{query_hash or ''}:{normalize_tier(tier)}"


def record_entitlement(store: dict, *, invoice: dict, report: dict, saved_at: Optional[float] = None) -> dict:
    record = {
        "entitlement_id": entitlement_key(
            invoice.get("payer_address"),
            invoice.get("query_hash"),
            invoice.get("tier"),
            invoice.get("provider_id", "funding_memory"),
        ),
        "provider_id": invoice.get("provider_id", "funding_memory"),
        "provider_owner_wallet": invoice.get("owner_wallet") or invoice.get("wallet_address"),
        "buyer_type": invoice.get("buyer_type", "human"),
        "query_hash": invoice.get("query_hash"),
        "query": invoice.get("query"),
        "symbol": invoice.get("symbol"),
        "tier": normalize_tier(invoice.get("tier")),
        "resource_type": invoice.get("resource_type", "qma_signal_report"),
        "payer_address": invoice.get("payer_address"),
        "settlement_id": invoice.get("settlement_id"),
        "transaction_hash": invoice.get("transaction_hash"),
        "explorer_url": invoice.get("explorer_url"),
        "gateway_status": invoice.get("gateway_status"),
        "amount_usdc": invoice.get("amount"),
        "paid_at": invoice.get("paid_at"),
        "saved_at": saved_at or time.time(),
        "report": report,
    }
    store[record["entitlement_id"]] = record
    return record


def list_wallet_entitlements(
    store: dict,
    address: str,
    *,
    symbol: Optional[str] = None,
    provider_id: Optional[str] = None,
) -> list[dict]:
    normalized = normalize_address(address)
    symbol_filter = (symbol or "").strip().upper()
    records = [
        record for record in store.values()
        if normalize_address(record.get("payer_address")) == normalized
        and (not symbol_filter or str(record.get("symbol", "")).upper() == symbol_filter)
        and (not provider_id or record.get("provider_id", "funding_memory") == provider_id)
    ]
    return sorted(records, key=lambda item: item.get("paid_at") or item.get("saved_at") or 0, reverse=True)


def resolve_settlement_tx(settlement: dict, explorer_url: str) -> dict:
    candidates = [
        settlement.get("transactionHash"),
        settlement.get("txHash"),
        settlement.get("batchTxHash"),
        settlement.get("blockchainTxHash"),
    ]
    for key in ("batch", "batchTransaction", "transaction", "data"):
        nested = settlement.get(key)
        if isinstance(nested, dict):
            candidates.extend([
                nested.get("transactionHash"),
                nested.get("txHash"),
                nested.get("hash"),
                nested.get("batchTxHash"),
            ])
    batch_tx = next((value for value in candidates if isinstance(value, str) and value.startswith("0x")), None)
    return {
        "batch_tx": batch_tx,
        "explorer_url": f"{explorer_url.rstrip('/')}/tx/{batch_tx}" if batch_tx else None,
    }

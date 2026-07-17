"""Wallet profile session and public wallet row helpers."""

import time

from fastapi import HTTPException, status

import paid_intelligence_kit as paid_kit

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
except Exception:
    Account = None
    encode_defunct = None


def wallet_profile_message(address: str, nonce: str, issued_at: int) -> str:
    normalized = paid_kit.normalize_address(address)
    return (
        "QMA Wallet Profile Access\n"
        f"Wallet: {normalized}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}\n"
        "Purpose: unlock-paid-report-snapshots"
    )


def verify_wallet_profile_token(address: str, token: str, *, access_token_secret: str) -> dict:
    try:
        payload = paid_kit.verify_access_token(token or "", secret=access_token_secret)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    expected = paid_kit.normalize_address(address)
    actual = paid_kit.normalize_address(payload.get("wallet"))
    if payload.get("scope") != "wallet_profile" or actual != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Wallet profile token does not match this wallet.")
    return payload


def wallet_profile_token_payload(address: str, payload) -> dict:
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
        "buyer_wallet_address": record.get("buyer_wallet_address"),
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

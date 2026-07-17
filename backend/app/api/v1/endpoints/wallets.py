"""Wallet profile, entitlements, and report history endpoints."""

from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from backend.app.schemas import WalletProfileSessionRequest

router = APIRouter(tags=["wallets"])


def wallet_events_with_invoice_fallback(address: str, deps: SimpleNamespace) -> list:
    events = deps.load_payment_events_for_wallet(address)
    paid_invoices = list(deps.load_paid_invoices_for_wallet(address).values())
    existing_keys = {deps.payment_event_key(event) for event in events}
    for invoice in paid_invoices:
        deps.hydrate_payment_schema(invoice)
        key = str(invoice.get("settlement_id") or invoice.get("invoice_id") or "")
        if key and key not in existing_keys:
            # For split invoices, derive aggregate gateway_status from legs instead of
            # the frozen "received" status that was written at verify time.
            invoice_gateway_status = invoice.get("gateway_status")
            if deps.invoice_split_mode(invoice) == "x402_direct_split":
                legs = deps.invoice_required_split_legs(invoice)
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
                "resource_type": invoice.get("resource_type", deps.payment_resource_type),
                "payer_address": invoice.get("payer_address"),
                "seller_address": deps.payment_wallet_address,
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
    for report in deps.load_paid_report_summaries_for_wallet(address):
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


def create_wallets_router(deps: SimpleNamespace) -> APIRouter:
    migrated = APIRouter(tags=["wallets"])

    @migrated.get("/api/v1/metrics/wallet/{address}")
    def get_wallet_metrics(
        address: str,
        payment_page: int = Query(default=1, ge=1),
        payment_page_size: int = Query(default=10, ge=1, le=100),
        entitlement_page: int = Query(default=1, ge=1),
        entitlement_page_size: int = Query(default=50, ge=1, le=100),
        qma_wallet_token: Optional[str] = Header(default=None, alias="X-QMA-Wallet-Token"),
        wallet_token: Optional[str] = Query(default=None),
    ):
        events = deps.load_payment_events_for_wallet(address)
        paid_invoices = list(deps.load_paid_invoices_for_wallet(address).values())
        for invoice in paid_invoices:
            deps.hydrate_payment_schema(invoice)
            if not any(event.get("settlement_id") == invoice.get("settlement_id") for event in events):
                events.append({
                    "invoice_id": invoice.get("invoice_id"),
                    "symbol": invoice.get("symbol"),
                    "provider_id": invoice.get("provider_id", "funding_memory"),
                    "provider_owner_wallet": invoice.get("owner_wallet"),
                    "buyer_type": invoice.get("buyer_type", "human"),
                    "tier": invoice.get("tier", "full"),
                    "resource_type": invoice.get("resource_type", deps.payment_resource_type),
                    "payer_address": invoice.get("payer_address"),
                    "seller_address": deps.payment_wallet_address,
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
            tier = deps.payment_event_tier(event)
            event["tier_category"] = tier
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            buyer_type = event.get("buyer_type", "human")
            buyer_type_counts[buyer_type] = buyer_type_counts.get(buyer_type, 0) + 1
            provider_id = event.get("provider_id", "funding_memory")
            provider_counts[provider_id] = provider_counts.get(provider_id, 0) + 1
        wallet_reports = deps.load_paid_reports_for_wallet(address)
        entitlements = deps.list_wallet_entitlements(wallet_reports, address)
        token = qma_wallet_token or wallet_token
        if token:
            deps.verify_wallet_profile_token(address, token)
        else:
            entitlements = [deps.public_entitlement_row(record) for record in entitlements]
        recent_payments, recent_payments_page = deps.paginate_items(events, payment_page, payment_page_size)
        entitlement_items, entitlements_page = deps.paginate_items(entitlements, entitlement_page, entitlement_page_size)
        return {
            "address": address,
            "access": "private" if token else "public",
            "gateway_balance": deps.fetch_gateway_balance(address),
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

    @migrated.get("/api/v1/wallets/{address}/summary")
    def get_wallet_summary(address: str):
        deps.maybe_refresh_unresolved_payment_events()
        events = wallet_events_with_invoice_fallback(address, deps)
        summary = deps.summarize_payment_events(events)
        purchased_symbols = sorted({event.get("symbol") for event in events if event.get("symbol")})
        provider_counts = {}
        for event in events:
            provider_id = event.get("provider_id", "funding_memory")
            provider_counts[provider_id] = provider_counts.get(provider_id, 0) + 1
        return {
            "address": address,
            "gateway_balance": deps.fetch_gateway_balance_cached(address),
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

    @migrated.get("/api/v1/wallets/{address}")
    def get_wallet_profile_alias(address: str):
        """Returns the wallet summary for direct wallet profile API probes."""
        return get_wallet_summary(address)

    @migrated.get("/api/v1/wallets/{address}/payments")
    def get_wallet_payments(
        address: str,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=100),
        qma_wallet_token: Optional[str] = Header(default=None, alias="X-QMA-Wallet-Token"),
        wallet_token: Optional[str] = Query(default=None),
    ):
        events = wallet_events_with_invoice_fallback(address, deps)
        token = qma_wallet_token or wallet_token
        if token:
            deps.verify_wallet_profile_token(address, token)
            report_summaries = deps.load_paid_report_summaries_for_wallet(address)
            rows = deps.attach_report_summaries(events, report_summaries)
        else:
            rows = [deps.public_payment_row(deps.compact_payment_event(event)) for event in events]
        page_items, meta = deps.paginate_items(rows, page, page_size)
        return {
            "address": address,
            "access": "private" if token else "public",
            "recent_payments": page_items,
            "recent_payments_page": meta,
        }

    @migrated.post("/api/v1/wallets/{address}/session")
    def create_wallet_profile_session(address: str, payload: WalletProfileSessionRequest):
        token_payload = deps.wallet_profile_token_payload(address, payload)
        return {
            "address": deps.normalize_address(address),
            "wallet_token": deps.sign_access_token(
                token_payload,
                secret=deps.access_token_secret,
                ttl_seconds=deps.wallet_profile_token_ttl_seconds,
            ),
            "expires_in": deps.wallet_profile_token_ttl_seconds,
            "message": deps.wallet_profile_message(address, payload.nonce, payload.issued_at),
        }

    @migrated.get("/api/v1/wallets/{address}/reports/{entitlement_id}")
    def get_wallet_report_detail(
        address: str,
        entitlement_id: str,
        qma_wallet_token: Optional[str] = Header(default=None, alias="X-QMA-Wallet-Token"),
        wallet_token: Optional[str] = Query(default=None),
    ):
        deps.verify_wallet_profile_token(address, qma_wallet_token or wallet_token or "")
        record = deps.load_paid_report_by_id(address, entitlement_id)
        if not record:
            raise HTTPException(status_code=404, detail="Paid report snapshot not found for this wallet.")
        return {
            "address": address,
            "entitlement": record,
        }

    @migrated.get("/api/v1/entitlements/wallet/{address}")
    def get_wallet_entitlements(
        address: str,
        symbol: Optional[str] = Query(default=None),
        provider_id: Optional[str] = Query(default=None),
        qma_wallet_token: Optional[str] = Header(default=None, alias="X-QMA-Wallet-Token"),
        wallet_token: Optional[str] = Query(default=None),
    ):
        wallet_reports = deps.load_paid_reports_for_wallet(address, symbol=symbol, provider_id=provider_id)
        records = deps.list_wallet_entitlements(wallet_reports, address, symbol=symbol, provider_id=provider_id)
        token = qma_wallet_token or wallet_token
        if token:
            deps.verify_wallet_profile_token(address, token)
        else:
            records = [deps.public_entitlement_row(record) for record in records]
        return {
            "address": address,
            "symbol": symbol,
            "provider_id": provider_id,
            "count": len(records),
            "access": "private" if token else "public",
            "entitlements": records[:100],
        }

    return migrated

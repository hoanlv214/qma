"""Platform analytics endpoints."""

from types import SimpleNamespace

from fastapi import APIRouter, Query


router = APIRouter(tags=["platform"])


def create_platform_router(deps: SimpleNamespace) -> APIRouter:
    migrated = APIRouter(tags=["platform"])

    @migrated.get("/api/v1/metrics")
    def get_metrics(
        payment_page: int = Query(default=1, ge=1),
        payment_page_size: int = Query(default=10, ge=1, le=100),
        payer_page: int = Query(default=1, ge=1),
        payer_page_size: int = Query(default=10, ge=1, le=100),
    ):
        events = deps.load_platform_payment_events()
        summary = deps.summarize_payment_events(events)
        recent_payments, recent_payments_page = deps.paginate_items(events, payment_page, payment_page_size)
        payer_breakdown_page_items, payer_breakdown_page = deps.paginate_items(summary["payer_breakdown"], payer_page, payer_page_size)
        seller_balance = deps.fetch_gateway_balance_cached(deps.payment_wallet_address)
        return {
            "seller_address": deps.payment_wallet_address,
            "seller_gateway_balance": seller_balance,
            "invoice_count": len(deps.invoices_db),
            "paid_count": summary["paid_count"],
            "current_paid_count": summary["current_paid_count"],
            "legacy_paid_count": summary["legacy_paid_count"],
            "unique_payers": summary["unique_payers"],
            "current_unique_payers": summary["current_unique_payers"],
            "revenue_usdc": summary["revenue_usdc"],
            "current_revenue_usdc": summary["current_revenue_usdc"],
            "legacy_revenue_usdc": summary["legacy_revenue_usdc"],
            "tier_counts": summary["tier_counts"],
            "buyer_type_counts": summary["buyer_type_counts"],
            "current_buyer_type_counts": summary["current_buyer_type_counts"],
            "legacy_buyer_type_counts": summary["legacy_buyer_type_counts"],
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

    @migrated.get("/api/v1/platform/summary")
    def get_platform_summary():
        deps.maybe_refresh_unresolved_payment_events()
        events = deps.load_platform_payment_events()
        summary = deps.summarize_payment_events(events)
        return {
            "seller_address": deps.payment_wallet_address,
            "seller_gateway_balance": deps.fetch_gateway_balance_cached(deps.payment_wallet_address),
            "invoice_count": len(deps.invoices_db),
            "paid_count": summary["paid_count"],
            "current_paid_count": summary["current_paid_count"],
            "legacy_paid_count": summary["legacy_paid_count"],
            "unique_payers": summary["unique_payers"],
            "current_unique_payers": summary["current_unique_payers"],
            "revenue_usdc": summary["revenue_usdc"],
            "current_revenue_usdc": summary["current_revenue_usdc"],
            "legacy_revenue_usdc": summary["legacy_revenue_usdc"],
            "tier_counts": summary["tier_counts"],
            "buyer_type_counts": summary["buyer_type_counts"],
            "current_buyer_type_counts": summary["current_buyer_type_counts"],
            "legacy_buyer_type_counts": summary["legacy_buyer_type_counts"],
            "revenue_by_tier": summary["revenue_by_tier"],
            "revenue_by_provider": summary["revenue_by_provider"],
            "top_symbols": summary["top_symbols"],
            "last_payment_key": summary["last_payment_key"],
            "last_paid_at": summary["last_paid_at"],
        }

    @migrated.get("/api/v1/platform/payments")
    def get_platform_payments(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=100),
    ):
        events = deps.load_platform_payment_events()
        page_items, meta = deps.paginate_items(events, page, page_size)
        return {
            "recent_payments": [deps.compact_payment_event(event) for event in page_items],
            "recent_payments_page": meta,
        }

    @migrated.get("/api/v1/platform/payers")
    def get_platform_payers(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=100),
    ):
        events = deps.load_platform_payment_events()
        summary = deps.summarize_payment_events(events)
        items, meta = deps.paginate_items(summary["payer_breakdown"], page, page_size)
        return {
            "payer_breakdown": items,
            "payer_breakdown_page": meta,
        }

    return migrated

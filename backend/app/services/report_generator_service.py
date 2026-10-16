"""Report generator domain service.

Builds full and preview intelligence reports, epoch market-state snapshots,
and canonical serializations for cryptographic hashing and GenLayer verification.
"""

import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi.encoders import jsonable_encoder

from backend.app.core.config import PAYMENT_WALLET_ADDRESS
from backend.app.schemas import ProviderReportResponse
from backend.app.services.market_epoch import begin_or_get_epoch
from backend.app.services.invoice_builder import hydrate_payment_schema
from backend.app.services.security import canonical_query_payload, query_fingerprint

logger = logging.getLogger("QMA-ReportGenerator")


_PUBLIC_VERIFICATION_CLAIMS = (
    "query_symbol",
    "is_ood",
    "ood_p_value",
    "ood_empirical_nn_distance",
    "ood_empirical_p99_threshold",
    "ood_empirical_percentile",
    "matched_k",
    "average_similarity",
    "regime_cluster",
    "regime_description",
    "regime_support",
    "weighted_win_rate",
    "ci_win_rate_95",
    "weighted_avg_profit",
    "ci_avg_profit_95",
    "percentiles",
    "effective_sample_size",
    "bootstrap_rounds",
    "distance_summary",
    "query_features",
    "data_quality",
    "validation_warnings",
    "risk_flags",
    "funding_context",
    "rough_win_rate",
    "win_rate_band",
    "analysis_focus",
    "turnover_context",
    "provider_diagnostics",
    "declared_confidence",
    "arbitrage_bias",
    "recommended_strategy",
    "anomaly",
    "regime",
    "predicted_bias",
    "bias",
)


def build_preview_report(full_report: dict, invoice: dict) -> dict:
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
        "risk_flags": full_report.get("risk_flags"),
        "effective_sample_size": full_report.get("effective_sample_size"),
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
        "buyer_wallet_address": invoice.get("buyer_wallet_address"),
        "provider_owner_wallet": invoice.get("owner_wallet"),
        "amount_usdc": invoice.get("amount"),
        "pricing": invoice.get("pricing"),
        "settlement": invoice.get("settlement"),
        "accounting": invoice.get("accounting"),
        "network": invoice.get("network"),
        "verification_mode": invoice.get("verification_mode"),
    }


def _canonical_report_json(report: dict) -> str:
    return json.dumps(
        jsonable_encoder(report),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _build_epoch_snapshot(provider: Any, query: dict, tier: str) -> dict:
    """Freeze one verified market-state snapshot: the normalized query, the
    report built from it, and their canonical hashes. Every invoice in the
    epoch reuses these, so one GenLayer attestation pre-verifies them all."""
    minimal_invoice = {"tier": tier, "query": query}
    report = build_provider_report(
        provider=provider,
        normalized_query=query,
        invoice_id=f"epoch_{getattr(provider, 'provider_id', 'provider')}_{query.get('symbol', 'X')}",
        invoice=minimal_invoice,
        required_tier=tier,
    )
    canonical_report = _canonical_report_json(report)
    return {
        "query": query,
        "report": report,
        "canonical": canonical_report,
        "query_hash": query_fingerprint(query),
        "report_hash": hashlib.sha256(canonical_report.encode("utf-8")).hexdigest(),
        "state": "pending",
    }


def build_provider_report(
    *,
    provider: Any,
    normalized_query: dict,
    invoice_id: str,
    invoice: dict,
    required_tier: str,
) -> dict:
    """Build the report once so GenLayer verifies the payload later delivered."""
    if hasattr(provider, "deliver"):
        context = {
            "query": invoice.get("query") or normalized_query,
            "tier": invoice.get("tier", required_tier),
        }
        if "_score_cache_key" in invoice:
            context["_score_cache_key"] = invoice["_score_cache_key"]
        if "declared_confidence" in invoice:
            context["declared_confidence"] = invoice["declared_confidence"]

        payload_data = provider.deliver(context, invoice_id)

        # Hybrid BYO-Key Intelligence Layer (Scenario A vs B)
        user_llm_key = (
            invoice.get("user_llm_key")
            or invoice.get("llm_api_key")
            or os.getenv("USER_LLM_API_KEY")
        )
        if user_llm_key and payload_data.get("tier") == "full":
            from backend.app.services.agent_synthesis import generate_agent_synthesis
            synthesis = generate_agent_synthesis(
                provider_id=getattr(provider, "provider_id", "unknown"),
                symbol=payload_data.get("symbol") or payload_data.get("query_symbol") or "TOKEN",
                metrics=payload_data,
                api_key=user_llm_key,
            )
            if synthesis:
                payload_data["agent_synthesis"] = synthesis
                payload_data["synthesis_mode"] = "byo_key_ai_executive_analysis"
            else:
                payload_data["synthesis_mode"] = "pure_quantitative_metrics"
        else:
            payload_data["synthesis_mode"] = "pure_quantitative_metrics"

        report_kwargs = {
            "query_symbol": payload_data.get("query_symbol"),
            "query": context.get("query"),
            "query_hash": invoice.get("query_hash"),
            "tier": payload_data.get("tier", required_tier),
            "invoice": invoice_report_meta(invoice_id, invoice),
            "provider_id": getattr(provider, "provider_id", "unknown"),
            "provider_name": getattr(provider, "provider_name", getattr(provider, "provider_id", "unknown")),
            "provider_owner_wallet": getattr(provider, "owner_wallet", PAYMENT_WALLET_ADDRESS),
            "paid_at": invoice.get("paid_at"),
            "payload": payload_data,
        }
        if "upgrade_cta" in payload_data:
            report_kwargs["upgrade_cta"] = payload_data["upgrade_cta"]

        report_obj = ProviderReportResponse(**report_kwargs)
        report = report_obj.model_dump(exclude_unset=True, by_alias=True)
    else:
        full_report = provider.full_report(normalized_query)
        full_report["query"] = invoice.get("query") or canonical_query_payload(normalized_query)
        full_report["query_hash"] = invoice.get("query_hash")
        full_report["provider_id"] = provider.provider_id
        full_report["provider_name"] = provider.provider_name
        full_report["provider_owner_wallet"] = provider.owner_wallet
        full_report["invoice"] = invoice_report_meta(invoice_id, invoice)
        if invoice.get("genlayer"):
            full_report["genlayer"] = invoice.get("genlayer")
        if required_tier == "preview":
            report = build_preview_report(full_report, invoice)
            report["provider_id"] = provider.provider_id
            report["provider_name"] = provider.provider_name
            if invoice.get("genlayer"):
                report["genlayer"] = invoice.get("genlayer")
        else:
            full_report["tier"] = "full"
            full_report["paid_at"] = invoice.get("paid_at")
            report = full_report
    return jsonable_encoder(report)

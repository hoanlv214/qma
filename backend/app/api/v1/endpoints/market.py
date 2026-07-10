"""Market data and agent recommendation endpoints."""

import time
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Query


router = APIRouter(tags=["market"])


def create_market_router(deps: SimpleNamespace) -> APIRouter:
    migrated = APIRouter(tags=["market"])

    def live_anomalies_payload() -> dict:
        now = time.time()
        if now - deps.live_anomalies_cache["last_updated"] > deps.cache_ttl_seconds:
            with deps.live_scan_lock:
                now = time.time()
                if now - deps.live_anomalies_cache["last_updated"] > deps.cache_ttl_seconds:
                    deps.logger.info("Cache expired. Scanning MEXC live...")
                    deps.live_anomalies_cache["data"] = deps.scan_mexc_live()
                    deps.live_anomalies_cache["last_updated"] = time.time()
        else:
            deps.logger.info("Serving live anomalies from cache.")

        return {
            "status": "success",
            "last_updated": deps.live_anomalies_cache["last_updated"],
            "count": len(deps.live_anomalies_cache["data"]),
            "anomalies": deps.live_anomalies_cache["data"],
        }

    @migrated.get("/api/v1/live-anomalies")
    def get_live_anomalies():
        """Returns real-time MEXC funding anomalies with caching."""
        return live_anomalies_payload()

    @migrated.get("/api/v1/market-data/cache")
    def get_market_data_cache(
        symbol: Optional[str] = Query(default=None),
        refresh: bool = Query(default=False),
    ):
        """Debugs the active market-data adapter cache, e.g. MEXC detailV2 contract size (cs)."""
        normalized_symbol = str(symbol or "").strip().upper() or None
        if normalized_symbol and "_" not in normalized_symbol:
            normalized_symbol = f"{normalized_symbol}_USDT"
        if not hasattr(deps.market_data_adapter, "cache_status"):
            return {
                "source": getattr(deps.market_data_adapter, "source_id", "unknown"),
                "cache_supported": False,
            }
        return deps.market_data_adapter.cache_status(symbol=normalized_symbol, refresh=refresh)

    @migrated.get("/api/v1/agent/recommendations")
    def get_agent_recommendations(limit: int = Query(default=8, ge=1, le=25)):
        """Ranks live anomalies as user-confirmed paid report candidates."""
        live = live_anomalies_payload()
        anomalies = live.get("anomalies", [])
        picks = []
        enabled_providers = [
            deps.provider_registry.require(item["provider_id"])
            for item in deps.provider_registry.list()
            if deps.provider_control(item["provider_id"])["enabled"]
        ]
        for item in anomalies:
            funding_pct = abs(float(item.get("fundingRate") or 0) * 100)
            volume = float(item.get("volume24h") or 0)
            market_cap = max(float(item.get("marketCap") or 0), 1)
            circ = float(item.get("circRatio") or 0)
            ath = abs(float(item.get("fromATH") or 0))
            for provider in enabled_providers:
                query_payload = deps.normalize_query_for_provider(provider, item)
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
            "pricing": deps.pricing_config(),
            "last_updated": live.get("last_updated"),
            "recommendations": picks,
        }

    return migrated

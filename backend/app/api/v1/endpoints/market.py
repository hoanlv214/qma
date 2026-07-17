"""Market data and agent recommendation endpoints."""

from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Query

from backend.app.services.agent_recommendations import build_agent_recommendations

router = APIRouter(tags=["market"])


def create_market_router(deps: SimpleNamespace) -> APIRouter:
    migrated = APIRouter(tags=["market"])

    def live_anomalies_payload() -> dict:
        import time

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
        return build_agent_recommendations(deps, limit)

    return migrated

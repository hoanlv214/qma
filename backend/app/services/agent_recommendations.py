"""Shared recommendation builder used by human and autonomous agent flows."""

import time
from types import SimpleNamespace


def build_agent_recommendations(deps: SimpleNamespace, limit: int = 8) -> dict:
    now = time.time()

    def _get_all_providers(registry):
        if hasattr(registry, "list_providers"):
            return registry.list_providers()
        return [registry.require(item["provider_id"]) for item in registry.list() if item.get("provider_id")]

    all_providers = _get_all_providers(deps.provider_registry)
    enabled_providers = [
        p for p in all_providers
        if deps.provider_control(p.provider_id)["enabled"]
    ]
    enabled_provider_ids = {getattr(p, "provider_id", "") for p in enabled_providers}

    # 1. Scan / Cache for funding_memory (and oi_memory)
    funding_pid = "funding_memory"
    f_cache_key = f"{funding_pid}_last_updated"
    f_data_key = f"{funding_pid}_data"
    if f_cache_key not in deps.live_anomalies_cache:
        deps.live_anomalies_cache[f_cache_key] = 0
        deps.live_anomalies_cache[f_data_key] = []

    if now - deps.live_anomalies_cache[f_cache_key] > deps.cache_ttl_seconds:
        with deps.live_scan_lock:
            now = time.time()
            if now - deps.live_anomalies_cache[f_cache_key] > deps.cache_ttl_seconds:
                deps.logger.info(f"Cache expired. Scanning live anomalies for {funding_pid}...")
                try:
                    provider = deps.provider_registry.require(funding_pid)
                    scanned = []
                    if hasattr(provider, "scan_live_anomalies"):
                        scanned = provider.scan_live_anomalies() or []
                    elif callable(deps.scan_mexc_live):
                        scanned = deps.scan_mexc_live() or []
                    if scanned:
                        deps.live_anomalies_cache[f_data_key] = scanned
                        deps.live_anomalies_cache[f_cache_key] = time.time()
                    elif not deps.live_anomalies_cache.get(f_data_key):
                        deps.live_anomalies_cache[f_cache_key] = time.time() - deps.cache_ttl_seconds + 2
                except Exception as e:
                    deps.logger.error(f"Failed to scan anomalies for {funding_pid}: {e}")

    funding_anomalies = deps.live_anomalies_cache.get(f_data_key) or []
    last_updated = deps.live_anomalies_cache.get(f_cache_key, 0) or time.time()

    picks = []
    from backend.app.main import _signal_verifiability, _gate_enabled
    from backend.app.services.market_epoch import is_preverified

    # 1. Process funding_memory & oi_memory on funding_anomalies
    mexc_providers = [p for p in enabled_providers if getattr(p, "provider_id", "") in ("funding_memory", "oi_memory")]
    for item in funding_anomalies:
        fr_raw = float(item.get("fundingRate") or 0)
        funding_pct = abs(fr_raw * 100)
        volume = float(item.get("volume24h") or 0)
        market_cap = max(float(item.get("marketCap") or 0), 1)
        circ = float(item.get("circRatio") or 0)
        ath = abs(float(item.get("fromATH") or 0))

        for provider in mexc_providers:
            query_payload = deps.normalize_query_for_provider(provider, item)
            turnover_pct = (volume / market_cap) * 100
            open_interest = float(query_payload.get("amount") or query_payload.get("openInterest") or 0)
            oi_pct = (open_interest / market_cap) * 100
            structure_score = min(20.0, max(0.0, 1.0 - abs(circ - 0.65)) * 20)
            discount_score = min(10.0, ath / 10)
            reasons = []

            if getattr(provider, "provider_id", "") == "oi_memory":
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
                    if fr_raw < 0:
                        reasons.append("negative funding context (short squeeze risk)")
                    else:
                        reasons.append("positive funding context (long squeeze / basis carry)")
            else:
                volume_score = min(25.0, turnover_pct)
                funding_score = min(45.0, funding_pct * 18)
                score = round(min(100.0, funding_score + volume_score + structure_score + discount_score), 1)
                if fr_raw <= -0.005:
                    reasons.append("extreme negative funding (short squeeze risk)")
                elif fr_raw >= 0.005:
                    reasons.append("extreme positive funding (long squeeze / basis carry)")
                elif fr_raw <= -0.0025:
                    reasons.append("notable negative funding anomaly")
                elif fr_raw >= 0.0025:
                    reasons.append("notable positive funding anomaly")
                else:
                    reasons.append("dislocated funding basis")
                if turnover_pct >= 2:
                    reasons.append("meaningful turnover")

            if 0.2 <= circ <= 1.0:
                reasons.append("usable circulating supply profile")
            if ath >= 50:
                reasons.append("deep drawdown context")

            suggested_tier = "full" if score >= 65 else "preview"
            try:
                if hasattr(provider, "score"):
                    score_result = provider.score({"query": query_payload, "tier": suggested_tier})
                    amount_usdc = score_result["amount_usdc"]
                    complexity = score_result.get("complexity_score", 0)
                    manifest = provider.manifest()
                    provider_name = manifest.get("name", provider.provider_id)
                    category = manifest.get("category", "unknown")
                else:
                    quote = provider.quote_price(query_payload, suggested_tier)
                    amount_usdc = quote["amount_usdc"]
                    complexity = quote["complexity_score"]
                    provider_name = getattr(provider, "provider_name", getattr(provider, "provider_id", "unknown"))
                    category = getattr(provider, "category", "unknown")
            except Exception as exc:
                if hasattr(deps, "logger") and deps.logger:
                    deps.logger.debug("Provider %s failed scoring: %s", getattr(provider, "provider_id", "unknown"), exc)
                continue

            pid = getattr(provider, "provider_id", "unknown")
            if _gate_enabled():
                check = _signal_verifiability(pid, query_payload)
                if not check["verifiable"]:
                    continue
                evidence_exchange = check.get("exchange") or "MEXC"
            else:
                evidence_exchange = "MEXC"
            sla_state = "preverified" if is_preverified(pid, str(item.get("symbol") or "")) else "verifiable"

            picks.append({
                "provider_id": pid,
                "provider_name": provider_name,
                "provider_category": category,
                "symbol": item.get("symbol"),
                "score": score,
                "suggested_tier": suggested_tier,
                "suggested_price_usdc": amount_usdc,
                "complexity_score": complexity,
                "estimated_value": (
                    "Short Squeeze" if fr_raw <= -0.0025
                    else "Long Squeeze" if fr_raw >= 0.0025
                    else "High" if score >= 70
                    else "Medium" if score >= 45
                    else "Exploratory"
                ),
                "reasons": reasons[:4] or ["fresh live anomaly"],
                "query": query_payload,
                "live": item,
                "exchange": evidence_exchange,
                "sla": {
                    "state": sla_state,
                    "evidence_exchange": evidence_exchange,
                },
            })
    picks = sorted(picks, key=lambda item: item["score"], reverse=True)[:limit]
    return {
        "mode": "suggest_then_pay",
        "provider_strategy": "single_provider_invoice",
        "pricing": deps.pricing_config(),
        "last_updated": last_updated,
        "recommendations": picks,
    }


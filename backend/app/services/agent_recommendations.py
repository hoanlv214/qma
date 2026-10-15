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

    # 2. Scan / Cache for polymarket_divergence
    poly_anomalies = []
    if "polymarket_divergence" in enabled_provider_ids:
        poly_pid = "polymarket_divergence"
        p_cache_key = f"{poly_pid}_last_updated"
        p_data_key = f"{poly_pid}_data"
        if p_cache_key not in deps.live_anomalies_cache:
            deps.live_anomalies_cache[p_cache_key] = 0
            deps.live_anomalies_cache[p_data_key] = []
        if now - deps.live_anomalies_cache[p_cache_key] > deps.cache_ttl_seconds:
            with deps.live_scan_lock:
                now = time.time()
                if now - deps.live_anomalies_cache[p_cache_key] > deps.cache_ttl_seconds:
                    try:
                        p_provider = deps.provider_registry.require(poly_pid)
                        if hasattr(p_provider, "scan_live_anomalies"):
                            scanned = p_provider.scan_live_anomalies() or []
                            if scanned:
                                deps.live_anomalies_cache[p_data_key] = scanned
                                deps.live_anomalies_cache[p_cache_key] = time.time()
                    except Exception as e:
                        deps.logger.error(f"Failed to scan anomalies for {poly_pid}: {e}")
        poly_anomalies = deps.live_anomalies_cache.get(p_data_key) or []

    # 3. Scan / Cache for pyth_stress_band
    pyth_anomalies = []
    if "pyth_stress_band" in enabled_provider_ids:
        pyth_pid = "pyth_stress_band"
        py_cache_key = f"{pyth_pid}_last_updated"
        py_data_key = f"{pyth_pid}_data"
        if py_cache_key not in deps.live_anomalies_cache:
            deps.live_anomalies_cache[py_cache_key] = 0
            deps.live_anomalies_cache[py_data_key] = []
        if now - deps.live_anomalies_cache[py_cache_key] > deps.cache_ttl_seconds:
            with deps.live_scan_lock:
                now = time.time()
                if now - deps.live_anomalies_cache[py_cache_key] > deps.cache_ttl_seconds:
                    try:
                        py_provider = deps.provider_registry.require(pyth_pid)
                        if hasattr(py_provider, "scan_live_anomalies"):
                            scanned = py_provider.scan_live_anomalies() or []
                            if scanned:
                                deps.live_anomalies_cache[py_data_key] = scanned
                                deps.live_anomalies_cache[py_cache_key] = time.time()
                    except Exception as e:
                        deps.logger.error(f"Failed to scan anomalies for {pyth_pid}: {e}")
        pyth_anomalies = deps.live_anomalies_cache.get(py_data_key) or []

    funding_anomalies = deps.live_anomalies_cache.get(f_data_key) or []
    last_updated = max(
        deps.live_anomalies_cache.get(f_cache_key, 0),
        deps.live_anomalies_cache.get("polymarket_divergence_last_updated", 0) if "polymarket_divergence" in enabled_provider_ids else 0,
        deps.live_anomalies_cache.get("pyth_stress_band_last_updated", 0) if "pyth_stress_band" in enabled_provider_ids else 0,
    ) or time.time()

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

    # 2. Process polymarket_divergence anomalies
    poly_provider = next((p for p in enabled_providers if getattr(p, "provider_id", "") == "polymarket_divergence"), None)
    if poly_provider and poly_anomalies:
        manifest = poly_provider.manifest()
        for p_item in poly_anomalies:
            query_payload = deps.normalize_query_for_provider(poly_provider, p_item)
            div_delta = float(query_payload.get("divergence_delta") or p_item.get("divergence_delta") or 0.12)
            fund_pct = float(query_payload.get("perpetual_funding_8h") or p_item.get("perpetual_funding_8h") or 0.01)

            div_score = min(60.0, div_delta * 350.0)
            basis_score = min(20.0, abs(fund_pct) * 20.0)
            score = round(min(100.0, 30.0 + div_score + basis_score), 1)
            suggested_tier = "full" if score >= 65 else "preview"

            reasons = []
            if div_delta >= 0.12:
                reasons.append(f"significant {round(div_delta * 100, 1)}% prediction-vs-perp divergence")
            else:
                reasons.append(f"active {round(div_delta * 100, 1)}% probability mispricing spread")
            reasons.append(p_item.get("event_title", "Polymarket Prediction Target")[:45])
            reasons.append("Polygon-Arc CCTP cross-chain arbitrage path")
            reasons.append("GenLayer multi-oracle consensus auditable")

            try:
                score_result = poly_provider.score({"query": query_payload, "tier": suggested_tier})
                amount_usdc = score_result["amount_usdc"]
                complexity = score_result.get("complexity_score", 0.85)
            except Exception:
                amount_usdc = 0.005 if suggested_tier == "full" else 0.002
                complexity = 0.85

            pid = poly_provider.provider_id
            if _gate_enabled():
                check = _signal_verifiability(pid, query_payload)
                if not check["verifiable"]:
                    continue
                evidence_exchange = check.get("exchange") or "Polymarket"
            else:
                evidence_exchange = "Polymarket"
            sla_state = "preverified" if is_preverified(pid, str(p_item.get("symbol") or "")) else "verifiable"

            picks.append({
                "provider_id": pid,
                "provider_name": manifest.get("name", "Polymarket Prediction Divergence"),
                "provider_category": manifest.get("category", "prediction_market"),
                "symbol": p_item.get("symbol"),
                "score": score,
                "suggested_tier": suggested_tier,
                "suggested_price_usdc": amount_usdc,
                "complexity_score": complexity,
                "estimated_value": "High" if score >= 70 else "Medium" if score >= 45 else "Exploratory",
                "reasons": reasons[:4],
                "query": query_payload,
                "live": p_item,
                "exchange": "Polymarket",
                "sla": {
                    "state": sla_state,
                    "evidence_exchange": evidence_exchange,
                },
            })

    # 3. Process pyth_stress_band anomalies
    pyth_provider = next((p for p in enabled_providers if getattr(p, "provider_id", "") == "pyth_stress_band"), None)
    if pyth_provider and pyth_anomalies:
        manifest = pyth_provider.manifest()
        for py_item in pyth_anomalies:
            query_payload = deps.normalize_query_for_provider(pyth_provider, py_item)
            spread_bps = float(query_payload.get("confidence_spread_bps") or py_item.get("confidence_spread_bps") or 5.0)
            stress_level = str(py_item.get("stress_level") or "CALM")

            spread_score = min(50.0, spread_bps * 10.0)
            score = round(min(100.0, 35.0 + spread_score + (15.0 if stress_level != "CALM" else 5.0)), 1)
            suggested_tier = "full" if score >= 65 else "preview"

            reasons = []
            if stress_level in ("CRITICAL_VOLATILITY", "ELEVATED_STRESS"):
                reasons.append(f"anomalous {spread_bps} bps confidence interval widening")
            else:
                reasons.append(f"low-latency sub-second {spread_bps} bps confidence band")
            reasons.append(f"regime: {stress_level}")
            reasons.append("Pyth Hermes real-time websocket verifiable")
            reasons.append("EIP-712 automated hedge order synthesizable")

            try:
                score_result = pyth_provider.score({"query": query_payload, "tier": suggested_tier})
                amount_usdc = score_result["amount_usdc"]
                complexity = score_result.get("complexity_score", 0.90)
            except Exception:
                amount_usdc = 0.005 if suggested_tier == "full" else 0.002
                complexity = 0.90

            pid = pyth_provider.provider_id
            if _gate_enabled():
                check = _signal_verifiability(pid, query_payload)
                if not check["verifiable"]:
                    continue
                evidence_exchange = check.get("exchange") or "Pyth"
            else:
                evidence_exchange = "Pyth"
            sla_state = "preverified" if is_preverified(pid, str(py_item.get("symbol") or "")) else "verifiable"

            picks.append({
                "provider_id": pid,
                "provider_name": manifest.get("name", "Pyth Low-Latency Stress Band"),
                "provider_category": manifest.get("category", "market_stress"),
                "symbol": py_item.get("symbol"),
                "score": score,
                "suggested_tier": suggested_tier,
                "suggested_price_usdc": amount_usdc,
                "complexity_score": complexity,
                "estimated_value": "High" if score >= 70 else "Medium" if score >= 45 else "Exploratory",
                "reasons": reasons[:4],
                "query": query_payload,
                "live": py_item,
                "exchange": "Pyth",
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


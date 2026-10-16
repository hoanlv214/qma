"""GenLayer SLA and Arc verdict reconciliation service.

Handles sale-time verifiability, pre-warm consensus execution, report manifest
binding, validator receipt matching, circuit breaking, and settlement loop.
"""

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, Optional

import requests
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

import paid_intelligence_kit as paid_kit
from backend.app.core import state
from backend.app.core.config import (
    ARC_GATEWAY_BASE_URL,
    ARC_GATEWAY_INTERNAL_SECRET,
    PAYMENT_RESOURCE_TYPE,
    PAYMENT_WALLET_ADDRESS,
)
from backend.app.core.static_config import app_setting
from backend.app.services import genlayer_arbiter
from backend.app.services.arc_verdict_settlement import (
    ArcVerdictSettlementError,
    ensure_arc_settlement_plan,
    execute_arc_settlement,
    public_arc_settlement,
)
from backend.app.services.circle_client import refresh_invoice_batch_tx
from backend.app.services.market_epoch import get_epoch, mark_epoch_tx, mark_epoch_verdict
from backend.app.services.payment_state_machine import invoice_split_mode
from backend.app.services.providers_meta import get_provider_or_404
from backend.app.services.security import normalize_query_for_provider
from backend.app.services.report_generator_service import (
    _PUBLIC_VERIFICATION_CLAIMS,
    _canonical_report_json,
    build_provider_report,
)

logger = logging.getLogger("QMA-GenLayerReconcile")

_MEXC_ANCHORED_PROVIDERS = {"funding_memory", "oi_memory"}
_EVIDENCE_CHECK_TTL_SECONDS = 60
_EVIDENCE_CHECK_CACHE: Dict[str, Any] = {}

_GENLAYER_PREWARM_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="genlayer_prewarm",
)


def _get_backend_main():
    """Lazy import of backend.app.main to allow monkeypatched helpers in test suites."""
    from backend.app import main
    return main


def _genlayer_target_exchange(evidence_url: str) -> str:
    if "bybit.com" in evidence_url:
        return "BYBIT"
    if "binance.com" in evidence_url:
        return "Binance"
    return "MEXC"


def _gate_enabled() -> bool:
    return bool(app_setting("providers", "signalVerifiabilityGate"))


def _mexc_evidence_has_market_data(evidence_url: str) -> tuple:
    cached = _EVIDENCE_CHECK_CACHE.get(evidence_url)
    now = time.time()
    if cached and cached[0] > now:
        return cached[1], cached[2]
    ok, reason = False, "unchecked"
    try:
        res = requests.get(evidence_url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if res.status_code != 200:
            reason = f"evidence endpoint returned HTTP {res.status_code}"
        else:
            payload = res.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if not data or (isinstance(data, (list, dict)) and len(data) == 0):
                reason = "evidence endpoint returned no market data for this symbol"
            else:
                ok, reason = True, "ok"
    except Exception as exc:
        reason = f"evidence endpoint unreachable: {exc}"
    _EVIDENCE_CHECK_CACHE[evidence_url] = (now + _EVIDENCE_CHECK_TTL_SECONDS, ok, reason)
    return ok, reason


def _signal_verifiability(provider_id: str, query: dict) -> Dict[str, Any]:
    symbol = str(query.get("symbol") or "")
    evidence_url = _genlayer_evidence_url({"provider_id": provider_id, "query": query, "symbol": symbol})
    target = _genlayer_target_exchange(evidence_url)

    if provider_id in _MEXC_ANCHORED_PROVIDERS and target in {"Binance", "BYBIT"}:
        return {
            "verifiable": False,
            "reason": f"evidence anchored to {target}, which GenLayer validators cannot fetch",
            "evidence_url": evidence_url,
            "exchange": target,
        }
    if "contract.mexc.com" in evidence_url:
        ok, reason = _mexc_evidence_has_market_data(evidence_url)
        return {
            "verifiable": bool(ok),
            "reason": reason,
            "evidence_url": evidence_url,
            "exchange": target,
        }
    return {"verifiable": True, "reason": "ok", "evidence_url": evidence_url, "exchange": target}


def _ensure_signal_verifiable(provider_id: str, query: dict) -> None:
    if not _gate_enabled():
        return
    symbol = str(query.get("symbol") or "")
    check = _signal_verifiability(provider_id, query)
    if not check["verifiable"]:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "signal_not_verifiable",
                "message": (
                    f"{symbol} cannot be GenLayer-verified right now: {check['reason']}. "
                    "Nothing was charged."
                ),
                "symbol": symbol,
                "evidence_url": check["evidence_url"],
                "reason": check["reason"],
            },
        )


def _report_verification_manifest(report: Any, invoice: dict, target_venue: str = "MEXC") -> dict:
    report_data = report if isinstance(report, dict) else {}
    payload = report_data.get("payload")
    source: dict[str, Any] = payload if isinstance(payload, dict) else report_data
    inner_raw = source.get("payload")
    inner: dict[str, Any] = inner_raw if isinstance(inner_raw, dict) else {}
    claims: dict[str, Any] = {}
    for key in _PUBLIC_VERIFICATION_CLAIMS:
        if key in inner:
            claims[key] = inner[key]
        elif key in source:
            claims[key] = source[key]
        elif key in report_data:
            claims[key] = report_data[key]
    if "declared_confidence" not in claims and "confidence" in report_data:
        claims["declared_confidence"] = report_data["confidence"]
    if target_venue:
        claims["exchange"] = target_venue

    query_payload = dict(invoice.get("query") or {})
    if target_venue:
        query_payload["exchange"] = target_venue

    return jsonable_encoder({
        "invoice_id": invoice.get("invoice_id"),
        "provider_id": invoice.get("provider_id"),
        "tier": invoice.get("tier"),
        "symbol": invoice.get("symbol"),
        "query_hash": invoice.get("query_hash"),
        "query": query_payload,
        "claims": claims,
    })


def _genlayer_evidence_url(invoice: dict) -> str:
    q_url = (invoice.get("query") or {}).get("evidence_url") or invoice.get("evidence_url")
    fetchable_prefixes = ("https://contract.mexc.com/",)
    if q_url and any(q_url.startswith(prefix) for prefix in fetchable_prefixes):
        return q_url

    raw_symbol = str(invoice.get("symbol") or (invoice.get("query") or {}).get("symbol") or "").strip()
    clean_symbol = raw_symbol.replace("-", "_").replace("/", "_").upper()
    if not clean_symbol.endswith("_USDT") and not clean_symbol.endswith("USDT"):
        clean_symbol = f"{clean_symbol}_USDT"
    elif clean_symbol.endswith("USDT") and not clean_symbol.endswith("_USDT"):
        clean_symbol = f"{clean_symbol[:-4]}_USDT"

    return f"https://contract.mexc.com/api/v1/contract/funding_rate/{clean_symbol}"


def prewarm_genlayer_sla_for_invoice(invoice: dict) -> Optional[dict]:
    try:
        provider_id = invoice.get("provider_id", "funding_memory")
        symbol = str(invoice.get("symbol") or "")
        query_hash = str(invoice.get("query_hash") or "")
        tier = invoice.get("tier", "preview")

        provider = get_provider_or_404(_get_backend_main().provider_registry, provider_id)
        normalized_query = normalize_query_for_provider(provider, invoice.get("query") or {})

        report = invoice.get("_verification_report")
        if report is None and invoice.get("market_epoch_key"):
            epoch_snapshot = get_epoch(str(invoice["market_epoch_key"]))
            if epoch_snapshot is not None:
                report = epoch_snapshot["report"]
        main_mod = _get_backend_main()
        if report is None:
            report = main_mod.build_provider_report(
                provider=provider,
                normalized_query=normalized_query,
                invoice_id=invoice.get("invoice_id", "prewarm"),
                invoice=invoice,
                required_tier=tier,
            )

        try:
            canonical_report = main_mod._canonical_report_json(report)
        except Exception:
            return None
        report_hash = hashlib.sha256(canonical_report.encode("utf-8")).hexdigest()

        cached = genlayer_arbiter.get_cached_sla_verdict(
            symbol=symbol,
            query_hash=query_hash,
            report_hash=report_hash,
        )
        if cached and cached.get("verdict") == "VALID":
            return cached

        evidence_url = _genlayer_evidence_url(invoice)
        target_venue = _genlayer_target_exchange(evidence_url)

        manifest_dict = main_mod._report_verification_manifest(report, invoice, target_venue=target_venue)
        verification_manifest = main_mod._canonical_report_json(manifest_dict)
        manifest_claims = manifest_dict.get("claims", {})

        try:
            receipt = genlayer_arbiter.verify_report(
                invoice_id=invoice.get("invoice_id", f"prewarm_{int(time.time())}"),
                buyer=invoice.get("buyer_wallet_address") or invoice.get("payer_address") or "",
                provider=invoice.get("owner_wallet") or "",
                symbol=symbol,
                expected_anomaly=(
                    f"Verify {symbol} market anomaly against live {target_venue} evidence: "
                    f"strategy={manifest_claims.get('recommended_strategy') or manifest_claims.get('bias') or manifest_claims.get('anomaly') or 'funding_arbitrage'}, "
                    f"declared_confidence={manifest_claims.get('declared_confidence', 0.6)}"
                ),
                query_hash=query_hash,
                report_hash=report_hash,
                verification_manifest=verification_manifest,
                evidence_url=evidence_url,
                transaction_hash=(
                    get_epoch(str(invoice.get("market_epoch_key") or "")).get("tx_hash")
                    if invoice.get("market_epoch_key")
                    else None
                ),
            )
        except genlayer_arbiter.GenLayerVerificationError as exc:
            if invoice.get("market_epoch_key"):
                mark_epoch_tx(str(invoice["market_epoch_key"]), exc.transaction_hash)
            raise
        return receipt
    except Exception as exc:
        logger.debug("Opportunistic GenLayer pre-warm for %s ended or skipped: %s", invoice.get("symbol"), exc)
        return None


def _trigger_genlayer_prewarm_in_background(invoice: dict) -> None:
    if not invoice:
        return

    def _worker():
        for attempt in range(1, 4):
            try:
                receipt = prewarm_genlayer_sla_for_invoice(invoice)
                if receipt is not None:
                    return
            except Exception as exc:
                logger.debug("Opportunistic GenLayer pre-warm error on attempt %d: %s", attempt, exc)
            if attempt < 3:
                time.sleep(20 * attempt)

    try:
        _GENLAYER_PREWARM_EXECUTOR.submit(_worker)
    except Exception as exc:
        logger.debug("Opportunistic GenLayer pre-warm queue full or rejected: %s", exc)


def verify_invoice_report_with_genlayer(invoice_id: str, invoice: dict) -> dict:
    with state.cross_process_lock("genlayer_verify:" + invoice_id):
        return _verify_invoice_report_with_genlayer_locked(invoice_id, invoice)


def _sync_single_payment_event(invoice: dict, reload_state: bool = True) -> None:
    main_mod = _get_backend_main()
    settlement_id = invoice.get("settlement_id")
    if not settlement_id or invoice_split_mode(invoice) == "x402_direct_split":
        return
    if reload_state:
        main_mod.reload_persistent_state(include_reports=False)
    if not any(event.get("settlement_id") == settlement_id for event in state.payment_events):
        new_event = {
            "invoice_id": invoice.get("invoice_id"),
            "symbol": invoice.get("symbol"),
            "provider_id": invoice.get("provider_id", "funding_memory"),
            "provider_owner_wallet": invoice.get("owner_wallet"),
            "buyer_type": invoice.get("buyer_type", "human"),
            "synthetic": invoice.get("synthetic", False),
            "agent_label": invoice.get("agent_label"),
            "run_source": invoice.get("run_source"),
            "tier": invoice.get("tier", "full"),
            "resource_type": invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
            "query": invoice.get("query"),
            "query_hash": invoice.get("query_hash"),
            "payer_address": invoice.get("payer_address"),
            "buyer_wallet_address": invoice.get("buyer_wallet_address"),
            "seller_address": PAYMENT_WALLET_ADDRESS,
            "amount_usdc": invoice.get("amount"),
            "amount_raw": invoice.get("amount_raw"),
            "pricing": invoice.get("pricing"),
            "settlement": invoice.get("settlement"),
            "accounting": invoice.get("accounting"),
            "settlement_id": settlement_id,
            "gateway_status": invoice.get("gateway_status"),
            "transaction_hash": invoice.get("transaction_hash"),
            "explorer_url": invoice.get("explorer_url"),
            "paid_at": invoice.get("paid_at") or time.time(),
            "arc_settlement": public_arc_settlement(invoice.get("arc_settlement")),
        }
        state.payment_events.append(new_event)
        main_mod._save_single_payment_event(new_event)


def _sync_arc_settlement_to_payment_events(invoice: dict) -> None:
    main_mod = _get_backend_main()
    public_plan = public_arc_settlement(invoice.get("arc_settlement"))
    if not public_plan:
        return
    for event in state.payment_events:
        if str(event.get("invoice_id") or "") != str(invoice.get("invoice_id") or ""):
            continue
        if event.get("arc_settlement") != public_plan:
            event["arc_settlement"] = public_plan
            main_mod._save_single_payment_event(event)


def settle_genlayer_verdict_on_arc(invoice_id: str, invoice: dict) -> dict | None:
    if invoice_split_mode(invoice) == "x402_direct_split":
        return None
    main_mod = _get_backend_main()
    try:
        with state.cross_process_lock("arc_settlement_plan:" + invoice_id):
            ensure_arc_settlement_plan(invoice)
            main_mod._save_invoice(invoice)
        plan = execute_arc_settlement(
            invoice,
            gateway_base_url=ARC_GATEWAY_BASE_URL,
            internal_secret=ARC_GATEWAY_INTERNAL_SECRET,
            save_invoice=main_mod._save_invoice,
        )
    except ArcVerdictSettlementError as exc:
        logger.error("Cannot create Arc verdict settlement for invoice %s: %s", invoice_id, exc)
        return None
    _sync_arc_settlement_to_payment_events(invoice)
    try:
        from backend.app.services.euthyna_audit import euthyna_audit_engine
        from backend.app.services.usyc_treasury import usyc_treasury_service

        liquid_bal = usyc_treasury_service.get_liquid_usdc_balance()
        pos = usyc_treasury_service.query_onchain_position()
        arc_tx = invoice.get("transaction_hash") or (invoice.get("arc_settlement") or {}).get("transaction_hash")
        amount_val = float(invoice.get("amount") or 0.0)
        euthyna_audit_engine.record_action(
            action="VENDOR_PAYOUT",
            actor=invoice.get("buyer_wallet_address") or "0xAutonomousBuyer",
            amount_usdc=amount_val,
            balance_before=liquid_bal,
            balance_after=max(0.0, round(liquid_bal - amount_val, 6)),
            usyc_shares=pos.get("usyc_shares", 0.0),
            policy_rule="RULE_ARBITER_VERIFIED_SETTLEMENT",
            reasoning=f"GenLayer validated deliverable for invoice {invoice_id}. Settlement executed on Arc.",
            tx_hash=arc_tx,
            provider_id=invoice.get("provider_id"),
            genlayer_consensus=(invoice.get("genlayer") or {}).get("verdict"),
        )
    except Exception as exc:
        logger.debug("Could not record Arc verdict settlement in Euthyna audit: %s", exc)
    return plan


def reconcile_arc_verdict_settlements_once(max_invoices: int = 20) -> int:
    main_mod = _get_backend_main()
    try:
        fresh_invoices = main_mod._load_invoices()
        if fresh_invoices:
            for k, inv in fresh_invoices.items():
                if k not in state.invoices_db:
                    state.invoices_db[k] = inv
                else:
                    curr = state.invoices_db[k]
                    if curr.get("status") == "pending" and inv.get("status") != "pending":
                        state.invoices_db[k] = inv
    except Exception as exc:
        logger.debug("Reconcile load invoices failed: %s", exc)

    settled_but_unsynced = [
        invoice
        for invoice in list(state.invoices_db.values())
        if invoice.get("status") == "verification_pending" and invoice.get("settlement_id")
    ]
    if settled_but_unsynced:
        try:
            main_mod.reload_persistent_state(include_reports=False)
        except Exception:
            logger.exception("State reload before payment event sync failed")
    for invoice in settled_but_unsynced:
        try:
            _sync_single_payment_event(invoice, reload_state=False)
        except Exception:
            logger.exception("Payment event sync failed for invoice %s", invoice.get("invoice_id"))

    pending_verifications = settled_but_unsynced[:max_invoices]
    for invoice in pending_verifications:
        try:
            inv_id = str(invoice.get("invoice_id") or "")
            verify_invoice_report_with_genlayer(inv_id, invoice)
        except (HTTPException, genlayer_arbiter.GenLayerVerificationError):
            pass
        except Exception:
            logger.exception("GenLayer background reconciliation failed for invoice %s", invoice.get("invoice_id"))

    candidates = [
        invoice
        for invoice in list(state.invoices_db.values())
        if (invoice.get("genlayer") or {}).get("verdict") in {"VALID", "INVALID"}
        and (invoice.get("arc_settlement") or {}).get("status") not in {"confirmed", "failed_terminal"}
        and invoice_split_mode(invoice) != "x402_direct_split"
    ][:max_invoices]
    for invoice in candidates:
        try:
            refresh_invoice_batch_tx(invoice)
            settle_genlayer_verdict_on_arc(str(invoice.get("invoice_id") or ""), invoice)
        except Exception:
            logger.exception(
                "Arc verdict settlement reconciliation failed for invoice %s",
                invoice.get("invoice_id"),
            )
    return len(candidates) + len(pending_verifications)


async def _arc_settlement_reconcile_loop() -> None:
    interval = max(5.0, float(app_setting("payment", "arcSettlementReconcileSeconds")))
    while True:
        try:
            await asyncio.sleep(interval)
            await asyncio.to_thread(reconcile_arc_verdict_settlements_once)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Arc settlement reconcile tick failed; retrying next cycle")


def _verify_invoice_report_with_genlayer_locked(invoice_id: str, invoice: dict) -> dict:
    main_mod = _get_backend_main()
    if invoice.get("status") == "refunded":
        raise HTTPException(
            status_code=409,
            detail={"error": "invoice_refunded", "message": "Invoice is refunded and cannot be paid."},
        )
    if invoice.get("status") == "paid" and (invoice.get("genlayer") or {}).get("verdict") == "VALID":
        return invoice.get("genlayer")
    if invoice.get("status") in {"verification_rejected", "refunded"} and (invoice.get("genlayer") or {}).get(
        "verdict"
    ) == "INVALID":
        return invoice.get("genlayer")

    provider_id = invoice.get("provider_id", "funding_memory")
    provider = get_provider_or_404(_get_backend_main().provider_registry, provider_id)
    normalized_query = normalize_query_for_provider(provider, invoice.get("query") or {})
    invoice["paid_at"] = invoice.get("paid_at") or time.time()
    main_mod = _get_backend_main()
    epoch_snapshot = (
        main_mod.get_epoch(str(invoice.get("market_epoch_key") or "")) if invoice.get("market_epoch_key") else None
    )
    report = invoice.get("_verification_report")
    if epoch_snapshot is not None:
        report = epoch_snapshot["report"]
    elif report is None and isinstance(invoice.get("verification_report_canonical"), str):
        try:
            report = json.loads(invoice["verification_report_canonical"])
        except Exception:
            report = None
    if report is None:
        report = main_mod.build_provider_report(
            provider=provider,
            normalized_query=normalized_query,
            invoice_id=invoice_id,
            invoice=invoice,
            required_tier=invoice.get("tier", "full"),
        )

    try:
        canonical_report = main_mod._canonical_report_json(report)
    except (TypeError, ValueError) as exc:
        invoice["status"] = "verification_pending"
        main_mod._save_invoice(invoice)
        raise HTTPException(
            status_code=503,
            detail={"error": "verification_payload_invalid", "message": str(exc)},
        ) from exc

    report_hash = hashlib.sha256(canonical_report.encode("utf-8")).hexdigest()
    evidence_url = _genlayer_evidence_url(invoice)
    target_venue = _genlayer_target_exchange(evidence_url)

    manifest_dict = main_mod._report_verification_manifest(report, invoice, target_venue=target_venue)
    verification_manifest = main_mod._canonical_report_json(manifest_dict)
    manifest_claims = manifest_dict.get("claims", {})
    if len(verification_manifest.encode("utf-8")) > 12000:
        invoice["status"] = "verification_pending"
        main_mod._save_invoice(invoice)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "verification_manifest_too_large",
                "message": "The public GenLayer verification manifest exceeds 12 KB.",
            },
        )
    previous_hash = invoice.get("verification_report_hash")
    if previous_hash and previous_hash != report_hash:
        if invoice.get("settlement_id"):
            invoice["status"] = "verification_rejected"
            invoice["access_status"] = "verification_rejected"
            existing_genlayer = invoice.get("genlayer")
            invoice["genlayer"] = {
                **(existing_genlayer if isinstance(existing_genlayer, dict) else {}),
                "error": "verification_report_hash_changed",
                "verdict": existing_genlayer.get("verdict") if isinstance(existing_genlayer, dict) else None,
            }
            invoice.pop("_verification_report", None)
            main_mod._save_invoice(invoice)
            settle_genlayer_verdict_on_arc(invoice_id, invoice)
            logger.warning(
                "Report hash mismatch for settled invoice %s; moved to verification_rejected and scheduled buyer refund.",
                invoice_id,
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "verification_report_hash_changed",
                    "message": "The verified report content changed after settlement; the invoice moved to verification_rejected and a buyer refund was scheduled.",
                },
            )
        raise HTTPException(
            status_code=409,
            detail="The cached report changed while GenLayer verification was pending.",
        )

    invoice["_verification_report"] = report
    invoice["verification_report_hash"] = report_hash
    invoice["verification_report_canonical"] = canonical_report
    invoice["status"] = "verification_pending"
    main_mod._save_invoice(invoice)

    gl_state = invoice.get("genlayer") if isinstance(invoice.get("genlayer"), dict) else {}
    epoch_tx = epoch_snapshot.get("tx_hash") if epoch_snapshot else None
    pending_tx = gl_state.get("transaction_hash") or epoch_tx
    resubmit_after_sec = int(app_setting("genlayer", "resubmitAfterSeconds"))
    pending_since = float(gl_state.get("pending_since") or invoice.get("paid_at") or time.time())
    if pending_tx and (time.time() - pending_since) > resubmit_after_sec:
        resubmit_count = int(gl_state.get("resubmit_count") or 0)
        if resubmit_count >= 3:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "genlayer_verification_stalled",
                    "message": "Repeated GenLayer verification submissions did not produce a verdict; report access remains locked.",
                    "transaction_hash": pending_tx,
                },
            )
        gl_state["superseded_transactions"] = list(gl_state.get("superseded_transactions") or []) + [pending_tx]
        gl_state["resubmit_count"] = resubmit_count + 1
        pending_tx = None
    try:
        receipt = genlayer_arbiter.verify_report(
            invoice_id=invoice_id,
            buyer=invoice.get("payer_address") or invoice.get("buyer_wallet_address") or "",
            provider=invoice.get("owner_wallet") or "",
            symbol=str(invoice.get("symbol") or ""),
            expected_anomaly=(
                f"Verify {invoice.get('symbol')} market anomaly against live {target_venue} evidence: "
                f"strategy={manifest_claims.get('recommended_strategy') or manifest_claims.get('bias') or manifest_claims.get('anomaly') or 'funding_arbitrage'}, "
                f"declared_confidence={manifest_claims.get('declared_confidence', 0.6)}"
            ),
            query_hash=str(invoice.get("query_hash") or ""),
            report_hash=report_hash,
            verification_manifest=verification_manifest,
            evidence_url=evidence_url,
            transaction_hash=pending_tx,
        )
    except genlayer_arbiter.GenLayerVerificationError as exc:
        gl_state = invoice.get("genlayer") if isinstance(invoice.get("genlayer"), dict) else {}
        next_genlayer = {
            **gl_state,
            "status": "VERIFICATION_PENDING",
            "verdict": "PENDING",
            "contract_address": genlayer_arbiter.GENLAYER_CONTRACT_ADDRESS or None,
            "transaction_hash": exc.transaction_hash or pending_tx,
            "error": str(exc),
        }
        if getattr(exc, "failed", False):
            next_genlayer["transaction_hash"] = None
            next_genlayer["pending_since"] = gl_state.get("pending_since") or time.time()
            next_genlayer["resubmit_count"] = int(gl_state.get("resubmit_count") or 0) + 1
            if exc.transaction_hash:
                next_genlayer["superseded_transactions"] = list(gl_state.get("superseded_transactions") or []) + [
                    exc.transaction_hash
                ]
        else:
            next_genlayer.setdefault("pending_since", time.time())
        if epoch_snapshot is not None:
            mark_epoch_tx(epoch_snapshot["key"], next_genlayer.get("transaction_hash"))
        invoice["status"] = "verification_pending"
        invoice["genlayer"] = next_genlayer
        main_mod._save_invoice(invoice)
        _sync_single_payment_event(invoice)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "genlayer_verification_pending",
                "message": "Payment is settled, but no finalized GenLayer verdict is available. Report access remains locked.",
                "transaction_hash": exc.transaction_hash or pending_tx,
            },
        ) from exc

    invoice["genlayer"] = {
        **{k: gl_state[k] for k in ("superseded_transactions", "resubmit_count", "pending_since") if k in gl_state},
        **receipt,
    }
    if epoch_snapshot is not None:
        mark_epoch_verdict(epoch_snapshot["key"], str(receipt.get("verdict") or ""))
    invoice["sla_state"] = "verified" if str(receipt.get("verdict") or "").upper() == "VALID" else "rejected"
    receipt_report_hash = receipt.get("report_hash") if isinstance(receipt, dict) else None
    if (receipt_report_hash is not None and str(receipt_report_hash) != str(report_hash)) or (
        receipt.get("verdict") != "INVALID" and receipt_report_hash is None
    ):
        tx_hash = (receipt.get("transaction_hash") if isinstance(receipt, dict) else None) or pending_tx
        invoice["status"] = "verification_pending"
        invoice["genlayer"] = {
            "status": "VERIFICATION_PENDING",
            "verdict": "PENDING",
            "contract_address": genlayer_arbiter.GENLAYER_CONTRACT_ADDRESS or None,
            "transaction_hash": tx_hash,
            "error": "genlayer_receipt_report_hash_mismatch",
        }
        main_mod._save_invoice(invoice)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "genlayer_receipt_report_hash_mismatch",
                "message": "Payment is settled, but GenLayer receipt does not match report content hash. Report access remains locked.",
                "transaction_hash": tx_hash,
            },
        )

    if receipt["verdict"] == "INVALID":
        invoice["status"] = "verification_rejected"
        invoice["access_status"] = "verification_rejected"
        invoice.pop("_verification_report", None)
        main_mod._save_invoice(invoice)
        settle_genlayer_verdict_on_arc(invoice_id, invoice)
        logger.warning(
            "GenLayer rejected invoice %s; report locked and the evidence-bound Arc refund was scheduled.",
            invoice_id,
        )
        target_session_id = invoice.get("session_id")
        run_source = invoice.get("run_source")
        if not target_session_id and run_source and str(run_source).startswith("agent_session_"):
            target_session_id = str(run_source).replace("agent_session_", "")
        if target_session_id:
            try:
                from backend.app.services.incident_engine import execute_session_control, record_incident

                record_incident(
                    session_id=str(target_session_id),
                    severity="P1_CRITICAL",
                    category="GENLAYER_SLA_VIOLATION",
                    rule="FAIL_CLOSED_VERIFIER",
                    details=f"GenLayer SLA verdict INVALID on invoice {invoice_id}. Automatic circuit breaker triggered.",
                    actor_type="SYSTEM_CIRCUIT_BREAKER",
                    trace_id=receipt.get("transaction_hash") or invoice.get("settlement_id"),
                    financial_context={
                        "attempted_amount_usdc": float(invoice.get("amount") or 0.0),
                        "provider_id": invoice.get("provider_id"),
                    },
                )
                execute_session_control(
                    session_id=str(target_session_id),
                    action="pause",
                    reason=f"Auto-pause: GenLayer SLA rejected report for invoice {invoice_id}",
                    storage=getattr(main_mod, "storage_backend", state.storage_backend),
                )
            except Exception as auto_err:
                logger.error(
                    "Failed to auto-pause session %s on GenLayer SLA rejection: %s", target_session_id, auto_err
                )
        return receipt

    if invoice_split_mode(invoice) != "x402_direct_split":
        ensure_arc_settlement_plan(invoice)
        invoice.setdefault("accounting", {})["distribution_mode"] = "automatic_genlayer_settlement"
    invoice["status"] = "paid"
    invoice["verified_report"] = report
    invoice.pop("_verification_report", None)
    main_mod._save_invoice(invoice)
    paid_reports_dict = getattr(main_mod, "paid_reports", state.paid_reports)
    entitlement_record = paid_kit.record_entitlement(paid_reports_dict, invoice=invoice, report=report)
    if entitlement_record and isinstance(entitlement_record, dict) and entitlement_record.get("entitlement_id"):
        main_mod._save_single_paid_report(entitlement_record["entitlement_id"], entitlement_record)
    else:
        main_mod._save_paid_reports(state.paid_reports)
    _sync_single_payment_event(invoice)
    settle_genlayer_verdict_on_arc(invoice_id, invoice)
    logger.info(
        "GenLayer verified invoice %s at %s with report hash %s",
        invoice_id,
        receipt.get("transaction_hash"),
        report_hash,
    )
    return receipt

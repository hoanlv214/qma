"""Payment domain service for QMA.

Handles invoice lifecycle, split payments, verification, token authorization,
and Gateway withdrawal settlements.
"""

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

import requests
from fastapi import HTTPException, Query, status

import paid_intelligence_kit as paid_kit
from backend.app.core import state
from backend.app.core.config import (
    ARC_EXPLORER,
    ARC_GATEWAY_API,
    ARC_GATEWAY_BASE_URL,
    ARC_GATEWAY_INTERNAL_SECRET,
    ARC_TESTNET_USDC,
    ARC_USDC_ADDRESS,
    INVOICE_TTL_SECONDS,
    IS_TESTNET,
    PAYMENT_AMOUNT_USDC,
    PAYMENT_NETWORK,
    PAYMENT_NETWORK_NAME,
    PAYMENT_RESOURCE_TYPE,
    PAYMENT_WALLET_ADDRESS,
    PLATFORM_TREASURY_ADDRESS,
    SETTLEMENT_CURRENCY,
    SETTLEMENT_RAIL,
    WITHDRAW_MODE,
    is_treasury_halted,
)
from backend.app.core.x402_spec import build_402_challenge_payload
from backend.app.schemas import InvoiceRequest, PaymentVerifyRequest
from backend.app.services.creator_claims import enforce_withdraw_relay_policy, record_withdraw_relay, validate_withdraw_intent
from backend.app.services.invoice_builder import (
    aggregate_split_gateway_status,
    get_invoice_or_402,
    hydrate_payment_schema,
    invoice_payment_state_response,
    payment_requirement,
    refresh_split_invoice_status,
    split_paid_legs,
)
from backend.app.services.market_epoch import begin_or_get_epoch
from backend.app.services.payment_signing import raw_usdc_str, verify_access_token, verify_split_receipt
from backend.app.services.payment_state_machine import (
    invoice_has_failed_settlement,
    invoice_required_split_legs,
    invoice_split_mode,
)
from backend.app.services.providers_meta import (
    get_provider_or_404,
    provider_ids_by_revenue_wallet,
    provider_revenue_wallet,
    sync_split_payment_events,
)
from backend.app.services.report_generator_service import (
    _build_epoch_snapshot,
    _canonical_report_json,
    build_provider_report,
)
from backend.app.services.security import canonical_query_payload, model_to_dict, normalize_query_for_provider, query_fingerprint
from backend.app.services.wallet_utils import bytes32_to_address, normalize_address, same_address

logger = logging.getLogger("QMA-PaymentService")


def _get_backend_main():
    from backend.app import main
    return main


def _sync_state(main_mod, invoice_id: Optional[str] = None):
    main_state = getattr(main_mod, "state", state)
    mod_db = getattr(main_mod, "invoices_db", None)
    st_db = getattr(main_state, "invoices_db", getattr(state, "invoices_db", None))
    if invoice_id:
        if mod_db and invoice_id in mod_db:
            invoices_db = mod_db
        elif st_db and invoice_id in st_db:
            invoices_db = st_db
        elif mod_db is not None and len(mod_db) > 0:
            invoices_db = mod_db
        elif st_db is not None:
            invoices_db = st_db
        else:
            invoices_db = mod_db if mod_db is not None else {}
    else:
        if mod_db is not None and len(mod_db) > 0:
            invoices_db = mod_db
        elif st_db is not None:
            invoices_db = st_db
        else:
            invoices_db = mod_db if mod_db is not None else {}

    payment_events = getattr(main_mod, "payment_events", None)
    if payment_events is None:
        payment_events = getattr(main_state, "payment_events", getattr(state, "payment_events", []))

    load_invoices_fn = getattr(main_mod, "load_invoices", getattr(main_mod, "_load_invoices", None))
    save_invoice_fn = getattr(main_mod, "save_invoice", getattr(main_mod, "_save_invoice", None))
    return invoices_db, load_invoices_fn, save_invoice_fn


def refresh_split_leg_batch_txs(invoice: dict) -> bool:
    main_mod = _get_backend_main()
    if invoice_split_mode(invoice) != "x402_direct_split":
        return False
    changed = False
    for leg in split_paid_legs(invoice):
        temp_event = {
            "settlement_id": leg.get("settlement_id"),
            "gateway_status": leg.get("gateway_status"),
            "transaction_hash": leg.get("transaction_hash"),
            "explorer_url": leg.get("explorer_url"),
        }
        if main_mod.refresh_event_batch_tx(temp_event):
            leg["gateway_status"] = temp_event.get("gateway_status")
            leg["transaction_hash"] = temp_event.get("transaction_hash")
            leg["explorer_url"] = temp_event.get("explorer_url")
            changed = True
    if changed:
        invoice["gateway_status"] = aggregate_split_gateway_status(invoice)
    return changed


def authorized_gateway_withdraw_depositor(address: str) -> dict:
    main_mod = _get_backend_main()
    depositor = normalize_address(address)
    if same_address(depositor, PAYMENT_WALLET_ADDRESS) or same_address(depositor, PLATFORM_TREASURY_ADDRESS):
        return {"address": depositor, "role": "platform_treasury", "provider_ids": []}
    pids = provider_ids_by_revenue_wallet(main_mod.provider_registry, depositor)
    if pids:
        return {"address": depositor, "role": "provider_revenue_wallet", "provider_ids": pids}
    raise HTTPException(status_code=403, detail="This wallet is not authorized to withdraw QMA Gateway balance.")


def create_invoice(req: InvoiceRequest) -> dict:
    main_mod = _get_backend_main()
    req_data = model_to_dict(req)
    provider_id = req_data.pop("provider_id", "funding_memory")
    buyer_type = req_data.pop("buyer_type", "human")
    tier = paid_kit.normalize_tier(req_data.pop("tier", "full"))
    resource_type = req_data.pop("resource_type", PAYMENT_RESOURCE_TYPE) or PAYMENT_RESOURCE_TYPE
    synthetic = bool(req_data.pop("synthetic", False))
    agent_label = req_data.pop("agent_label", None)
    run_source = req_data.pop("run_source", None)
    buyer_wallet_address = req_data.pop("buyer_wallet_address", None)
    buyer_wallet_address = normalize_address(buyer_wallet_address) if buyer_wallet_address else None
    plan = req_data.pop("plan", None)
    if plan is None and hasattr(req, "plan"):
        plan = getattr(req, "plan", None)
    req_data.pop("candidate_id", None)
    req_data.pop("expected_price_usdc", None)
    provider = get_provider_or_404(main_mod.provider_registry, provider_id)
    req_data = normalize_query_for_provider(provider, req_data)

    main_mod._ensure_signal_verifiable(provider.provider_id, req_data)

    epoch_snapshot = None
    try:
        epoch_snapshot = begin_or_get_epoch(
            provider.provider_id,
            str(req_data.get("symbol") or ""),
            create_snapshot=lambda: _build_epoch_snapshot(provider, dict(req_data), tier),
        )
        req_data = dict(epoch_snapshot["query"])
    except Exception as exc:
        logger.debug("Market epoch snapshot unavailable for %s: %s", req_data.get("symbol"), exc)
        epoch_snapshot = None

    if hasattr(provider, "score"):
        context = {"query": req_data, "tier": tier}
        score_result = provider.score(context)
        amount_usdc = score_result["amount_usdc"]
        complexity_score = score_result.get("complexity_score", 0)
        base_usdc = amount_usdc
        _score_cache_key = score_result.get("_score_cache_key")
        declared_confidence = score_result.get("declared_confidence")
    else:
        quote = provider.quote_price(req_data, tier)
        amount_usdc = quote["amount_usdc"]
        complexity_score = quote["complexity_score"]
        base_usdc = quote["base_usdc"]
        _score_cache_key = None
        declared_confidence = None

    storage_backend = getattr(main_mod, "storage_backend", state.storage_backend)
    if run_source and str(run_source).startswith("agent_session_") and hasattr(storage_backend, "_request"):
        session_id = str(run_source).replace("agent_session_", "")
        is_uuid = False
        try:
            uuid.UUID(session_id)
            is_uuid = True
        except ValueError:
            pass

        if is_uuid:
            session_rows = storage_backend._request(
                "GET", "agent_sessions", params={"id": f"eq.{session_id}", "limit": "1"}
            )
            if session_rows:
                sess_status = str(session_rows[0].get("status") or "").lower()
                if sess_status in ("paused", "stopped", "completed", "failed"):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Agent session {session_id} is in status '{sess_status}'. Zero-spend invariant prevents creating invoices.",
                    )
                if session_rows[0].get("budget_usdc") is not None:
                    budget = float(session_rows[0]["budget_usdc"])
                    invoices = main_mod._load_invoices()
                    total_spent = sum(
                        float(inv.get("amount") or 0)
                        for inv in invoices.values()
                        if inv.get("run_source") == run_source and inv.get("status") in ("paid", "pending")
                    )
                    if total_spent + float(amount_usdc) > budget:
                        raise HTTPException(
                            status_code=402,
                            detail=f"Session budget exceeded. Limit: {budget} USDC. Spent/Pending: {total_spent} USDC. Requested: {amount_usdc} USDC.",
                        )

    invoice, requirement = paid_kit.create_invoice(
        query=req_data,
        tier=tier,
        amount_usdc=amount_usdc,
        resource_type=resource_type,
        provider_id=provider.provider_id,
        buyer_type=buyer_type,
        owner_wallet=getattr(provider, "owner_wallet", PAYMENT_WALLET_ADDRESS),
        network=PAYMENT_NETWORK,
        network_name=PAYMENT_NETWORK_NAME,
        seller_address=PLATFORM_TREASURY_ADDRESS,
        gateway_base_url=ARC_GATEWAY_BASE_URL,
        facilitator_url=ARC_GATEWAY_API,
        explorer_url=ARC_EXPLORER,
        ttl_seconds=INVOICE_TTL_SECONDS,
        settlement_rail=SETTLEMENT_RAIL,
        settlement_currency=SETTLEMENT_CURRENCY,
        settlement_token_address=ARC_USDC_ADDRESS,
        settlement_decimals=6,
    )

    if plan and isinstance(plan, dict):
        max_price_plan = plan.get("max_price_usdc")
        if max_price_plan is not None and float(invoice.get("amount") or 0) > float(max_price_plan or 0):
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "quoted_price_exceeds_policy_max",
                    "quoted": invoice.get("amount"),
                    "max": plan.get("max_price_usdc"),
                },
            )

    if _score_cache_key:
        invoice["_score_cache_key"] = _score_cache_key
    if declared_confidence is not None:
        invoice["declared_confidence"] = declared_confidence

    hydrate_payment_schema(invoice)

    smode = "seller_wallet"
    invoice["settlement"]["mode"] = smode
    invoice["verification_required"] = True

    rev_wallet = (
        provider_revenue_wallet(provider)
        if hasattr(provider, "revenue_wallet")
        else getattr(provider, "owner_wallet", PAYMENT_WALLET_ADDRESS)
    )
    rev_share_bps = int(getattr(provider, "revenue_share_bps", 8000))
    invoice["accounting"] = {
        **invoice.get("accounting", {}),
        "settlement_mode": smode,
        "creator_wallet": rev_wallet,
        "creator_share_bps": rev_share_bps,
        "platform_share_bps": 10000 - rev_share_bps,
        "distribution_mode": "automatic_genlayer_settlement",
    }

    invoice["wallet_address"] = PLATFORM_TREASURY_ADDRESS
    invoice["platform_treasury_wallet"] = normalize_address(PLATFORM_TREASURY_ADDRESS)
    invoice["synthetic"] = synthetic
    invoice["agent_label"] = agent_label
    invoice["run_source"] = run_source
    invoice["buyer_wallet_address"] = buyer_wallet_address

    if epoch_snapshot is not None:
        invoice["_verification_report"] = epoch_snapshot["report"]
        invoice["verification_report_hash"] = epoch_snapshot["report_hash"]
        invoice["market_epoch_key"] = epoch_snapshot["key"]
        invoice["sla_state"] = "preverified" if epoch_snapshot.get("state") == "valid" else "verifying"
    else:
        try:
            report = main_mod.build_provider_report(
                provider=provider,
                normalized_query=req_data,
                invoice_id=invoice["invoice_id"],
                invoice=invoice,
                required_tier=tier,
            )
            canonical_report = _canonical_report_json(report)
            report_hash = hashlib.sha256(canonical_report.encode("utf-8")).hexdigest()
            invoice["_verification_report"] = report
            invoice["verification_report_hash"] = report_hash
        except Exception as exc:
            logger.debug("Immediate build_provider_report on create_invoice skipped: %s", exc)
    evidence_url = main_mod._genlayer_evidence_url(invoice)
    target_venue = main_mod._genlayer_target_exchange(evidence_url)
    invoice["evidence_url"] = evidence_url
    invoice["exchange"] = (invoice.get("query") or {}).get("exchange") or target_venue
    if isinstance(invoice.get("query"), dict):
        if not invoice["query"].get("evidence_url"):
            invoice["query"]["evidence_url"] = evidence_url
        if not invoice["query"].get("exchange"):
            invoice["query"]["exchange"] = invoice["exchange"]
    state.invoices_db[invoice["invoice_id"]] = invoice
    main_mod._save_invoice(invoice)
    try:
        main_mod._trigger_genlayer_prewarm_in_background(invoice)
    except Exception as exc:
        logger.debug("Opportunistic GenLayer prewarm trigger skipped: %s", exc)
    return {
        "invoice_id": invoice["invoice_id"],
        "amount": invoice["amount"],
        "amount_usdc": invoice["amount"],
        "currency": invoice["settlement"]["currency"],
        "pricing": invoice["pricing"],
        "settlement": invoice["settlement"],
        "split": invoice.get("split"),
        "accounting": invoice["accounting"],
        "network": PAYMENT_NETWORK,
        "network_name": PAYMENT_NETWORK_NAME,
        "provider_id": invoice["provider_id"],
        "provider_name": getattr(provider, "provider_name", invoice["provider_id"]),
        "buyer_type": invoice["buyer_type"],
        "tier": invoice["tier"],
        "tier_label": paid_kit.SUPPORTED_TIERS[invoice["tier"]]["label"],
        "base_usdc": base_usdc,
        "complexity_score": complexity_score,
        "resource_type": invoice["resource_type"],
        "wallet_address": invoice["wallet_address"],
        "platform_treasury_wallet": invoice.get("platform_treasury_wallet"),
        "provider_owner_wallet": getattr(provider, "owner_wallet", PAYMENT_WALLET_ADDRESS),
        "synthetic": invoice.get("synthetic", False),
        "agent_label": invoice.get("agent_label"),
        "run_source": invoice.get("run_source"),
        "buyer_wallet_address": invoice.get("buyer_wallet_address"),
        "expires_at": invoice["expires_at"],
        "nonce": invoice["nonce"],
        "invoice_secret": invoice["invoice_secret"],
        "query_hash": invoice["query_hash"],
        "query": invoice.get("query"),
        "sla_state": invoice.get("sla_state"),
        "payment_requirement": requirement,
        "arc_gateway_url": requirement["resource"],
        "split_legs": invoice.get("split", {}).get("legs", []),
        "evidence_url": evidence_url,
        "exchange": invoice["exchange"],
    }


def get_payment_invoice_status(invoice_id: str, invoice_secret: str, refresh: bool = True) -> dict:
    main_mod = _get_backend_main()
    invoices_db, load_invoices_fn, save_invoice_fn = _sync_state(main_mod, invoice_id)
    invoice = get_invoice_or_402(
        invoices_db,
        invoice_id,
        load_invoices_fn=load_invoices_fn,
        invoice_secret=invoice_secret,
    )
    hydrate_payment_schema(invoice)
    if not hmac.compare_digest(str(invoice_secret), str(invoice.get("invoice_secret"))):
        raise HTTPException(
            status_code=402,
            detail={
                "error": "payment_required",
                "message": "Create and settle a USDC invoice before requesting this report.",
                "payment": payment_requirement(invoice_id=invoice_id),
            },
        )
    changed = False
    if main_mod.invoice_split_mode(invoice) == "x402_direct_split":
        old_status = invoice.get("status")
        refresh_split_invoice_status(invoice)
        if refresh:
            changed = main_mod.refresh_split_leg_batch_txs(invoice) or changed
        invoice["gateway_status"] = aggregate_split_gateway_status(invoice)
        changed = changed or old_status != invoice.get("status")
        if invoice.get("status") == "paid":
            sync_split_payment_events(invoice, save_event_fn=main_mod._save_single_payment_event)
    elif refresh:
        before = (invoice.get("gateway_status"), invoice.get("transaction_hash"), invoice.get("explorer_url"))
        main_mod.refresh_invoice_batch_tx(invoice)
        after = (invoice.get("gateway_status"), invoice.get("transaction_hash"), invoice.get("explorer_url"))
        changed = before != after
    if refresh and invoice.get("status") == "verification_pending" and invoice.get("settlement_id"):
        try:
            main_mod.verify_invoice_report_with_genlayer(invoice_id, invoice)
            changed = True
        except HTTPException as exc:
            if exc.status_code not in (409, 503):
                raise
        except Exception as exc:
            logger.warning("GenLayer verification in get_payment_invoice_status failed for %s: %s", invoice_id, exc)
    if refresh and (invoice.get("genlayer") or {}).get("verdict") in {"VALID", "INVALID"}:
        try:
            main_mod.settle_genlayer_verdict_on_arc(invoice_id, invoice)
            changed = True
        except Exception as exc:
            logger.warning("Arc verdict settlement in get_payment_invoice_status failed for %s: %s", invoice_id, exc)
    if changed:
        save_invoice_fn(invoice)
    return invoice_payment_state_response(
        invoice_id,
        invoice,
        include_access_token=True,
        fetch_gateway_balance_fn=main_mod.fetch_gateway_balance,
    )


def verify_split_payment(invoice_id: str, invoice: dict, proof: PaymentVerifyRequest) -> dict:
    main_mod = _get_backend_main()
    invoices_db, load_invoices_fn, save_invoice_fn = _sync_state(main_mod, invoice_id)
    if invoice.get("status") == "refunded" or (invoice.get("genlayer") or {}).get("verdict") == "INVALID":
        return invoice_payment_state_response(
            invoice_id,
            invoice,
            include_access_token=False,
            include_seller_balance=False,
            fetch_gateway_balance_fn=main_mod.fetch_gateway_balance,
        )
    refresh_split_invoice_status(invoice)
    if invoice.get("status") == "paid" and (invoice.get("genlayer") or {}).get("verdict") == "VALID":
        if main_mod.refresh_split_leg_batch_txs(invoice):
            sync_split_payment_events(invoice, save_event_fn=main_mod._save_single_payment_event)
        save_invoice_fn(invoice)
        return invoice_payment_state_response(
            invoice_id, invoice, include_access_token=True, fetch_gateway_balance_fn=main_mod.fetch_gateway_balance
        )
    if invoice.get("status") == "expired":
        raise HTTPException(status_code=400, detail="Invoice expired. Create a new purchase.")
    required_legs = invoice_required_split_legs(invoice)
    if not required_legs:
        raise HTTPException(status_code=400, detail="Invoice has no split legs.")
    provided = {item.leg_id: item for item in proof.split_settlements or []}
    if len(provided) != len(proof.split_settlements or []):
        raise HTTPException(status_code=400, detail="Duplicate split settlement leg submitted.")
    missing = [
        leg.get("leg_id") for leg in required_legs if leg.get("leg_id") not in provided and not leg.get("settlement_id")
    ]
    if missing:
        invoice["status"] = "partial_paid" if any(leg.get("settlement_id") for leg in required_legs) else "pending"
        save_invoice_fn(invoice)
        raise HTTPException(status_code=402, detail=f"Missing split settlement leg(s): {', '.join(missing)}")
    payer = normalize_address(proof.payer_address)
    verified_legs = []
    with state.cross_process_lock("split_leg_verify_global"):
        with state.split_leg_lock:
            for leg in required_legs:
                leg_id = leg.get("leg_id")
                submitted = provided.get(leg_id)
                if not submitted:
                    continue
                if leg.get("status") == "paid" and leg.get("settlement_id"):
                    if leg.get("settlement_id") != submitted.settlement_id:
                        raise HTTPException(
                            status_code=409,
                            detail=f"Split leg {leg_id} is already settled with a different settlement_id. Refusing to overwrite.",
                        )
                    verified_legs.append(leg)
                    continue
                if raw_usdc_str(submitted.amount_raw) != raw_usdc_str(leg.get("amount_raw")):
                    raise HTTPException(status_code=400, detail=f"Split leg {leg_id} amount does not match invoice.")
                if normalize_address(submitted.pay_to) != normalize_address(leg.get("pay_to")):
                    raise HTTPException(status_code=400, detail=f"Split leg {leg_id} pay_to does not match invoice.")
                has_authoritative_gateway_claims = bool(submitted.payer_address and submitted.gateway_status)
                receipt_valid = (
                    verify_split_receipt(
                        invoice_id=invoice_id,
                        leg_id=leg_id,
                        pay_to=leg.get("pay_to"),
                        settled_amount_raw=submitted.amount_raw,
                        settlement_id=submitted.settlement_id,
                        receipt=submitted.sidecar_receipt,
                        payer_address=submitted.payer_address,
                        gateway_status=submitted.gateway_status,
                    )
                    if has_authoritative_gateway_claims
                    else verify_split_receipt(
                        invoice_id=invoice_id,
                        leg_id=leg_id,
                        pay_to=leg.get("pay_to"),
                        settled_amount_raw=submitted.amount_raw,
                        settlement_id=submitted.settlement_id,
                        receipt=submitted.sidecar_receipt,
                    )
                )
                if not receipt_valid and has_authoritative_gateway_claims:
                    has_authoritative_gateway_claims = False
                    receipt_valid = verify_split_receipt(
                        invoice_id=invoice_id,
                        leg_id=leg_id,
                        pay_to=leg.get("pay_to"),
                        settled_amount_raw=submitted.amount_raw,
                        settlement_id=submitted.settlement_id,
                        receipt=submitted.sidecar_receipt,
                    )
                if not receipt_valid:
                    raise HTTPException(status_code=400, detail=f"Invalid sidecar receipt for split leg {leg_id}.")
                backend_store = getattr(main_mod, "storage_backend", state.storage_backend)
                if main_mod.settlement_id_already_claimed(
                    submitted.settlement_id,
                    exclude_invoice_id=invoice_id,
                    load_invoices_fn=load_invoices_fn,
                    invoices_db=invoices_db,
                    storage_backend=backend_store,
                ):
                    raise HTTPException(
                        status_code=400, detail="Settlement ID already claimed by another invoice/leg."
                    )
                if has_authoritative_gateway_claims:
                    settlement = {
                        "status": submitted.gateway_status,
                        "toAddress": leg.get("pay_to"),
                        "fromAddress": submitted.payer_address,
                        "amount": submitted.amount_raw,
                    }
                else:
                    settlement = main_mod.fetch_circle_settlement(submitted.settlement_id)
                    if leg.get("payer_address") and normalize_address(
                        settlement.get("fromAddress")
                    ) != normalize_address(leg.get("payer_address")):
                        settlement["fromAddress"] = leg.get("payer_address")
                main_mod.validate_arc_split_leg_payment(invoice, leg, settlement, payer_address=proof.payer_address)
                if settlement.get("rail") == "arc_onchain":
                    buyer = invoice.get("buyer_wallet_address")
                    if not buyer:
                        raise HTTPException(
                            status_code=400,
                            detail="On-chain settlement verification requires an invoice bound to a buyer wallet address.",
                        )
                    if normalize_address(settlement.get("fromAddress")) != normalize_address(buyer):
                        raise HTTPException(
                            status_code=403, detail="Settlement sender does not match the invoice buyer wallet."
                        )
                settlement_payer = normalize_address(settlement.get("fromAddress"))
                if payer and settlement_payer != payer:
                    raise HTTPException(status_code=400, detail="Split settlement payer mismatch.")
                payer = payer or settlement_payer
                batch = (
                    {"batch_tx": None, "explorer_url": None}
                    if has_authoritative_gateway_claims
                    else main_mod.find_arc_batch_tx(settlement)
                )
                if invoice.get("status") == "refunded":
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "invoice_refunded", "message": "Invoice is refunded and cannot be paid."},
                    )
                leg_update = {
                    "status": "paid",
                    "settlement_id": submitted.settlement_id,
                    "payer_address": settlement_payer,
                    "gateway_status": settlement.get("status"),
                    "paid_at": time.time(),
                    "sidecar_receipt": submitted.sidecar_receipt,
                }
                if batch.get("match_type") == "heuristic_window":
                    leg_update["heuristic_batch_tx"] = batch.get("batch_tx")
                    leg_update["batch_tx_match_type"] = batch.get("match_type")
                    invoice["heuristic_batch_tx"] = batch.get("batch_tx")
                    invoice["batch_tx_match_type"] = batch.get("match_type")
                else:
                    leg_update["transaction_hash"] = batch.get("batch_tx")
                    leg_update["explorer_url"] = batch.get("explorer_url")
                leg.update(leg_update)
                verified_legs.append(leg)
            if not all(leg.get("status") == "paid" and leg.get("settlement_id") for leg in required_legs):
                invoice["status"] = "partial_paid"
                main_mod._save_invoice(invoice)
                raise HTTPException(
                    status_code=402, detail="Invoice is partially paid. Complete all split legs before unlock."
                )
            invoice["status"] = "settlement_verified"
            invoice["payer_address"] = payer
            invoice["settlement_id"] = f"split:{invoice_id}"
            invoice["split_settlement_ids"] = [leg.get("settlement_id") for leg in required_legs]
            invoice["gateway_status"] = aggregate_split_gateway_status(invoice)
            invoice["amount_raw"] = (invoice.get("split") or {}).get("total_amount_raw")
            try:
                gl_receipt = main_mod.verify_invoice_report_with_genlayer(invoice_id, invoice)
                if gl_receipt["verdict"] == "INVALID":
                    return invoice_payment_state_response(
                        invoice_id,
                        invoice,
                        include_access_token=False,
                        include_seller_balance=False,
                        fetch_gateway_balance_fn=main_mod.fetch_gateway_balance,
                    )
            except HTTPException as exc:
                if exc.status_code == 503:
                    return invoice_payment_state_response(
                        invoice_id,
                        invoice,
                        include_access_token=False,
                        include_seller_balance=False,
                        fetch_gateway_balance_fn=main_mod.fetch_gateway_balance,
                    )
                raise
            main_mod.reload_persistent_state(include_reports=False)
            sync_split_payment_events(invoice, save_event_fn=main_mod._save_single_payment_event)
            save_invoice_fn(invoice)
    return invoice_payment_state_response(
        invoice_id, invoice, include_access_token=True, fetch_gateway_balance_fn=main_mod.fetch_gateway_balance
    )


def verify_payment(invoice_id: str, proof: Optional[PaymentVerifyRequest] = None) -> dict:
    main_mod = _get_backend_main()
    invoices_db, load_invoices_fn, save_invoice_fn = _sync_state(main_mod, invoice_id)
    if proof is None:
        raise HTTPException(status_code=400, detail="payment proof is required.")
    invoice = get_invoice_or_402(
        invoices_db,
        invoice_id,
        load_invoices_fn=load_invoices_fn,
        allow_expired=bool(proof and proof.settlement_id),
    )
    hydrate_payment_schema(invoice)
    if not hmac.compare_digest(str(proof.invoice_secret), str(invoice.get("invoice_secret"))):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invoice secret mismatch.")
    if invoice.get("status") == "refunded" or (invoice.get("genlayer") or {}).get("verdict") == "INVALID":
        if invoice.get("status") != "refunded":
            main_mod.refresh_invoice_batch_tx(invoice)
            main_mod.settle_genlayer_verdict_on_arc(invoice_id, invoice)
        return invoice_payment_state_response(
            invoice_id,
            invoice,
            include_access_token=False,
            include_seller_balance=False,
            fetch_gateway_balance_fn=main_mod.fetch_gateway_balance,
        )
    if invoice.get("status") == "paid" and (invoice.get("genlayer") or {}).get("verdict") == "VALID":
        if main_mod.invoice_split_mode(invoice) == "x402_direct_split":
            if main_mod.refresh_split_leg_batch_txs(invoice):
                sync_split_payment_events(invoice, save_event_fn=main_mod._save_single_payment_event)
                main_mod._save_invoice(invoice)
        else:
            before = (invoice.get("gateway_status"), invoice.get("transaction_hash"), invoice.get("explorer_url"))
            main_mod.refresh_invoice_batch_tx(invoice)
            after = (invoice.get("gateway_status"), invoice.get("transaction_hash"), invoice.get("explorer_url"))
            if before != after:
                main_mod._save_invoice(invoice)
            main_mod.settle_genlayer_verdict_on_arc(invoice_id, invoice)
        return invoice_payment_state_response(
            invoice_id,
            invoice,
            include_access_token=True,
            include_seller_balance=False,
            fetch_gateway_balance_fn=main_mod.fetch_gateway_balance,
        )
    if invoice.get("status") == "verification_pending" and invoice.get("settlement_id"):
        try:
            receipt = main_mod.verify_invoice_report_with_genlayer(invoice_id, invoice)
            return invoice_payment_state_response(
                invoice_id,
                invoice,
                include_access_token=receipt.get("verdict") == "VALID",
                include_seller_balance=False,
                fetch_gateway_balance_fn=main_mod.fetch_gateway_balance,
            )
        except HTTPException as exc:
            if exc.status_code in (409, 503):
                return invoice_payment_state_response(
                    invoice_id,
                    invoice,
                    include_access_token=False,
                    include_seller_balance=False,
                    fetch_gateway_balance_fn=main_mod.fetch_gateway_balance,
                )
            raise
    if main_mod.invoice_split_mode(invoice) == "x402_direct_split" or proof.split_settlements:
        return main_mod.verify_split_payment(invoice_id, invoice, proof)
    if not proof.settlement_id:
        raise HTTPException(status_code=400, detail="settlement_id is required.")
    with state.cross_process_lock("settlement_claim:" + str(proof.settlement_id)):
        backend_store = getattr(main_mod, "storage_backend", state.storage_backend)
        if main_mod.settlement_id_already_claimed(
            proof.settlement_id,
            exclude_invoice_id=invoice_id,
            load_invoices_fn=load_invoices_fn,
            invoices_db=invoices_db,
            storage_backend=backend_store,
        ):
            raise HTTPException(status_code=409, detail="settlement_id already claimed by another invoice.")
        if backend_store and hasattr(backend_store, "claim_settlement_for_invoice"):
            st_invoices_db = getattr(getattr(main_mod, "state", state), "invoices_db", invoices_db)
            claimed = backend_store.claim_settlement_for_invoice(
                proof.settlement_id, invoice_id, invoices_db=st_invoices_db
            )
            if not claimed:
                raise HTTPException(status_code=409, detail="settlement_id already claimed by another invoice.")
        with state.cross_process_lock("split_leg:" + invoice_id):
            invoice = get_invoice_or_402(
                invoices_db,
                invoice_id,
                load_invoices_fn=load_invoices_fn,
                allow_expired=bool(proof and proof.settlement_id),
            )
            hydrate_payment_schema(invoice)
            if invoice.get("status") == "paid":
                return invoice_payment_state_response(
                    invoice_id,
                    invoice,
                    include_access_token=True,
                    include_seller_balance=False,
                    fetch_gateway_balance_fn=main_mod.fetch_gateway_balance,
                )
            if not proof.settlement_id:
                if invoice.get("status") == "expired":
                    raise HTTPException(status_code=400, detail="Invoice expired. Create a new purchase.")
                if (
                    invoice.get("expires_at")
                    and time.time() > float(invoice["expires_at"])
                    and invoice.get("status") in {"pending", "partial_paid"}
                ):
                    invoice["status"] = "expired"
                    main_mod._save_invoice(invoice)
                    raise HTTPException(status_code=400, detail="Invoice expired. Create a new purchase.")
            settlement = main_mod.fetch_circle_settlement(proof.settlement_id)
            main_mod.validate_arc_payment(invoice, settlement, payer_address=proof.payer_address)
            if settlement.get("rail") == "arc_onchain":
                buyer = invoice.get("buyer_wallet_address")
                if not buyer:
                    raise HTTPException(
                        status_code=400,
                        detail="On-chain settlement verification requires an invoice bound to a buyer wallet address.",
                    )
                if normalize_address(settlement.get("fromAddress")) != normalize_address(buyer):
                    raise HTTPException(
                        status_code=403, detail="Settlement sender does not match the invoice buyer wallet."
                    )
            if invoice.get("settlement_id") and invoice["settlement_id"] != proof.settlement_id:
                raise HTTPException(status_code=409, detail="Invoice is already bound to another settlement.")
            invoice["status"] = "verification_pending"
            invoice["settlement_id"] = proof.settlement_id
            invoice["payer_address"] = settlement.get("fromAddress")
            invoice["gateway_status"] = settlement.get("status")
            invoice["amount_raw"] = settlement.get("amount")
            invoice["verification_mode"] = "circle-gateway-arc-testnet" if IS_TESTNET else "circle-gateway-arc-mainnet"
            main_mod._save_invoice(invoice)
            batch = main_mod.find_arc_batch_tx(settlement)
            if batch.get("match_type") == "heuristic_window":
                invoice["heuristic_batch_tx"] = batch.get("batch_tx")
                invoice["batch_tx_match_type"] = batch.get("match_type")
            else:
                invoice["transaction_hash"] = batch.get("batch_tx")
                invoice["explorer_url"] = batch.get("explorer_url")
        try:
            gl_receipt = main_mod.verify_invoice_report_with_genlayer(invoice_id, invoice)
            if gl_receipt["verdict"] == "INVALID":
                return invoice_payment_state_response(
                    invoice_id,
                    invoice,
                    include_access_token=False,
                    include_seller_balance=False,
                    fetch_gateway_balance_fn=main_mod.fetch_gateway_balance,
                )
        except HTTPException as exc:
            if exc.status_code in (409, 503):
                return invoice_payment_state_response(
                    invoice_id,
                    invoice,
                    include_access_token=False,
                    include_seller_balance=False,
                    fetch_gateway_balance_fn=main_mod.fetch_gateway_balance,
                )
            raise
    main_mod.reload_persistent_state(include_reports=False)
    if not any(event.get("settlement_id") == proof.settlement_id for event in state.payment_events):
        new_event = {
            "invoice_id": invoice_id,
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
            "settlement_id": invoice.get("settlement_id"),
            "gateway_status": invoice.get("gateway_status"),
            "transaction_hash": invoice.get("transaction_hash"),
            "explorer_url": invoice.get("explorer_url"),
            "paid_at": invoice.get("paid_at"),
            "arc_settlement": main_mod.public_arc_settlement(invoice.get("arc_settlement")),
        }
        state.payment_events.append(new_event)
        main_mod._save_single_payment_event(new_event)
        main_mod._save_invoice(invoice)
    main_mod.settle_genlayer_verdict_on_arc(invoice_id, invoice)
    return invoice_payment_state_response(
        invoice_id,
        invoice,
        include_access_token=True,
        include_seller_balance=False,
        fetch_gateway_balance_fn=main_mod.fetch_gateway_balance,
    )


def submit_withdraw(payload: dict) -> dict:
    main_mod = _get_backend_main()
    if is_treasury_halted():
        raise HTTPException(
            status_code=503,
            detail="Treasury is halted (treasury_halted=true) — creator withdrawals refused",
        )

    burn_intent = payload.get("burnIntent")
    signature = payload.get("signature")
    if not burn_intent or not signature:
        raise HTTPException(status_code=400, detail="burnIntent and signature are required")
    try:
        requested_depositor = bytes32_to_address((burn_intent.get("spec") or {}).get("sourceDepositor"))
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        raise HTTPException(status_code=400, detail=f"Withdraw intent depositor is invalid: {exc}")
    withdraw_owner = main_mod.authorized_gateway_withdraw_depositor(requested_depositor)
    expected_depositor = withdraw_owner["address"]
    intent = validate_withdraw_intent(burn_intent, expected_depositor=expected_depositor)
    if WITHDRAW_MODE in ("platform_relayed", "relayed", "gasless"):
        enforce_withdraw_relay_policy(intent)
        try:
            relay_resp = requests.post(
                f"{ARC_GATEWAY_BASE_URL.rstrip('/')}/api/withdraw/relay",
                json={"burnIntent": burn_intent, "signature": signature, "expectedDepositor": expected_depositor},
                timeout=120,
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"Withdraw relayer unavailable: {exc}")
        if not relay_resp.ok:
            try:
                relay_error = relay_resp.json()
            except Exception:
                relay_error = {"error": relay_resp.text[:300]}
            raise HTTPException(
                status_code=relay_resp.status_code,
                detail=relay_error.get("error")
                or relay_error.get("detail")
                or f"Relayer returned {relay_resp.status_code}",
            )
        data = relay_resp.json()
        record_withdraw_relay(intent)
        return {
            **data,
            "withdraw_mode": "platform_relayed",
            "relayed": True,
            "amount_usdc": data.get("amount_usdc", f"{intent['amount_usdc']:.6f}"),
            "withdraw_owner": withdraw_owner,
        }
    try:
        resp = requests.post(
            f"{ARC_GATEWAY_API}/v1/transfer",
            json=[{"burnIntent": burn_intent, "signature": signature}],
            timeout=15,
        )
        if resp.ok:
            data = resp.json()
            if (
                data.get("success") is False
                or data.get("error")
                or not data.get("attestation")
                or not data.get("signature")
            ):
                raise HTTPException(
                    status_code=502,
                    detail=f"Circle Gateway did not return a mint attestation: {json.dumps(data)[:300]}",
                )
            return {
                **data,
                "withdraw_mode": "seller_wallet",
                "relayed": False,
                "amount_usdc": f"{intent['amount_usdc']:.6f}",
                "withdraw_owner": withdraw_owner,
            }
        raise HTTPException(
            status_code=502,
            detail=f"Circle Gateway transfer API returned {resp.status_code}: {resp.text[:300]}",
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise exc
        logger.warning(f"Circle transfer API failed: {exc}.")
        raise HTTPException(status_code=502, detail=f"Circle Gateway transfer API failed: {exc}")


def authorize_paid_invoice(
    *, query: dict, invoice_id: str, token: str, required_tier: str, provider_id: str = "funding_memory"
) -> dict:
    main_mod = _get_backend_main()
    invoices_db, load_invoices_fn, save_invoice_fn = _sync_state(main_mod, invoice_id)
    if not invoice_id:
        amount_dec = "0.005000" if required_tier == "full" else "0.002000"
        challenge_body, challenge_headers = build_402_challenge_payload(
            url=f"/api/v1/providers/{provider_id}/{'preview' if required_tier == 'preview' else 'full-report'}",
            amount_decimal=amount_dec,
            description=f"QMA {provider_id.replace('_', ' ').title()} {required_tier.title()} Report",
        )
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "payment_required",
                "message": f"Payment required: ${amount_dec} USDC over x402 / Circle Gateway to access {provider_id} {required_tier} report.",
                "payment": payment_requirement(
                    symbol=query.get("symbol", "BTC_USDT"),
                    amount_usdc=0.005 if required_tier == "full" else 0.002,
                    tier=required_tier,
                    provider_id=provider_id,
                ),
            },
            headers=challenge_headers,
        )
    invoice = get_invoice_or_402(invoices_db, invoice_id, load_invoices_fn=load_invoices_fn)

    if invoice.get("provider_id", "funding_memory") != provider_id:
        raise HTTPException(status_code=400, detail="Invoice provider does not match requested provider.")
    if invoice_has_failed_settlement(invoice):
        if invoice.get("status") != "disputed":
            invoice["status"] = "disputed"
            save_invoice_fn(invoice)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "settlement_disputed",
                "message": "Circle reported a terminal settlement failure for this invoice after access was granted. No further access will be issued; contact support if you believe this is an error.",
            },
        )
    genlayer_verdict = (invoice.get("genlayer") or {}).get("verdict")
    if invoice.get("status") == "verification_rejected" or genlayer_verdict == "INVALID":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "genlayer_verification_rejected",
                "message": "GenLayer rejected this report; access remains locked.",
            },
        )
    if invoice["status"] != "paid":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "payment_not_settled",
                "message": f"Invoice is {invoice['status']}. Complete the USDC payment before analysis.",
                "payment": payment_requirement(
                    invoice_id=invoice_id,
                    symbol=invoice["symbol"],
                    amount_usdc=invoice.get("amount"),
                    tier=invoice.get("tier", required_tier),
                    resource_type=invoice.get("resource_type", PAYMENT_RESOURCE_TYPE),
                    provider_id=invoice.get("provider_id", provider_id),
                ),
            },
        )
    if invoice.get("verification_required") and genlayer_verdict != "VALID":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "genlayer_verification_pending",
                "message": "Payment is settled, but a finalized VALID GenLayer verdict is required before report access.",
            },
        )
    if invoice["symbol"].upper() != str(query.get("symbol", "")).upper():
        raise HTTPException(status_code=400, detail="Invoice symbol does not match query symbol.")
    current_query_hash = query_fingerprint(query)
    stored_query_hash = invoice.get("query_hash")
    if stored_query_hash != current_query_hash:
        non_query_fields = {
            "provider_id",
            "tier",
            "buyer_type",
            "buyer_wallet_address",
            "synthetic",
            "agent_label",
            "run_source",
            "resource_type",
            "candidate_id",
            "expected_price_usdc",
        }
        inv_q_clean = {k: v for k, v in (invoice.get("query") or {}).items() if k not in non_query_fields}
        client_q_clean = {k: v for k, v in query.items() if k not in non_query_fields}
        clean_inv_hash = query_fingerprint(inv_q_clean) if inv_q_clean else None
        clean_client_hash = query_fingerprint(client_q_clean)
        if not (clean_inv_hash and clean_client_hash == clean_inv_hash) and clean_client_hash != stored_query_hash:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Paid invoice is bound to a different query snapshot. Create a fresh invoice for changed signal data.",
            )
    token_payload = verify_access_token(token or "")
    try:
        paid_kit.require_access(token_payload, invoice, required_tier=required_tier)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return invoice

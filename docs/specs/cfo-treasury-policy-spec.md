# QMA Corporate Treasury Policy & Autonomous CFO Specification

- **Module**: `backend/app/services/usyc_treasury.py`
- **Schemas**: `backend/app/schemas/treasury.py` (`CorporateTreasuryPolicy`, `CFODecisionResult`, `CFODecisionRequest`)
- **Endpoints**: `POST /api/v1/treasury/agent/decide`, `GET /api/v1/treasury/policy`, `PUT /api/v1/treasury/policy`
- **Flow Alignment**: [FL-03 (Autonomous CFO Decision)](../FLOWS.md)
- **Status**: Implemented & Machine-Verified

---

## 1. Scope & System Objective

The QMA Autonomous AI CFO continuously monitors platform and operational wallet liquidity on the **Arc blockchain** (Chain ID `5042` / `504201`), balancing liquid cash requirements against yield generation across tokenized treasury vaults (**Institutional USYC ERC-4626** and **Arc Morpho Lending Vault**).

The engine operates on a deterministic, non-bypassable policy framework that evaluates liquidity obligations before proposing or executing any treasury movement.

---

## 2. Policy Configuration Schema (`CorporateTreasuryPolicy`)

All autonomous treasury decisions adhere strictly to parameters declared in `CorporateTreasuryPolicy`:

| Field Name | Type | Default | Constraint | Description |
| :--- | :--- | :--- | :--- | :--- |
| `min_operating_reserve_usdc` | `float` | `10.0` | $\ge 0.0$ | Minimum liquid USDC reserve to preserve on Arc. Can never be swept. |
| `target_safety_buffer_ratio` | `float` | `1.5` | $\ge 1.0$ | Target ratio of total liquid assets to upcoming obligations ($\ge 150\%$). |
| `min_sweep_threshold_usdc` | `float` | `2.0` | $\ge 0.0$ | Minimum surplus cash required before executing an on-chain sweep. |
| `max_sweep_per_epoch_usdc` | `float` | `50.0` | $> 0.0$ | Hard ceiling on USDC swept into yield vaults during a single decision epoch. |
| `max_jit_redeem_per_epoch_usdc` | `float` | `50.0` | $> 0.0$ | Hard ceiling on USDC redeemed from vaults during a single decision epoch. |
| `rebalance_cooldown_seconds` | `int` | `300` | $\ge 0$ | Minimum delay (seconds) between consecutive on-chain rebalancing actions. |
| `autonomous_execution_enabled` | `bool` | `false` | Boolean | Whether the AI CFO is authorized to broadcast transactions autonomously without manual confirmation. |
| `target_apy_baseline` | `float` | `0.05` | $0.0 \dots 1.0$ | Baseline target annualized yield (5.0% APY). |
| `yield_rail` | `str` | `"EARN_KIT_MORPHO"` | Enum | Target yield rail: `"EARN_KIT_MORPHO"` (Morpho Arc USDC Core) or `"USYC"` (Institutional USYC Treasury). |
| `target_earn_vault` | `str` | `"morpho_arc_usdc_core"` | String | Default vault identifier on Arc. |
| `treasury_halted` | `bool` | `false` | Boolean | Operator emergency circuit breaker. When `true`, all sweeps and JIT redemptions are blocked immediately. |

---

## 3. Four-Stage Decision Ladder (`evaluate_cfo_decision`)

Every evaluation tick in `usyc_treasury.py:1027` follows an immutable 4-stage deductive ladder:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        AUTONOMOUS CFO DECISION LADDER                  │
├────────────────────────────────────────────────────────────────────────┤
│ 1. SOLVENCY EVALUATION                                                 │
│    total_assets = liquid_usdc + vault_assets                           │
│    if total_assets < required_reserve * 0.5:                           │
│        ==> INSOLVENCY_ALERT (Halt Spends, Alert Operator)              │
│                                                                        │
│ 2. DEFICIT EVALUATION (Operational Liquidity Depletion)                │
│    if liquid_usdc < required_reserve:                                  │
│        deficit = min(required_reserve - liquid, max_jit_redeem)        │
│        ==> JIT_REDEEM (Unwind vault shares -> liquid USDC)             │
│                                                                        │
│ 3. SURPLUS EVALUATION (Excess Cash Drag)                               │
│    surplus = liquid_usdc - required_reserve                            │
│    if surplus >= min_sweep_threshold:                                  │
│        sweep_amount = min(surplus, max_sweep_per_epoch)                │
│        ==> SWEEP_IDLE (Deposit idle USDC -> Yield Vault)               │
│                                                                        │
│ 4. EQUILIBRIUM                                                         │
│    if liquid_usdc within target bounds:                                │
│        ==> HOLD_AND_EARN (Maintain position, accumulate APY)          │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Execution Invariants & Audit Sealing

1. **Simulation vs Production**:
   - Calling `evaluate_cfo_decision` with `execute_if_authorized=False` produces a read-only proposal (`execution_status: "PROPOSAL_ONLY"`).
   - Only admin-authorized executions (`execute_if_authorized=True` AND `autonomous_execution_enabled=True`) dispatch real on-chain transactions on Arc.
2. **Athenian Euthyna Audit Anchoring**:
   - Every on-chain execution logs an immutable action (`USYC_SWEEP`, `USYC_JIT_REDEEM`, or `HOLD_AND_EARN`) to `euthyna_audit_engine`, returning a cryptographically verifiable `audit_record_id` bound to the transaction hash.
3. **Emergency Halt Interlock**:
   - If `treasury_halted=True`, both `SWEEP_IDLE` and `JIT_REDEEM` are refused at the code level, regardless of AI model proposals.

---

## 5. Verification Commands

```powershell
# Run USYC Treasury and CFO Decision unit tests
uv run pytest tests/unit/test_usyc_treasury.py tests/unit/test_cfo_decision_sources.py tests/unit/test_earn_kit.py -v
```

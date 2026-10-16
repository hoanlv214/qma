# QMA System Specifications Directory (`docs/specs/`)

This directory is the **sole canonical source of truth** for all formal system contracts, financial settlement specifications, and agent execution policies across the QMA platform.

All specifications here are **prerequisites for implementation** and strictly grounded in the verified source code.

---

## Specification Master Register

| Specification | Primary Source Code | Category | Core Invariants & Scope |
| :--- | :--- | :--- | :--- |
| [**`AGENT_API.md`**](AGENT_API.md) | `backend/app/api/v1/endpoints/agent.py` | API Contract | Decision endpoint `POST /api/v1/agent/decision`, 4-tier cascade, budget ceilings, policy check response models. |
| [**`agent-consumption-contract-v1.md`**](agent-consumption-contract-v1.md) | `backend/app/services/agent_decision.py` | Agent Contract | Query validation, token parameter schema, access token verification for autonomous buyers. |
| [**`agent-risk-and-incident-management.md`**](agent-risk-and-incident-management.md) | `backend/app/services/incident_engine.py` | Safety & Risk | 3-Tier state machine (`payment`, `session`, `micro-tick`), P1/P2/P3 incident triage, Euthyna hash linking, emergency kill-switch. |
| [**`cfo-treasury-policy-spec.md`**](cfo-treasury-policy-spec.md) | `backend/app/services/usyc_treasury.py` | Treasury Policy | 4-stage solvency ladder (`INSOLVENCY_ALERT`, `JIT_REDEEM`, `SWEEP_IDLE`, `HOLD_AND_EARN`), USYC ERC-4626 vault bounds, Morpho earn rail. |
| [**`circle-marketplace-bilateral-a2a.md`**](circle-marketplace-bilateral-a2a.md) | `agents/src/`, `backend/app/services/` | Integration | Circle agent wallet discovery, bilateral Agent-to-Agent (A2A) x402 payment protocol, and dynamic creator fees. |
| [**`deterministic-guardrails-and-invoice-clarity.md`**](deterministic-guardrails-and-invoice-clarity.md) | `backend/app/services/spend_guard.py` | Safety Guard | "Blocked by code, not by the model" invariant, deterministic spend limits, VIP stacked invoice preview card. |
| [**`intelligence-contract-v1.md`**](intelligence-contract-v1.md) | `backend/app/services/plugins/` | Payload Contract | Exact payload format for quantitative reports: analog matches, weighted win rates, SLA confidence score. |
| [**`payment-settlement-spec.md`**](payment-settlement-spec.md) | `backend/app/services/payment_state_machine.py` | Settlement | Circle Gateway Nanopayments on Arc, single-payment settlement (D-06), GenLayer SLA verification gate, terminal states (`settled`, `refunded`). |
| [**`provider-onboarding-spec.md`**](provider-onboarding-spec.md) | `backend/app/core/provider_registry.py` | Onboarding | Third-party quantitative model manifest schema, pricing tiers, sandbox verification. |
| [**`provider-review-process.md`**](provider-review-process.md) | `backend/app/services/providers_meta.py` | Reputation | SLA quality verification, GenLayer consensus adjudication, and Proof-of-Spend reputation scoring. |

---

## Architectural & Flow Cross-References

- **Execution Flows (FL-01 to FL-08)**: [`docs/FLOWS.md`](../FLOWS.md)
- **Definitive System Architecture**: [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md)
- **Architecture Decision Log (D-01 to D-06)**: [`docs/architecture/DECISIONS.md`](../architecture/DECISIONS.md)
- **OpenAPI Endpoint Inventory**: [`docs/api/README.md`](../api/README.md)
- **Payment State Machine Details**: [`docs/agent/PAYMENT_FLOW.md`](../agent/PAYMENT_FLOW.md)

---

## Verification Suite

```powershell
# Verify OpenAPI documentation gate
uv run pytest tests/api_v1/test_api_openapi_docs.py -q

# Verify unit test invariants
uv run pytest tests/unit/ -q
```

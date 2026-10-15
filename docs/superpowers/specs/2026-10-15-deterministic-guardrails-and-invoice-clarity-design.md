# Deterministic Guardrails & Invoice Clarity Design

Date: 2026-10-15.
Branch: `main`.
Status: Implemented.

## 1. Context & Problem Statement

Autonomous agents possessing transaction and wallet authority face a fundamental safety requirement:
**Financial spending limits and execution safety cannot rely on LLM prompts alone.**

In previous iterations:
- An LLM planner was instructed to evaluate whether candidate prices were within budget.
- When an execution hit a spending cap in `spend_guard.py`, the system silently mutated the decision action to `"skip"` with a generic reason (`"Spend Guard: ..."`).
- To external observers, auditors, and prospective users, this created an ambiguous impression: *Did the model choose to skip, or did deterministic safety code intervene? What prevents a hallucinating or prompt-injected model from spending customer funds?*
- On the Landing Page, the hero visualization was rendered as a lengthy perforated paper slip with low information density, verbose technical markers (`OBSERVE`, `REASON`, `ENFORCE`, `SIGN`), and internal rule codes that obscured the business value of market intelligence reports.

## 2. Core Architectural Invariant: "Blocked by Code, Not by the Model"

QMA enforces a strict **two-layer decision boundary**:

1. **Advisory Intelligence Layer (LLM / Router):**
   - The LLM or Laya neural router analyzes funding and open-interest dislocations.
   - It formulates an autonomous proposal (`action: "purchase"`, candidate selection, requested tier, and domain rationale).
   - The model is **untrusted** with wallet custody or spending authority.

2. **Deterministic Code Guardrail Layer (`SpendLimitGuard` / Python Service):**
   - Runs purely deterministic Decimal arithmetic before any wallet signature, x402 invoice generation, or Arc contract interaction.
   - Evaluates:
     - `max_single_tx`: Per-transaction ceiling (e.g. 0.05 USDC).
     - `max_daily_spend`: 24-hour cumulative spending cap (e.g. 1.00 USDC).
     - `circuit_breaker`: Halts after consecutive transaction failures.
   - When a rule is breached, the system records:
     - `model_proposal`: The model's intended action (`"purchase"`).
     - `guardrail_blocked`: `true`.
     - `guardrail_rule`: `"spend_guard.spend_limit"`.
     - `guardrail_message`: **"Blocked by code, not by the model. It is above the payer's payment limit."**
     - Quantitative audit figures: `attempted_usdc` vs `allowed_usdc`.

This guarantees mathematical proof that funds cannot move without passing non-bypassable code checks.

## 3. Landing Page Hero Redesign: Stacked Invoice Preview

Inspired by high-conviction financial consoles, the landing hero visual (`AgentLoopReplay.tsx`) transitions from a verbose faux receipt to a **VIP Stacked Invoice Card Preview**:

### Top Primary Card:
- **Header:** Eyebrow `MARKET INTELLIGENCE INVOICE` + Status Badge (`Live Arc Settlement` or `Guardrail Intercepted`).
- **Payee & Anomaly Metadata:**
  - *Paid Scenario:* `Funding Dislocation Alpha · Report #0412` (0.0050 USDC).
  - *Blocked Scenario:* `Whale Order Flow Alpha · Report #0931` (0.0500 USDC attempted).
- **Decision Status Badges:**
  - *Paid:* `[Agent: purchase]` + `[Settled on Arc]`.
  - *Blocked:* `[Model: proposed purchase]` + `[Held by Guardrail]`.
- **Reasoning:** Concise, natural language explaining the statistical regime match.
- **Verification Details:**
  - *Paid:* 4 clean checkmarks (Spending cap, GenLayer SLA, Circle Gateway x402, Euthyna SHA-256 link).
  - *Blocked:* **Prominent Red Callout Band with ShieldX icon:**
    - Title: **"Blocked by code, not by the model."**
    - Body: *"The agent decided to purchase. The deterministic spend guard refused it before anything was signed or sent."*
    - Spec Table: Rule, Attempted Amount (0.0500 USDC), Allowed Limit (0.0100 USDC), and Rationale.
- **Operator Verdict:** Interactive prompt *"Do you agree with the agent?"* with `[Approve & Execute]` and `[Review Query]`.

### Stacked Secondary Card:
- Tucked directly beneath the primary card (`-mt-2 rounded-b-2xl border border-t-0`).
- Displays the alternate scenario peeking through, allowing instant one-click switching.
- Visitors immediately perceive both realities: seamless automated execution when compliant, and ironclad code intervention when limits are exceeded.

### Live Production Ledger Head:
- Bottom connector reads live SHA-256 hashes from `/api/v1/treasury/audit/euthyna` and production metrics from `/api/v1/metrics`.

## 4. Verification & Testing

- Unit tests in `tests/api_v1/test_api_agent.py` verify decision schema and plan preservation.
- OpenAPI docs gate test `tests/api_v1/test_api_openapi_docs.py` remains 100% passing.
- Frontend build validates zero TypeScript errors.

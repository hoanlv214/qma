# QMA Agent Package

This directory contains the typed policy and bounded-session package. It is a
library boundary, not the FastAPI payment service and not the React UI.

For the complete end-to-end flow, read
[docs/AUTONOMOUS_AGENT.md](../docs/AUTONOMOUS_AGENT.md). For runnable commands,
read [examples/README.md](../examples/README.md).

## Ownership

```text
agents/src/contracts/  decision and candidate shapes
agents/src/planner/    optional local LLM response shaping
agents/src/policy/     decision validation against hard policy
agents/src/qma/        typed backend API reads
agents/src/session/    bounded loop, state, accounting, stop conditions
agents/src/wallets/    signer interfaces and adapters
agents/src/executor/   sequential signed/Circle split-payment executor
```

The authoritative decision boundary remains the backend:
`POST /api/v1/agent/decision`. The package must not duplicate provider price
resolution, invoice construction, settlement verification, or entitlement
issuance.

## Session responsibilities

The session package normalizes and enforces:

- hard session budget and per-report maximum;
- provider and tier allowlists;
- minimum score and ownership checks;
- Preview-to-Full upgrade policy;
- symbol cooldowns;
- failed-candidate backoff and bounded retry attempts;
- entitlement-key deduplication (`provider:symbol:tier`) even when a provider
  returns a new candidate ID;
- duration and maximum-purchase stop conditions;
- spend, failure, wait, skip, decision, and purchase accounting.

The session delegates live payment to the executable buyer under
`examples/agent_buyer.mjs`. The buyer uses the shared executor for both signed
x402 payments and Circle Agent Wallet payments. The executor settles legs
sequentially, normalizes settlement proofs, and refuses to retry an uncertain
outcome; the backend remains responsible for invoice verification and report
access.

## Input model

The current executable CLI is flag-driven for reproducible tests and
automation. The intended user-facing wizard is documented as a future UX in
[examples/README.md](../examples/README.md); do not assume `npm run agent` is
interactive until the runtime implements it.

The normalized policy must be fixed for a session. If session resume is added,
persist only non-secret policy and accounting. Never persist private keys, OTPs,
Circle CLI sessions, invoice secrets, or access tokens.

## Circle Agent Wallet boundary

The CLI can opt into Circle Agent Wallet through
`--executor circle-agent-wallet`. The wallet address is the authorization
identity; Gateway settlement may expose a separate backing payer identity.
The backend binds and verifies both identities where available.

Circle CLI credentials and OTP sessions must never be sent to Vite or stored in
browser storage. The browser UI may provide a signer adapter for a
user-approved payment, while the Circle Agent Wallet adapter stays in the
Node/CLI runtime.

## Build

From the repository root:

```powershell
npm run agent:build
```

The package does not own runtime payment verification. Verify payment behavior
with the backend tests and [PAYMENT_FLOW.md](../PAYMENT_FLOW.md).

# QMA Payment & Settlement Specification

- **Module**: `backend/app/services/payment_state_machine.py`, `settlement_validation.py`
- **Schemas**: `backend/app/schemas/invoices.py`, `backend/app/schemas/payments.py`
- **Endpoints**: `POST /api/v1/payment/invoice`, `POST /api/v1/payment/verify`, `GET /api/v1/payment/invoices/{id}`
- **Flow Alignment**: [FL-01 (Report purchase & verdict settlement)](../FLOWS.md)
- **Status**: Implemented & Machine-Verified

---

## 1. Scope & Core Payment Rail

All monetization within QMA uses **Circle USDC Nanopayments on the Arc blockchain** (Chain ID `5042` / `504201`), utilizing Arc's native USDC gas token mechanics (zero ETH/MATIC required). 

Per Architectural Decision **D-06**, every invoice settles via a **Single Payment followed by GenLayer Intelligent SLA Verification**.

---

## 2. Invoice State Machine & Terminal Transitions

The lifecycle of an invoice is governed strictly by `refresh_split_invoice_status()` in `backend/app/services/payment_state_machine.py`:

```
                 ┌────────────────────────────────────────────────────────┐
                 │                       INVOICE LIFECYCLE                │
                 └────────────────────────────────────────────────────────┘
                                            │
                                            ▼
                                       [pending]
                                            │
                           Payment Settled via Circle Gateway
                                            │
                                            ▼
                                [verification_pending]
                                            │
                          GenLayer Intelligent Contract Verdict
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
             Verdict == 'VALID'                           Verdict == 'INVALID'
                     │                                             │
                     ▼                                             ▼
                  [paid]                               [verification_rejected]
                     │                                             │
             Access Token Issued                           Refund Mint Intent
                     │                                             │
                     ▼                                             ▼
                 [settled] (TERMINAL)                         [refunded] (TERMINAL)
```

### Monotonic Terminal States:
1. **`settled`**: The payment is confirmed, the GenLayer consensus is `VALID`, and the `X-QMA-Access-Token` is permanently bound to the invoice. Once in `settled`, no caller can mutate the invoice.
2. **`refunded`**: An `INVALID` verdict triggered a Circle BurnIntent -> mint refund. Once the Circle transaction state is `COMPLETE`, the status becomes terminal `refunded`.
3. **`disputed`**: Triggered immediately if `has_fabricated_settlement()` detects legacy bypass patterns (`x402_settle_*`).

---

## 3. Financial Invariants & Security Gates

1. **Anti-Fabrication Check (`has_fabricated_settlement`)**:
   - Inspects `settlement_id`. Any record prefixed with `x402_settle_` (unverified client bypass) is immediately classified as `disputed` and locked.
2. **Fail-Closed Persistence**:
   - With PostgreSQL configured, all invoice status mutations and payment events persist to PostgreSQL atomically. A failed database write aborts execution and never leaks paid reports.
3. **GenLayer SLA Holding Gate**:
   - Only a finalized on-chain `VALID` verdict releases the decryption secret / access token. In indeterminate, timeout, or pending validator states, the invoice remains locked in `verification_pending`.
4. **Idempotency Keying**:
   - Payment events are indexed by unique UUID-v4 idempotency keys, preventing double-crediting or duplicate payouts during network retries.

---

## 4. Verification Commands

```powershell
# Run Payment State Machine and Settlement Validation unit tests
uv run pytest tests/unit/test_payment_state_machine.py tests/unit/test_settlement_validation.py -v
```

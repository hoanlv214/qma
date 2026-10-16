# Unified Documentation & Specifications Consolidation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

---

## 1. Context & Motivation

Currently, specifications and architectural documentation across the QMA repository are fragmented across multiple disparate locations:
1. **Two Separate Spec Directories**:
   - `docs/specs/`: Contains 5 interface contracts (`AGENT_API.md`, `agent-consumption-contract-v1.md`, `intelligence-contract-v1.md`, `provider-onboarding-spec.md`, `provider-review-process.md`).
   - `docs/superpowers/specs/`: Contains 16 dated design specs (`2026-09-26-*.md` to `2026-10-15-*.md`) detailing system milestones, financial models, security invariants, and state machines.
2. **Root vs `docs/` Duplications**:
   - `PAYMENT_FLOW.md` (root, 3.7 KB) vs `docs/agent/PAYMENT_FLOW.md` (7.7 KB).
   - `SECURITY_AUDIT.md` (root, 18.2 KB) vs `docs/SECURITY_AUDIT.md` (13.1 KB).
   - `AUDIT_FINAL.md` (root, 14.8 KB) vs `docs/AUDIT_FINAL.md` (4.8 KB).
   - `TRACTION.md` (root, 4.4 KB) vs `docs/business/TRACTION.md` (1.8 KB).
3. **Overlapping Architecture Specs**:
   - `docs/ARCHITECTURE.md` (31.5 KB, authoritative Phase 8 spec) vs `docs/architecture/SYSTEM_ARCHITECTURE.md` (23.4 KB, earlier Phase 1-2 snapshot).

This plan unifies all specifications into **one single canonical directory (`docs/specs/`)**, eliminates file duplication, updates all cross-references, and aligns the documentation tree under the Controlled Refactoring & Codebase Intelligence Protocol (CRCIP).

---

## 2. Target Unified Architecture ("Thống Nhất 1 Mối")

All specifications will live under a unified, cleanly partitioned `docs/specs/` hierarchy:

```
docs/specs/
├── README.md               # Master Specification Register & Cross-Reference Index
├── contracts/              # Domain Interface & Integration Contracts
│   ├── agent-api.md                    (from AGENT_API.md)
│   ├── agent-consumption-contract.md   (from agent-consumption-contract-v1.md)
│   ├── intelligence-delivery-contract.md (from intelligence-contract-v1.md)
│   ├── provider-onboarding-spec.md
│   └── provider-review-process.md
└── designs/                # Chronological Engineering Design Specifications (16 specs)
    ├── 2026-09-26-agent-risk-and-incident-management-design.md
    ├── 2026-09-27-autonomous-cfo-and-usyc-yield-vault-design.md
    ├── 2026-09-28-athenian-euthyna-cryptographic-audit-engine-design.md
    ├── 2026-09-29-circle-marketplace-bilateral-a2a-integration-design.md
    ├── 2026-09-30-mcp-server-and-oauth-pkce-integration-design.md
    ├── 2026-10-01-circle-stablefx-and-cross-currency-swap-design.md
    ├── 2026-10-02-treasury-os-design-system-and-operations-console-design.md
    ├── 2026-10-03-e5-money-critical-invariants-and-honest-consensus-design.md
    ├── 2026-10-04-distributed-session-leases-and-concurrency-locks-design.md
    ├── 2026-10-05-arc-dex-aggregator-and-execution-router-design.md
    ├── 2026-10-05-creator-royalty-claims-and-split-settlement-design.md
    ├── 2026-10-06-market-state-epochs-and-sla-gate-design.md
    ├── 2026-10-07-erc8004-verifiable-agent-reputation-design.md
    ├── 2026-10-15-centralized-static-configuration-design.md
    ├── 2026-10-15-deterministic-guardrails-and-invoice-clarity-design.md
    └── 2026-10-15-multi-environment-control-center-design.md
```

`docs/superpowers/specs/` will maintain a lean `README.md` pointing directly to `docs/specs/designs/` for compatibility with superpowers tools, preventing directory drift.

---

## 3. Bite-Sized Implementation Tasks

### Task 1: Audit & Merge Root Markdown Duplicates
- [ ] **Step 1**: Compare and merge `PAYMENT_FLOW.md` (root) into `docs/agent/PAYMENT_FLOW.md` ensuring all newer rules (e.g. terminal states, fail-closed persistence) are preserved.
- [ ] **Step 2**: Replace root `PAYMENT_FLOW.md` with a clean pointer referencing `docs/agent/PAYMENT_FLOW.md` to avoid diverging copies while keeping `AGENTS.md` rule compatibility.
- [ ] **Step 3**: Compare and merge `SECURITY_AUDIT.md` (root, 18KB) with `docs/SECURITY_AUDIT.md` (13KB) into a single authoritative `docs/SECURITY_AUDIT.md`.
- [ ] **Step 4**: Compare and merge `AUDIT_FINAL.md` (root, 14KB) with `docs/AUDIT_FINAL.md` (4KB) into `docs/AUDIT_FINAL.md`.
- [ ] **Step 5**: Compare and merge `TRACTION.md` (root, 4KB) with `docs/business/TRACTION.md` (1.8KB) into `docs/business/TRACTION.md`.
- [ ] **Step 6**: Commit merged documentation and pointer files.

### Task 2: Restructure `docs/specs/` into `contracts/` and `designs/`
- [ ] **Step 1**: Create `docs/specs/contracts/` and move the 5 domain interface specs into it:
  - `AGENT_API.md` -> `docs/specs/contracts/agent-api.md`
  - `agent-consumption-contract-v1.md` -> `docs/specs/contracts/agent-consumption-contract.md`
  - `intelligence-contract-v1.md` -> `docs/specs/contracts/intelligence-delivery-contract.md`
  - `provider-onboarding-spec.md` -> `docs/specs/contracts/provider-onboarding-spec.md`
  - `provider-review-process.md` -> `docs/specs/contracts/provider-review-process.md`
- [ ] **Step 2**: Create `docs/specs/designs/` and copy/move all 16 dated design specs from `docs/superpowers/specs/` into `docs/specs/designs/`.
- [ ] **Step 3**: Create a compatibility pointer in `docs/superpowers/specs/README.md` referencing `docs/specs/designs/` so tooling and external skills find the specs seamlessly.
- [ ] **Step 4**: Commit restructuring changes.

### Task 3: Build the Unified Master Specification Register (`docs/specs/README.md`)
- [ ] **Step 1**: Write a comprehensive `docs/specs/README.md` containing:
  - **Section A: Domain Interface Contracts** (Table of all 5 contracts, entry points, schemas, and consumers).
  - **Section B: Chronological Design Specifications** (Table of all 16 dated specs, commit hashes, target modules, and status).
  - **Section C: System Execution Flows Mapping** (Explicit matrix mapping FL-01 through FL-08 in `docs/FLOWS.md` to both contracts and design specs).
- [ ] **Step 2**: Commit `docs/specs/README.md`.

### Task 4: Reconcile Architecture Documents (`docs/ARCHITECTURE.md` vs `docs/architecture/`)
- [ ] **Step 1**: Verify that `docs/ARCHITECTURE.md` is the authoritative single source of truth for high-level architecture per CRCIP Phase 8.
- [ ] **Step 2**: In `docs/architecture/SYSTEM_ARCHITECTURE.md`, add an authoritative header banner indicating that `docs/ARCHITECTURE.md` is the primary macro-architecture document, while `docs/architecture/` files provide detailed subsystem breakdowns (`AUTONOMOUS_AGENT.md`, `ARC_PAYMENT.md`, `PRODUCTION_SECURITY_ARCHITECTURE.md`, etc.).
- [ ] **Step 3**: Commit architecture document reconciliation.

### Task 5: Update All Cross-References & Links Across the Repository
- [ ] **Step 1**: Update `docs/README.md` (documentation map) to reflect the unified `docs/specs/` structure.
- [ ] **Step 2**: Update `AGENTS.md` documentation loading section to refer to the canonical paths (`docs/agent/PAYMENT_FLOW.md`, `docs/specs/contracts/agent-api.md`).
- [ ] **Step 3**: Update `examples/README.md` and `docs/api/README.md` links pointing to `docs/specs/contracts/agent-api.md`.
- [ ] **Step 4**: Commit reference updates.

### Task 6: Final Verification & Test Gates
- [ ] **Step 1**: Run `uv run pytest tests/api_v1/test_api_openapi_docs.py -q` (Must pass 13/13).
- [ ] **Step 2**: Run `uv run pytest tests/unit/ -q` (Must pass 451/451).
- [ ] **Step 3**: Run frontend build check (`cd frontend && npm run build`).
- [ ] **Step 4**: Run a Python script checking for any dead links (`[...](...)`) pointing to moved spec files across `docs/` and root `.md` files.
- [ ] **Step 5**: Final review and git status clean check.

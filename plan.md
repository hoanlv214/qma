# QMA Comprehensive Engineering Review (v2 — Verifiable Process)

This document outlines a verifiable technical audit protocol for this repository. In this version: **every conclusion must be backed by an evidence trail**, and dedicated process logs must be recorded for each phase to allow independent verification of the audit results.

---

## Mandatory Rules (Applicable to ALL Phases)

1. **No speculation based on file or directory names.** If a file has not been directly opened and read, do NOT describe its contents, behavior, or architecture. If mentioned without reading, explicitly flag it as: `⚠️ UNREAD — insufficient evidence`.

2. **No negative assertions without corresponding searches.** Statements like "None found", "No missing endpoints", or "Fully covered" must be preceded by the explicit list of search/grep commands executed, including the number of matches.

3. **All code citations (evidence blocks) must originate from the latest view/read in this session.** Do not copy line numbers from memory or prior sessions if files may have changed. If uncertain, append `(line numbers may have shifted, verification required)`.

4. **Process by the smallest possible unit (per-file, per-endpoint); do not aggregate in large batches.** For instance, do not read 10 router files and summarize collectively — process each router file individually, log per-file, and then synthesize.

5. **Do not skip directories within a phase scope.** If a directory (e.g., `arc_gateway/`) is referenced in any finding, it MUST be directly listed and read in that phase's process log.

6. **Pause at the end of each phase.** Do not auto-advance to the next phase without presenting a concise summary (created audit files + log files) and waiting for confirmation when required.

---

## Process Log Format (Mandatory for each phase)

For each Phase N, in addition to the primary audit document `docs/audit/0N-*.md`, produce:

```
docs/audit/logs/0N-process-log.md
```

Follow this sequential structure:

```markdown
# Process Log — Phase N: <Phase Name>

## Declared Scope
- List of files/directories planned for reading

## Execution Steps (Sequential)

### Step 1: <Description, e.g., "Read full payment_state_machine.py">
- Tool used: view / grep / search
- Exact input: <file path or grep query>
- Result: <line count / match count / sample snippet>
- Notes: <anomalies or truncation if any>

### Step 2: ...

## Directly Read Files
- path/to/file1.py — lines 1–388 (full)
- path/to/file2.ts — lines 1–57 (full)

## Mentioned But Unread Files
- path/to/fileX — reason unread: <...>
  → Tagged with ⚠️ UNREAD in main audit

## Executed Searches / Greps
| Query | Matches | Purpose |
|---|---|---|
| "/api/v1" in frontend/src | 34 matches | Endpoint cross-referencing |

## Self-Flagged Speculative Risks
List areas with lowest certainty (e.g., partial reads, inferred logic).
```

---

## Phase 1 — API Surface Review

**Read (individually with per-file logging):**
- `backend/app/main.py`
- All files in `backend/app/api/v1/endpoints/`
- All files in `frontend/src/services/`
- All files in `frontend/src/hooks/` with API invocations
- Components directly invoking `fetch` or `/api/v1`

**For each router file:**
1. List all endpoints (HTTP method, path, handler function) copied verbatim.
2. Grep the route path in `frontend/src/` — record exact query and match count.
3. If matched → record referencing file and line numbers.
4. If unmatched → label "unused endpoint" only after searching both full path and handler function name.

**Output:** `docs/audit/01-api-surface.md`  
**Log:** `docs/audit/logs/01-process-log.md`

---

## Phase 2 — Payment Lifecycle Review

**Read completely without omission (high-risk focus):**
- `payment_state_machine.py`
- `x402_gateway.py`
- `settlement_validation.py`
- `payment_signing.py`
- `invoice_builder.py`
- All direct state/amount dependencies imported by the above

**For each critical function (state transition, amount calculation, settlement verification):**
- Provide verbatim code snippet as evidence.
- Evaluate edge cases not handled.
- Do not mark "Severity: Low (Well-Handled)" without attempting counter-examples or bypass tests.

**Output:** `docs/audit/02-payment-review.md`  
**Log:** `docs/audit/logs/02-process-log.md`

---

## Phase 3 — Authorization Review

**Read:**
- `security.py`, `security_schemes.py`
- All router files with `Depends(...)` relating to auth
- Auth middleware in `backend/app/` if present

**For each route:**
- Document whether auth dependencies are enforced or absent.

**Output:** `docs/audit/03-authorization-review.md`  
**Log:** `docs/audit/logs/03-process-log.md`

---

## Phase 4 — Data Flow Review

Sequence diagrams (Report Purchase / Report Unlock / Provider Payout) must be based strictly on directly read source files in Phases 1–3 plus any additional files logged in Phase 4.

**Output:** `docs/audit/04-data-flow.md`  
**Log:** `docs/audit/logs/04-process-log.md`

---

## Phase 5 — Architecture Review

Inspect directory layout and entry points for all top-level and secondary packages across the repository.

**Output:** `docs/audit/05-architecture.md`  
**Log:** `docs/audit/logs/05-process-log.md`

---

## Phase 6 — Executive Summary

Synthesize findings from audit files 1–5 with exact line citations to primary audit reports.

**Output:** `docs/audit/06-summary.md`  
**Log:** `docs/audit/logs/06-process-log.md`

---

## Phase 7 — Verification Pass

Re-verify all 6 audit files against source files to ensure citations and line numbers match 100%.

**Output:** Updated audit files (if needed) + `docs/audit/logs/07-verification-log.md`
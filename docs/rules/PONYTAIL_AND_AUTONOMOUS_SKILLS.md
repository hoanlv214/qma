# PONYTAIL PRINCIPLES & AUTONOMOUS SKILLS ROUTING DIRECTIVE

## 1. CORE PHILOSOPHY: THE PONYTAIL HIERARCHY
Whenever auditing, debugging, designing, refactoring, or building in this codebase, the agent MUST operate under the strict Senior-Dev Ponytail engineering hierarchy:

> **Correct > Safe > Holds under load > Tested > Fast > Lean**

No optimization or architectural clean-up may compromise correctness, thread-safety, or financial/data invariants.

---

## 2. AUTONOMOUS SKILLS DISCOVERY & ACTIVATION
The user should NEVER have to manually remind the agent to activate skills. For any task, the agent MUST proactively identify the task domain and automatically engage the relevant skills:

| Task Domain | Mandatory / Recommended Skills to Auto-Engage |
| :--- | :--- |
| **Codebase Audit & Diagnostics** | `agent-architecture-audit`, `verification-loop`, `systematic-debugging`, `codegraph` |
| **Architecture, Specs & Planning** | `brainstorming`, `writing-plans`, `sdlc-protocol`, `cross-file-consistency` |
| **Backend & API Engineering** | `fastapi-patterns`, `error-handling`, `cross-file-consistency` |
| **Database & Concurrency** | `postgres-patterns`, `database-migrations`, `redis-patterns` |
| **Security & Wallet Authority** | `llm-trading-agent-security`, `agent-wallet-policy`, `credentials` |
| **Implementation Discipline** | `test-driven-development`, `tdd-superpowers`, `executing-plans`, `subagent-driven-development` |
| **Frontend & UI/UX Design** | `ui-ux-pro-max`, `design-taste-frontend`, `make-interfaces-feel-better`, `react-patterns`, `react-performance`, `web-quality` |
| **Pre-Completion & Verification** | `verification-before-completion`, `requesting-code-review`, `finishing-a-development-branch` |

---

## 3. PONYTAIL AUDIT CHECKLIST (MANDATORY INVARIANTS)
Whenever conducting an audit (`/ponytail`, "audit", "rà soát", "kiểm tra hệ thống"), the agent MUST systematically evaluate the 6 invariant axes:

### Axis 1: Concurrency, Deadlocks & Thread Contention
- Inspect nested locks (`Lock`, `RLock`, `Semaphore`) for inverted acquisition order or re-entrant deadlocks.
- Verify thread pools are strictly bounded (e.g. `ThreadPoolExecutor(max_workers=...)`) with named worker prefixes.
- Confirm every acquired database connection or lock is guaranteed to be released in a `finally:` block or context manager.
- Verify PostgreSQL connection pool health: recycle closed/corrupted connections and rollback aborted transactions before reuse.

### Axis 2: Memory Management & State Eviction
- Detect unbound caches or collections growing indefinitely under production traffic.
- Enforce sliding window bounds, time-to-live (TTL) eviction, or LRU caps for telemetry, rate limiters, and session states.
- Ensure periodic prune/cleanup threads or background tasks do not block request handlers.

### Axis 3: Security & Network Perimeter
- Verify origin shielding: never trust spoofable client headers (`x-forwarded-for`, `x-real-ip`) unless authenticated by trusted reverse proxy / Cloudflare CIDRs.
- Enforce fail-closed access controls on all internal gateway routes (`x-qma-internal-secret`) and administrative APIs (`x-qma-admin-token`).
- Guard against prompt injection, parameter tampering, and unauthorized payment header reuse.

### Axis 4: Financial & Settlement Integrity
- **Zero Mock on Production Paths**: Eliminate fake endpoints, synthetic numbers, or dummy responses that allow bypassing actual payment or verification logic.
- **In-Memory & Storage Parity**: If storage persistence fails, the in-memory cache MUST evict the unpersisted state immediately (`pop`). Uncommitted "paid" states must never linger in RAM.
- **Atomic Settlement**: Settlement IDs and payment nonces must be protected by unique database constraints and serializable/atomic checks to prevent double-spending or replay attacks.

### Axis 5: Clean Modular Separation
- Avoid monolithic god-files. Break down complex orchestration into focused domain services under `backend/app/services/` and `backend/app/infrastructure/`.
- Maintain clean import boundaries: preserve backward-compatible re-exports when refactoring legacy symbol locations so external callers and tests do not break.

### Axis 6: Evidence Over Assertion (E3/E5 Gate)
- Never declare a task, bug fix, or audit complete without executing real test and build commands:
  * Backend test suite: `uv run pytest tests/unit/ tests/services/ tests/api_v1/ -q`
  * Concurrency / Race tests: `uv run pytest tests/integration/test_postgres_concurrency_race.py -v`
  * OpenAPI documentation gate: `uv run pytest tests/api_v1/test_api_openapi_docs.py -q`
  * Frontend production build: `npm run build`
- Present verifiable terminal output before asserting success.

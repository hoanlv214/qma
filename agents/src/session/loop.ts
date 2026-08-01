import type { SessionPolicy } from "./policy.js";
import {
  createSessionState,
  finishSession,
  pauseSession,
  recordAction,
  recordCandidateFailure,
  recordFailure,
  recordObservation,
  recordPurchase,
  sessionReport,
  startSession,
  type PurchaseResult,
  type SessionCandidate,
  type SessionState,
} from "./state.js";

export interface SessionObservation {
  candidates: SessionCandidate[];
  candidateCount?: number;
  metadata?: Record<string, unknown>;
}

export interface SessionDeps {
  observe: (state: SessionState, policy: SessionPolicy) => Promise<SessionObservation>;
  purchase: (candidate: SessionCandidate, state: SessionState, policy: SessionPolicy) => Promise<PurchaseResult>;
  sleep?: (seconds: number, signal?: AbortSignal) => Promise<void>;
  onEvent?: (event: Record<string, unknown>) => void;
  onStateChange?: (state: SessionState) => void;
  now?: () => number;
}

function defaultSleep(seconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, seconds * 1000);
    signal?.addEventListener("abort", () => { clearTimeout(timer); reject(new Error("manual_interrupt")); }, { once: true });
  });
}

function chooseCandidate(state: SessionState, policy: SessionPolicy, candidates: SessionCandidate[]): { candidate?: SessionCandidate; reason: string } {
  const now = (Date.now() / 1000);
  const ownedEntitlements = new Set(state.purchasedEntitlements.map((item) => `${item.provider_id}:${item.symbol.toUpperCase()}:${item.tier}`));
  const eligible = candidates.filter((candidate) => {
    if (!policy.allowedProviders.includes(candidate.provider_id)) return false;
    if (!policy.allowedTiers.includes(candidate.tier)) return false;
    if (candidate.score < policy.minimumScore) return false;
    if (candidate.price_usdc <= 0 || candidate.price_usdc > policy.maxPricePerReportUsdc || candidate.price_usdc > state.remainingBudgetUsdc) return false;
    if (candidate.eligible === false) return false;
    const entitlementKey = `${candidate.provider_id}:${candidate.symbol.toUpperCase()}`;
    const attemptKey = `${entitlementKey}:${candidate.tier}`;
    const hasPreview = ownedEntitlements.has(`${entitlementKey}:preview`);
    const hasFull = ownedEntitlements.has(`${entitlementKey}:full`);
    if (policy.avoidOwnedReports && (candidate.owned || hasFull || (hasPreview && !candidate.upgrade))) return false;
    if (state.purchasedCandidateIds.includes(candidate.candidate_id) && !candidate.upgrade) return false;
    if ((state.failedCandidateAttempts[attemptKey] || 0) >= policy.maxFailedAttemptsPerCandidate) return false;
    if ((state.failedCandidateCooldowns[attemptKey] || 0) > now) return false;
    if ((state.symbolCooldowns[candidate.symbol.toUpperCase()] || 0) > now) return false;
    if (candidate.upgrade && (!policy.upgradePolicy.enabled || candidate.price_usdc > policy.upgradePolicy.maxFullPriceUsdc)) return false;
    return true;
  });
  eligible.sort((a, b) => Number(b.preferred) - Number(a.preferred) || Number(b.upgrade) - Number(a.upgrade) || (b.value_density || b.score) - (a.value_density || a.score));
  return eligible[0]
    ? { candidate: eligible[0], reason: "highest validated value among eligible candidates" }
    : { reason: "no candidate passed provider, tier, ownership, score, cooldown, and price policy" };
}

export async function runAutonomousSession(policy: SessionPolicy, deps: SessionDeps, signal?: AbortSignal, initialState?: Partial<SessionState>): Promise<Record<string, unknown>> {
  const state = createSessionState(policy);
  if (initialState) {
    Object.assign(state, initialState);
  }
  const isResume = !!initialState;

  if (state.status === "completed" || state.status === "failed") {
    throw new Error("Cannot resume a completed or failed session");
  }

  if (state.status === "created") startSession(state);
  else if (state.status === "paused") startSession(state);
  const sleep = deps.sleep || defaultSleep;
  const now = deps.now || (() => Date.now());
  
  if (!isResume) deps.onEvent?.({ event: "session_started", session_id: state.sessionId });
  else deps.onEvent?.({ event: "session_resumed", session_id: state.sessionId });
  deps.onStateChange?.(state);

  try {
    while (state.status === "running") {
      if (signal?.aborted) { pauseSession(state); break; }
      if (policy.stopConditions.stopWhenMaxPurchasesReached && policy.maxPurchases !== null && state.purchaseCount >= policy.maxPurchases) {
        finishSession(state, "completed", "max_purchases_reached"); break;
      }
      if (policy.maxAttempts !== null && state.attemptCount >= policy.maxAttempts) {
        finishSession(state, "completed", "max_attempts_reached"); break;
      }
      if (policy.stopConditions.stopWhenBudgetExhausted && state.remainingBudgetUsdc <= 0) {
        finishSession(state, "completed", "budget_exhausted"); break;
      }
      if (policy.stopConditions.stopWhenDurationElapsed && policy.durationSeconds !== null && state.startedAt && now() - Date.parse(state.startedAt) >= policy.durationSeconds * 1000) {
        finishSession(state, "completed", "duration_elapsed"); break;
      }

      state.attemptCount += 1;
      const observation = await deps.observe(state, policy);
      recordObservation(state, observation.metadata || {}, observation.candidateCount ?? observation.candidates.length);
      const decision = chooseCandidate(state, policy, observation.candidates);
      deps.onEvent?.({
        event: "decision",
        session_id: state.sessionId,
        selected_candidate_id: decision.candidate?.candidate_id || null,
        selected_provider_id: decision.candidate?.provider_id || null,
        selected_symbol: decision.candidate?.symbol || null,
        reason: decision.reason,
        candidate_count: observation.candidateCount ?? observation.candidates.length,
      });
      if (!decision.candidate) {
        const rejected = Array.isArray(observation.metadata?.rejected_candidates) ? observation.metadata.rejected_candidates : [];
        rejected.slice(0, 25).forEach((item) => {
          if (item && typeof item === "object") {
            const rejection = item as Record<string, unknown>;
            recordAction(state, { action: "skip", candidate_id: rejection.candidate_id, reason: rejection.reason_code || rejection.reason });
          }
        });
        recordAction(state, { action: "wait", reason: decision.reason });
        deps.onEvent?.({ event: "wait", session_id: state.sessionId, reason: decision.reason });
      } else {
        const action = decision.candidate.upgrade ? "upgrade" : "purchase";
        recordAction(state, { 
          action: "attempt_" + action, 
          candidate_id: decision.candidate.candidate_id, 
          symbol: decision.candidate.symbol, 
          tier: decision.candidate.tier,
          provider: decision.candidate.provider_id,
          amount_usdc: decision.candidate.price_usdc,
          reason: decision.reason 
        });
        const result = await deps.purchase(decision.candidate, state, policy);
        if (result.status === "completed") {
          recordPurchase(state, policy, decision.candidate, result);
          recordAction(state, { 
            action, 
            candidate_id: decision.candidate.candidate_id, 
            symbol: decision.candidate.symbol, 
            tier: decision.candidate.tier,
            provider: decision.candidate.provider_id,
            amount_usdc: result.amount_usdc ?? decision.candidate.price_usdc,
            reason: decision.reason 
          });
          deps.onEvent?.({ event: "purchase_completed", session_id: state.sessionId, ...result });
        } else {
          const error = result.error || "purchase_failed";
          recordCandidateFailure(state, policy, decision.candidate, error);
          recordAction(state, { action: "retry_backoff", candidate_id: decision.candidate.candidate_id, reason: error });
          deps.onEvent?.({ event: "purchase_failed", session_id: state.sessionId, ...result });
        }
      }
      if (policy.runOnce) { finishSession(state, "completed", "run_once"); break; }
      deps.onStateChange?.(state);
      await sleep(policy.pollIntervalSeconds, signal);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message === "manual_interrupt" || signal?.aborted) pauseSession(state);
    else { recordFailure(state, { error: message }); finishSession(state, "failed", message); }
  }
  deps.onStateChange?.(state);
  deps.onEvent?.({ event: "session_finished", session_id: state.sessionId, stop_reason: state.stopReason });
  return sessionReport(state, policy);
}

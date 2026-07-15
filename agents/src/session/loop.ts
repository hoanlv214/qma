import type { SessionPolicy } from "./policy.js";
import {
  createSessionState,
  finishSession,
  recordAction,
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
  const eligible = candidates.filter((candidate) => {
    if (!policy.allowedProviders.includes(candidate.provider_id)) return false;
    if (!policy.allowedTiers.includes(candidate.tier)) return false;
    if (candidate.score < policy.minimumScore) return false;
    if (candidate.price_usdc <= 0 || candidate.price_usdc > policy.maxPricePerReportUsdc || candidate.price_usdc > state.remainingBudgetUsdc) return false;
    if (policy.avoidOwnedReports && candidate.owned) return false;
    if (state.purchasedCandidateIds.includes(candidate.candidate_id)) return false;
    if ((state.symbolCooldowns[candidate.symbol.toUpperCase()] || 0) > now) return false;
    if (candidate.upgrade && (!policy.upgradePolicy.enabled || candidate.price_usdc > policy.upgradePolicy.maxFullPriceUsdc)) return false;
    return true;
  });
  eligible.sort((a, b) => Number(b.upgrade) - Number(a.upgrade) || (b.value_density || b.score) - (a.value_density || a.score));
  return eligible[0]
    ? { candidate: eligible[0], reason: "highest validated value among eligible candidates" }
    : { reason: "no candidate passed provider, tier, ownership, score, cooldown, and price policy" };
}

export async function runAutonomousSession(policy: SessionPolicy, deps: SessionDeps, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const state = createSessionState(policy);
  startSession(state);
  const sleep = deps.sleep || defaultSleep;
  const now = deps.now || (() => Date.now());
  deps.onEvent?.({ event: "session_started", session_id: state.sessionId });

  try {
    while (state.status === "running") {
      if (signal?.aborted) { finishSession(state, "completed", "manual_interrupt"); break; }
      if (policy.stopConditions.stopWhenMaxPurchasesReached && policy.maxPurchases !== null && state.purchaseCount >= policy.maxPurchases) {
        finishSession(state, "completed", "max_purchases_reached"); break;
      }
      if (policy.stopConditions.stopWhenBudgetExhausted && state.remainingBudgetUsdc <= 0) {
        finishSession(state, "completed", "budget_exhausted"); break;
      }
      if (policy.stopConditions.stopWhenDurationElapsed && policy.durationSeconds !== null && state.startedAt && now() - Date.parse(state.startedAt) >= policy.durationSeconds * 1000) {
        finishSession(state, "completed", "duration_elapsed"); break;
      }

      const observation = await deps.observe(state, policy);
      recordObservation(state, observation.metadata || {}, observation.candidateCount ?? observation.candidates.length);
      const decision = chooseCandidate(state, policy, observation.candidates);
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
        recordAction(state, { action, candidate_id: decision.candidate.candidate_id, symbol: decision.candidate.symbol, reason: decision.reason });
        const result = await deps.purchase(decision.candidate, state, policy);
        if (result.status === "completed") {
          recordPurchase(state, policy, decision.candidate, result);
          deps.onEvent?.({ event: "purchase_completed", session_id: state.sessionId, ...result });
        } else {
          recordFailure(state, { action, candidate_id: decision.candidate.candidate_id, error: result.error || "purchase_failed" });
          deps.onEvent?.({ event: "purchase_failed", session_id: state.sessionId, ...result });
        }
      }
      if (policy.runOnce) { finishSession(state, "completed", "run_once"); break; }
      await sleep(policy.pollIntervalSeconds, signal);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message === "manual_interrupt" || signal?.aborted) finishSession(state, "completed", "manual_interrupt");
    else { recordFailure(state, { error: message }); finishSession(state, "failed", message); }
  }
  deps.onEvent?.({ event: "session_finished", session_id: state.sessionId, stop_reason: state.stopReason });
  return sessionReport(state, policy);
}

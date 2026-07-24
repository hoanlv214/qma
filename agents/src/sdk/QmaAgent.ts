import { EventEmitter } from "node:events";
import { QmaClient } from "../qma/client.js";
import { createPaymentExecutor } from "../executor/paymentExecutor.js";
import type { AgentPaymentSigner } from "../wallets/signer.js";
import { runAutonomousSession, SessionDeps } from "../session/loop.js";
import { SessionPolicyInput, normalizeSessionPolicy } from "../session/policy.js";

export interface QmaAgentConfig {
  apiUrl?: string;
  apiKey?: string;
  signer?: AgentPaymentSigner;
}

export interface QmaAgentRunOptions extends SessionPolicyInput {
  initialState?: import("../session/state.js").SessionState;
}

export class QmaAgent extends EventEmitter {
  private client: QmaClient;
  private signer?: AgentPaymentSigner;

  private _state?: import("../session/state.js").SessionState;

  constructor(config: QmaAgentConfig = {}) {
    super();
    this.client = new QmaClient({ baseUrl: config.apiUrl, apiKey: config.apiKey });
    this.signer = config.signer;
  }

  getState(): import("../session/state.js").SessionState | undefined {
    return this._state;
  }

  async run(options: QmaAgentRunOptions, signal?: AbortSignal): Promise<Record<string, unknown>> {
    const policy = normalizeSessionPolicy(options);
    const executor = createPaymentExecutor(this.signer);

    const deps: SessionDeps = {
      observe: async (state, policy) => {
        const decision = await this.client.getAgentDecision({
          prompt: policy.task,
          wallet: this.signer?.walletAddress,
          budget_usdc: policy.sessionBudgetUsdc,
          max_price_usdc: policy.maxPricePerReportUsdc,
          limit: 25,
          allowed_providers: policy.allowedProviders,
          allowed_tiers: policy.allowedTiers,
          minimum_score: policy.minimumScore,
          use_llm: false,
        });
        const resolved = decision.resolved_candidate;
        const evaluatedCandidates = Array.isArray(decision.evaluated_candidates)
          ? decision.evaluated_candidates.map((item: any) => ({
            candidate_id: item.candidate_id,
            provider_id: item.provider_id,
            symbol: item.symbol,
            tier: item.tier,
            score: Number(item.score || 0),
            price_usdc: Number(item.price_usdc || 0),
            value_density: Number(item.value_density || 0),
            eligible: item.eligible !== false,
            preferred: item.candidate_id === resolved?.candidate_id,
            owned: item.status === "ALREADY_OWNED",
            upgrade: Boolean(item.upgrade),
            canonical_query: item.canonical_query || (item.candidate_id === resolved?.candidate_id ? decision.canonical_query : undefined),
          }))
          : resolved ? [{ ...resolved, owned: false, canonical_query: decision.canonical_query }] : [];
        return {
          candidates: evaluatedCandidates,
          candidateCount: Number(decision.candidate_count || 0),
          metadata: {
            decision_source: decision.decision_source,
            plan: decision.plan,
            selection_basis: decision.selection_basis,
            policy_check: decision.policy_check,
            evaluated_candidates: decision.evaluated_candidates,
            rejected_candidates: decision.rejected_candidates,
          },
        };
      },
      purchase: async (candidate, state, policy) => {
        if (policy.executionMode === "dry_run") {
          return {
            status: "completed",
            provider_id: candidate.provider_id,
            symbol: candidate.symbol,
            tier: candidate.upgrade ? "full" : candidate.tier as any,
            amount_usdc: candidate.price_usdc,
            settlement_ids: ["dry_run_settlement_mock"]
          };
        }
        try {
          const invoice = await this.client.createAgentInvoice({
            candidate_id: candidate.candidate_id,
            provider_id: candidate.provider_id,
            symbol: candidate.symbol,
            tier: candidate.upgrade ? "full" : candidate.tier,
            expected_price_usdc: candidate.price_usdc,
            buyer_wallet_address: this.signer?.walletAddress || undefined,
            ...(candidate.canonical_query || {})
          });
          const invoiceAmount = Number(invoice.amount || 0);
          if (invoiceAmount > candidate.price_usdc * 1.01 || invoiceAmount > policy.maxPricePerReportUsdc) {
            return {
              status: "failed",
              error: `invoice_price_exceeds_policy: returned amount ${invoiceAmount} > allowed ${candidate.price_usdc}`
            };
          }
          const execution = await executor.execute({ invoice });
          return {
            status: "completed",
            provider_id: candidate.provider_id,
            symbol: candidate.symbol,
            tier: candidate.upgrade ? "full" : candidate.tier as any,
            amount_usdc: candidate.price_usdc,
            settlement_ids: execution.settlements.map((s) => s.settlement_id)
          };
        } catch (e) {
          return {
            status: "failed",
            error: e instanceof Error ? e.message : String(e)
          };
        }
      },
      onEvent: (payload) => {
        const eventType = typeof payload.event === "string" ? payload.event : "unknown";
        this.emit(eventType, payload);
      },
      onStateChange: (state) => {
        this._state = state;
        this.emit("state_change", state);
      }
    };

    return runAutonomousSession(policy, deps, signal, options.initialState);
  }
}

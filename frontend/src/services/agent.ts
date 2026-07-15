import { requestJson } from "./api";

export interface AgentDecisionResponse {
  status: string;
  plan: {
    action: "purchase" | "skip" | "clarify";
    candidate_id: string | null;
    requested_tier: "preview" | "full" | "auto";
    budget_usdc: number;
    max_price_usdc: number;
    reason: string;
    rejected_candidate_ids: string[];
  };
  validation: { valid: boolean; errors: string[]; warnings: string[] };
  resolved_candidate: {
    candidate_id: string;
    provider_id: string;
    provider_name?: string;
    symbol: string;
    tier: "preview" | "full";
    score: number;
    price_usdc: number;
    value_density: number;
    upgrade?: boolean;
  } | null;
  canonical_query: Record<string, any> | null;
  policy_check: Record<string, boolean>;
  rejected_candidates: Array<{
    candidate_id: string;
    reason_code: string;
    reason: string;
    observed_price_usdc?: number;
    limit_usdc?: number;
  }>;
  evaluated_candidates: Array<Record<string, any>>;
  candidate_count: number;
  decision_source: "llm" | "deterministic_policy" | "cached_policy";
}

export function requestAgentDecision(prompt: string, wallet?: string) {
  return requestJson<AgentDecisionResponse>("/api/v1/agent/decision", {
    method: "POST",
    body: JSON.stringify({ prompt, wallet: wallet || undefined, limit: 25 }),
  });
}

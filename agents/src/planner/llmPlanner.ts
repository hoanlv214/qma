import type { AgentDecision, DecisionContext } from "../contracts/index.js";
import { parseAgentDecision, parseAgentDecisionJson } from "./schema.js";

export interface LlmDecisionGenerator {
  generateDecision(input: { systemPrompt: string; userPrompt: string; context: DecisionContext }): Promise<unknown | string>;
}

export const DECISION_SYSTEM_PROMPT = [
  "You are the QMA report purchase planner.",
  "Return JSON only using the exact minimal plan schema.",
  "You may select only a candidate_id from the supplied candidates.",
  "Never return provider metadata, symbol, score, price, query, invoice, payment, settlement, or access-token fields.",
  "If no eligible candidate satisfies the request, return action=skip; if the request is ambiguous, return action=clarify.",
].join(" ");

export function buildDecisionPrompt(context: DecisionContext): string {
  return JSON.stringify({
    task: context.prompt,
    budget_usdc: context.budgetUsdc,
    max_price_usdc: context.maxPriceUsdc,
    candidates: context.candidates.map((candidate) => ({
      candidate_id: candidate.candidateId,
      symbol: candidate.symbol,
      score: candidate.score,
      suggested_tier: candidate.suggestedTier,
      reasons: candidate.reasons,
    })),
    entitlements: context.entitlements.map((entry) => ({ symbol: entry.symbol, tier: entry.tier, provider_id: entry.providerId })),
  });
}

export async function planWithLlm(generator: LlmDecisionGenerator, context: DecisionContext): Promise<AgentDecision> {
  const result = await generator.generateDecision({
    systemPrompt: DECISION_SYSTEM_PROMPT,
    userPrompt: buildDecisionPrompt(context),
    context,
  });
  return typeof result === "string" ? parseAgentDecisionJson(result) : parseAgentDecision(result);
}

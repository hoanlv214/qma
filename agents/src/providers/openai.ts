import type { DecisionContext } from "../contracts/index.js";
import type { LlmDecisionGenerator } from "../planner/llmPlanner.js";

const DECISION_SCHEMA = {
  type: "object",
  additionalProperties: false,
  properties: {
    action: { type: "string", enum: ["purchase", "skip", "clarify"] },
    candidate_id: { type: ["string", "null"] },
    requested_tier: { type: "string", enum: ["preview", "full", "auto"] },
    budget_usdc: { type: "number", minimum: 0 },
    max_price_usdc: { type: "number", minimum: 0 },
    reason: { type: "string" },
    rejected_candidate_ids: {
      type: "array",
      maxItems: 25,
      items: { type: "string" },
    },
  },
  required: [
    "action",
    "candidate_id",
    "requested_tier",
    "budget_usdc",
    "max_price_usdc",
    "reason",
    "rejected_candidate_ids",
  ],
} as const;

interface OpenAiResponse {
  choices?: Array<{
    message?: { content?: string | null; refusal?: string | null };
  }>;
  error?: { message?: string };
}

export class OpenAiDecisionGenerator implements LlmDecisionGenerator {
  private readonly apiKey: string;
  private readonly model: string;

  constructor(options: { apiKey?: string; model?: string } = {}) {
    this.apiKey = options.apiKey || process.env.OPENAI_API_KEY || "";
    this.model = options.model || process.env.QMA_LLM_MODEL || "gpt-4o-mini";
    if (!this.apiKey) {
      throw new Error("OPENAI_API_KEY is required for the LLM planner.");
    }
  }

  async generateDecision(input: {
    systemPrompt: string;
    userPrompt: string;
    context: DecisionContext;
  }): Promise<unknown> {
    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: this.model,
        messages: [
          { role: "system", content: input.systemPrompt },
          { role: "user", content: input.userPrompt },
        ],
        response_format: {
          type: "json_schema",
          json_schema: {
            name: "qma_agent_decision",
            strict: true,
            schema: DECISION_SCHEMA,
          },
        },
      }),
      signal: AbortSignal.timeout(30_000),
    });

    const data = await response.json() as OpenAiResponse;
    if (!response.ok) {
      throw new Error(`OpenAI returned HTTP ${response.status}: ${data.error?.message || "unknown error"}`);
    }

    const message = data.choices?.[0]?.message;
    if (message?.refusal) throw new Error(`OpenAI refused the decision: ${message.refusal}`);
    if (!message?.content) throw new Error("OpenAI returned an empty decision.");
    return message.content;
  }
}

export type ExecutionMode = "dry_run" | "live";
import type { AgentTier } from "../contracts/index.js";

export interface UpgradePolicy {
  enabled: boolean;
  requireOwnedPreview: boolean;
  maxFullPriceUsdc: number;
}

export interface StopConditions {
  stopWhenBudgetExhausted: boolean;
  stopWhenMaxPurchasesReached: boolean;
  stopWhenDurationElapsed: boolean;
  stopOnManualInterrupt: boolean;
}

export interface SessionPolicy {
  policyVersion: "1";
  task: string;
  executionMode: ExecutionMode;
  sessionBudgetUsdc: number;
  maxPricePerReportUsdc: number;
  maxPurchases: number | null;
  durationSeconds: number | null;
  runOnce: boolean;
  pollIntervalSeconds: number;
  allowedProviders: string[];
  allowedTiers: AgentTier[];
  minimumScore: number;
  avoidOwnedReports: boolean;
  symbolCooldownSeconds: number;
  autoDepositGateway: boolean;
  upgradePolicy: UpgradePolicy;
  stopConditions: StopConditions;
}

export interface SessionPolicyInput {
  task: string;
  executionMode?: ExecutionMode;
  sessionBudgetUsdc: number;
  maxPricePerReportUsdc: number;
  maxPurchases?: number | null;
  durationSeconds?: number | null;
  runOnce?: boolean;
  pollIntervalSeconds?: number;
  allowedProviders?: string[];
  allowedTiers?: AgentTier[];
  minimumScore?: number;
  avoidOwnedReports?: boolean;
  symbolCooldownSeconds?: number;
  autoDepositGateway?: boolean;
  upgradePolicy?: Partial<UpgradePolicy>;
  stopConditions?: Partial<StopConditions>;
}

export function parseDurationSeconds(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number") return Number.isFinite(value) && value >= 0 ? value : null;
  const match = value.trim().match(/^(\d+(?:\.\d+)?)(s|m|h|d)?$/i);
  if (!match) return null;
  const amount = Number(match[1]);
  const multiplier = { s: 1, m: 60, h: 3600, d: 86400 }[String(match[2] || "s").toLowerCase() as "s" | "m" | "h" | "d"];
  return amount * multiplier;
}

export function validateSessionPolicy(policy: SessionPolicy): string[] {
  const errors: string[] = [];
  if (!policy.task.trim()) errors.push("task is required");
  if (!Number.isFinite(policy.sessionBudgetUsdc) || policy.sessionBudgetUsdc < 0) errors.push("session budget must be non-negative");
  if (!Number.isFinite(policy.maxPricePerReportUsdc) || policy.maxPricePerReportUsdc < 0) errors.push("max price must be non-negative");
  if (policy.maxPricePerReportUsdc > policy.sessionBudgetUsdc) errors.push("max price cannot exceed session budget");
  if (policy.maxPurchases !== null && (!Number.isInteger(policy.maxPurchases) || policy.maxPurchases < 1)) errors.push("max purchases must be null or a positive integer");
  if (policy.durationSeconds !== null && (!Number.isFinite(policy.durationSeconds) || policy.durationSeconds < 0)) errors.push("duration must be null or non-negative");
  if (!Number.isFinite(policy.pollIntervalSeconds) || policy.pollIntervalSeconds < 1) errors.push("poll interval must be at least one second");
  if (!Number.isFinite(policy.minimumScore) || policy.minimumScore < 0 || policy.minimumScore > 100) errors.push("minimum score must be between 0 and 100");
  if (!policy.allowedProviders.length) errors.push("at least one allowed provider is required");
  if (!policy.allowedTiers.length) errors.push("at least one allowed tier is required");
  if (policy.allowedTiers.some((tier) => tier !== "preview" && tier !== "full")) errors.push("allowed tiers must be preview or full");
  if (policy.executionMode !== "dry_run" && policy.executionMode !== "live") errors.push("execution mode must be dry_run or live");
  return errors;
}

export function normalizeSessionPolicy(input: SessionPolicyInput): SessionPolicy {
  const policy: SessionPolicy = {
    policyVersion: "1",
    task: input.task.trim(),
    executionMode: input.executionMode || "dry_run",
    sessionBudgetUsdc: Number(input.sessionBudgetUsdc),
    maxPricePerReportUsdc: Number(input.maxPricePerReportUsdc),
    maxPurchases: input.maxPurchases === undefined ? null : input.maxPurchases,
    durationSeconds: input.durationSeconds === undefined ? null : input.durationSeconds,
    runOnce: input.runOnce ?? false,
    pollIntervalSeconds: input.pollIntervalSeconds ?? 60,
    allowedProviders: [...new Set(input.allowedProviders?.filter(Boolean) || ["funding_memory", "oi_memory"])],
    allowedTiers: [...new Set(input.allowedTiers || ["preview", "full"])] as AgentTier[],
    minimumScore: input.minimumScore ?? 0,
    avoidOwnedReports: input.avoidOwnedReports ?? true,
    symbolCooldownSeconds: input.symbolCooldownSeconds ?? 600,
    autoDepositGateway: input.autoDepositGateway ?? false,
    upgradePolicy: {
      enabled: input.upgradePolicy?.enabled ?? true,
      requireOwnedPreview: input.upgradePolicy?.requireOwnedPreview ?? true,
      maxFullPriceUsdc: input.upgradePolicy?.maxFullPriceUsdc ?? Number(input.maxPricePerReportUsdc),
    },
    stopConditions: {
      stopWhenBudgetExhausted: input.stopConditions?.stopWhenBudgetExhausted ?? true,
      stopWhenMaxPurchasesReached: input.stopConditions?.stopWhenMaxPurchasesReached ?? true,
      stopWhenDurationElapsed: input.stopConditions?.stopWhenDurationElapsed ?? true,
      stopOnManualInterrupt: input.stopConditions?.stopOnManualInterrupt ?? true,
    },
  };
  const errors = validateSessionPolicy(policy);
  if (errors.length) throw new Error(`Invalid session policy: ${errors.join("; ")}`);
  return policy;
}

import assert from "node:assert/strict";
import { normalizeSessionPolicy, runAutonomousSession } from "../dist/index.js";

const policy = normalizeSessionPolicy({
  task: "test bounded session",
  sessionBudgetUsdc: 0.01,
  maxPricePerReportUsdc: 0.005,
  maxPurchases: 1,
  runOnce: false,
  pollIntervalSeconds: 1,
});

let observations = 0;
const report = await runAutonomousSession(policy, {
  observe: async () => {
    observations += 1;
    return {
      candidateCount: 4,
      candidates: [{
        candidate_id: "candidate-1",
        provider_id: "funding_memory",
        symbol: "SXT",
        tier: "preview",
        score: 80,
        price_usdc: 0.001,
      }],
    };
  },
  purchase: async (candidate) => ({ status: "completed", amount_usdc: candidate.price_usdc, report_unlocked: true }),
});

assert.equal(observations, 1);
assert.equal(report.status, "completed");
assert.equal(report.stop_reason, "max_purchases_reached");
assert.equal(report.purchase_count, 1);
assert.equal(report.candidates_evaluated, 4);
assert.equal(report.spent_usdc, 0.001);
assert.equal(report.remaining_budget_usdc, 0.009);
console.log("bounded session smoke PASS");

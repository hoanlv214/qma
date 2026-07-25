# @qma/agents

The shared autonomous runtime used by QMA CLI, backend workers, and future UI integrations.

`@qma/agents` provides the execution engine for running background AI agents that can autonomously evaluate, purchase, and consume x402-monetized intelligence reports using USDC stablecoins.

## Quick Start (5 Minutes)

Run an autonomous agent locally using the Circle Agent Wallet.

1. **Install Circle CLI globally:**
   ```bash
   npm install -g @circle-fin/cli
   ```
2. **Login and authenticate:**
   ```bash
   circle wallet login your-email@domain.com
   ```
3. **Create your Agent Wallet:**
   ```bash
   circle wallet create
   ```
4. **Fund your Agent Wallet:**
   Transfer USDC to your Agent Wallet address on the Arc Testnet. 
   *(Note: The CLI and SDK will automatically detect your on-chain USDC balance and handle the deposit into the Circle Gateway for you when starting a session, so manual Gateway deposit is optional).*
5. **Install the SDK:**
   *Note: This package is ESM-only and requires Node.js >= 20.*
   ```bash
   npm install qma-cli
   ```
6. **Run your Agent:**
   Create an `index.ts` file in your project, replace the placeholder `address` with yours, and run it:
   ```typescript
   import { QmaAgent } from "qma-cli";
   import { createCircleAgentWalletSigner } from "qma-cli/circle-wallet";

   const signer = createCircleAgentWalletSigner({ address: "0x...", chain: "ARC-TESTNET" });
   const agent = new QmaAgent({ signer });

   await agent.run({
     task: "Buy trending reports",
     sessionBudgetUsdc: 15,
     maxPricePerReportUsdc: 5,
     maxPurchases: 3,
     executionMode: "live"
   });
   ```



## Payment Modes

The agent behavior depends entirely on which `AgentPaymentSigner` you provide.

| | Mode A (Circle Agent Wallet) | Mode B (Browser Wallet) |
|---|---|---|
| **Runs unattended** | Yes, for hours, no human present | No — needs tab open + user present per purchase |
| **Where it executes** | Node Worker / Backend | Client-side, directly in the browser |
| **Category** | Autonomous agent | Assistant (recommends, human approves) |

### Mode A: Circle Agent Wallet (Fully Autonomous)
Uses the `circle` CLI to execute payments. Once the Gateway is funded, the agent can run for hours without any manual intervention.

```text
Circle Agent Wallet
      ↓ deposit
Circle Gateway Balance
      ↓ automatic x402 payment
Providers
```

```typescript
import { QmaAgent } from "@qma/agents";
import { createCircleAgentWalletSigner } from "@qma/agents/circle-wallet";

const signer = createCircleAgentWalletSigner({ address: "0x...", chain: "ARC-TESTNET" });
const agent = new QmaAgent({ signer, apiUrl: "http://localhost:8000" });
```

### Mode B: Browser Wallet (Manual)
Uses Metamask, viem, or ethers.js. The user must manually sign every single x402 purchase popup.

> ⚠️ **Mode B is not autonomous.** The decision loop still runs automatically, but execution pauses at every purchase waiting for a wallet signature. The user must keep the tab open and be physically present for the full session. If the tab closes, the session dies. This mode behaves as an assistant, not an unattended agent.

```typescript
import { QmaAgent } from "@qma/agents";

const customSigner = {
  walletAddress: "0x...",
  async signLeg(resourceUrl: string) { return { paymentHeader: "..." }; }
};
const agent = new QmaAgent({ signer: customSigner, apiUrl: "http://localhost:8000" });
```

## Autonomous Sessions

The `QmaAgent.run()` method kicks off an autonomous polling loop. 
1. The agent fetches market intelligence candidates from the QMA Backend.
2. The agent uses deterministic backend scoring (via `agent_decision.py`) to rank candidates.
3. It filters candidates against your strict **Session Policy** (budget, max price, cooldowns).
4. If a candidate passes all checks, it automatically triggers an x402 payment using your configured Wallet.

The loop stops automatically when:
- The budget is exhausted.
- The `durationSeconds` time expires.
- The `maxPurchases` limit is reached.
- You manually trigger an `AbortSignal`.

## Resuming Sessions

The SDK emits state changes after every tick. You can persist this state to a database and resume the agent later if it crashes or is stopped.

```typescript
// 1. Save state during execution
agent.on("state_change", (state) => {
  // await db.sessions.update(sessionId, state);
});

// 2. Resume later
// const savedState = await db.sessions.get(sessionId);
await agent.run({
  task: "Find AI tokens",
  initialState: savedState // Agent resumes exactly where it left off
});
```

## Events

You can listen to lifecycle events emitted during the session. This is incredibly useful for piping logs to a database or streaming to a UI via SSE.

```typescript
agent.on("session_started", (e) => { ... });
agent.on("session_resumed", (e) => { ... });    // Resumed from a saved state
agent.on("state_change", (e) => { ... });       // Emitted after every tick to allow persistence
agent.on("decision", (e) => { ... });           // The backend ranked a candidate
agent.on("wait", (e) => { ... });               // No candidates passed policy, agent sleeps
agent.on("purchase_completed", (e) => { ... }); // x402 settled successfully
agent.on("purchase_failed", (e) => { ... });    // Transaction failed or ran out of funds
agent.on("session_finished", (e) => { ... });   // Loop exited gracefully
```

## Policies

The Session Policy is the strict boundary that the AI cannot override.

```typescript
await agent.run({
  task: "Buy random reports",
  sessionBudgetUsdc: 50,            // Absolute maximum agent can spend
  maxPricePerReportUsdc: 5,         // Prevent agent from buying expensive single reports
  durationSeconds: 3600,            // Automatically kill agent after 1 hour
  maxFailedAttemptsPerCandidate: 3, // Anti-looping protection
  executionMode: "dry_run"          // Set to "live" to spend real USDC. "dry_run" fully mocks the payment executor and does not validate real invoices.
});
```

## Error Handling

The loop is designed to be resilient. Temporary network errors during observation or purchase (`purchase_failed`) will not crash the loop. Instead, the agent logs the failure, triggers a short cooldown for that specific provider, and tries again on the next tick.

## Advanced Usage (Low-Level APIs)

While `QmaAgent` is a convenient facade, the SDK is fully modular. You can bypass `QmaAgent` and build your own runtime loop using the low-level primitives:

### `runAutonomousSession`
The core engine. It manages the loop, candidate fetching, cooldowns, and policy evaluation independently of any specific backend or payment method. You inject dependencies via `SessionDeps`.

```typescript
import { runAutonomousSession, normalizeSessionPolicy } from "@qma/agents";

await runAutonomousSession(
  normalizeSessionPolicy({ sessionBudgetUsdc: 10 }),
  initialState,
  {
    now: () => Date.now(),
    sleep: (ms) => new Promise(r => setTimeout(r, ms)),
    observe: async (state) => { /* fetch candidates */ },
    purchase: async (candidate) => { /* execute payment */ },
    onStateChange: (state) => { /* persist state */ },
    onEvent: (event) => { /* broadcast via SSE */ }
  },
  abortSignal
);
```

### Payment Executor
You can use `createPaymentExecutor()` standalone to handle split-leg invoices independently of the agent loop. It requires an `AgentPaymentSigner` to fulfill the actual signatures.

## API Reference

### `QmaAgent(config)`
- `config.apiKey`: (Optional) Your QMA API Key. Overrides `process.env.QMA_API_KEY`.
- `config.apiUrl`: (Optional) The QMA Backend URL. Defaults to `http://127.0.0.1:8000` (localhost) or the `QMA_API_URL` environment variable if set.
- `config.signer`: (Optional) The `AgentPaymentSigner` for x402 execution.

### `agent.run(options, signal?)`
Starts the session. Returns a Promise resolving to the final Session Report (a lossy summary of the run). To access the raw `SessionState`, use `agent.getState()`.
- `options`: A `SessionPolicyInput` object defining the task and boundaries. Can also include an `initialState` object to resume a previous session.
- `signal`: An `AbortSignal` to manually interrupt the loop.

import { QmaAgent } from "./index.js";
import { createCircleAgentWalletSigner } from "./wallets/circleSigner.js";
const API_BASE_URL = process.env.API_BASE_URL || "http://127.0.0.1:8000";
const POLL_INTERVAL_MS = 5000;

async function updateSessionState(sessionId: string, state: any, status?: string) {
  try {
    const body: any = { runtime_state: state };
    if (status) body.status = status;

    const res = await fetch(`${API_BASE_URL}/api/v1/sessions/${sessionId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    
    if (!res.ok) {
      console.error(`Failed to update session state:`, await res.text());
    }
  } catch (e) {
    console.error(`Network error updating session state:`, e);
  }
}

async function runWorkerLoop() {
  console.log("Worker started. Polling for queued sessions...");
  
  while (true) {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/sessions/pick`, { method: "POST" });
      
      if (res.ok) {
        const session = await res.json();
        console.log(`[Worker] Acquired queued session atomically: ${session.id}`);

      const signer = createCircleAgentWalletSigner({
        address: process.env.AGENT_WALLET_ADDRESS || "0x4859d0d0babdcc8c4d8d2d116258fd0e5f7ff67d",
        chain: "ARC-TESTNET"
      });
      const agent = new QmaAgent({ signer });

      async function pushEvent(sessionId: string, eventType: string, payload: any) {
        try {
          const res = await fetch(`${API_BASE_URL}/api/v1/sessions/${sessionId}/events`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ event_type: eventType, payload })
          });
          if (!res.ok) {
            console.error(`Failed to push event ${eventType}:`, await res.text());
          }
        } catch (e) {
          console.error(`Network error pushing event ${eventType}:`, e);
        }
      }

      agent.on("state_change", async (state) => {
        console.log(`[Worker] Session ${session.id} state changed: ${state.status}, purchases: ${state.purchaseCount}`);
        await updateSessionState(session.id, state);
      });

      agent.on("purchase_completed", async (event) => {
        console.log(`[Worker] Session ${session.id} purchased ${event.symbol} for ${event.amount_usdc} USDC.`);
        await pushEvent(session.id, "purchase_completed", event);
      });

      agent.on("purchase_failed", async (event) => {
        console.log(`[Worker] Session ${session.id} purchase failed: ${event.error}`);
        await pushEvent(session.id, "purchase_failed", event);
      });

      try {
        console.log(`[Worker] Starting QmaAgent for session ${session.id}`, "RUNTIME_STATE IS:", session.runtime_state);
        const ac = new AbortController();
        const statusCheckInterval = setInterval(async () => {
          try {
            const res = await fetch(`${API_BASE_URL}/api/v1/sessions/${session.id}`);
            if (res.ok) {
              const data = await res.json();
              if (data.status === "stopped") {
                console.log(`[Worker] Session ${session.id} stopped externally. Aborting.`);
                ac.abort();
              }
            }
          } catch (e) { /* ignore */ }
        }, 3000);

        try {
          let parsedMaxPurchases: number | null = null;
          const qtyMatch = session.task.match(/(?:buy|purchase|get)\s+(\d+)/i);
          if (qtyMatch) {
            parsedMaxPurchases = parseInt(qtyMatch[1], 10);
          }

          // Support resume: if session.runtime_state exists, pass it as initialState
          await agent.run({
            task: session.task,
            sessionBudgetUsdc: session.budget_usdc,
            maxPricePerReportUsdc: Math.min(5, session.budget_usdc), // prevent policy error
            maxPurchases: parsedMaxPurchases,
            executionMode: "live",
            initialState: session.runtime_state || undefined
          }, ac.signal);
        } finally {
          clearInterval(statusCheckInterval);
        }

        console.log(`[Worker] Session ${session.id} finished.`);
        // Mark as completed or stopped
        const finalStatus = ac.signal.aborted ? "stopped" : "completed";
        await updateSessionState(session.id, agent.getState(), finalStatus);
      } catch (err) {
        console.error(`[Worker] Session ${session.id} failed:`, err);
        await updateSessionState(session.id, agent.getState(), "failed");
      }
      }
    } catch (e) {
      console.error("Worker poll error:", e);
    }

    // Sleep before next poll
    await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
  }
}

runWorkerLoop().catch(console.error);

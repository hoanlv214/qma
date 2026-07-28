/**
 * QMA Autonomous Background Worker
 * 
 * This worker polls the database for queued agent sessions, automates prepaid
 * Gateway deposits from the agent's on-chain wallet if needed, and spins up
 * the QmaAgent lifecycle loops. It also hosts a minimal HTTP server for
 * Render web service health checks and external keep-alive cron pings.
 */

import { QmaAgent } from "./index.js";
import { createCircleAgentWalletSigner } from "./wallets/circleSigner.js";
import { privateKeyToAccount } from "viem/accounts";
import * as fs from "node:fs";
import * as path from "node:path";
import * as http from "node:http";

// Start a dummy HTTP server for Render free web service health checks & external keep-alive cron pings
const PORT = process.env.PORT || 10000;
http.createServer((req, res) => {
  const url = req.url || "/";
  if (url === "/health") {
    console.log(`[Worker] Keep-alive health check ping received from ${req.socket.remoteAddress}`);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", service: "qma-agent-worker", uptime: process.uptime() }));
  } else {
    res.writeHead(200, { "Content-Type": "text/plain" });
    res.end("QMA Worker is active\n");
  }
}).listen(PORT, () => {
  console.log(`[Worker] Dummy HTTP server listening on port ${PORT} for Render health checks and /health pings.`);
});

function loadEnv() {
  try {
    const envPath = path.resolve(process.cwd(), ".env");
    if (fs.existsSync(envPath)) {
      const content = fs.readFileSync(envPath, "utf-8");
      for (const line of content.split("\n")) {
        const trimmed = line.trim();
        if (trimmed && !trimmed.startsWith("#") && trimmed.includes("=")) {
          const [key, ...valueParts] = trimmed.split("=");
          const val = valueParts.join("=").trim().replace(/^['"]|['"]$/g, "");
          process.env[key.trim()] = val;
        }
      }
    }
  } catch (e) {
    console.error("Failed to load .env file:", e);
  }
}
loadEnv();

const API_BASE_URL = process.env.API_BASE_URL || "http://127.0.0.1:8000";
const ARC_GATEWAY_URL = process.env.QMA_ARC_GATEWAY_URL || process.env.ARC_GATEWAY_URL || "http://127.0.0.1:3000";
const INTERNAL_SECRET = process.env.QMA_ARC_GATEWAY_INTERNAL_SECRET ?? "";
const POLL_INTERVAL_MS = 5000;

function sessionHeaders(includeJson = false): Record<string, string> {
  const headers: Record<string, string> = {};
  if (includeJson) headers["Content-Type"] = "application/json";
  if (INTERNAL_SECRET) headers["x-qma-internal-secret"] = INTERNAL_SECRET;
  return headers;
}

async function updateSessionState(sessionId: string, state: any, status?: string) {
  try {
    const body: any = { runtime_state: state };
    if (status) body.status = status;

    const res = await fetch(`${API_BASE_URL}/api/v1/sessions/${sessionId}`, {
      method: "PATCH",
      headers: sessionHeaders(true),
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
      const res = await fetch(`${API_BASE_URL}/api/v1/sessions/pick`, {
        method: "POST",
        headers: sessionHeaders(),
      });

      if (res.ok) {
        const session = await res.json();
        console.log(`[Worker] Acquired queued session atomically: ${session.id}`);

        let signer;
        const runtimeState = session.runtime_state || {};
        const agentWalletAddress = runtimeState.agent_wallet_address;
        const agentWalletId = runtimeState.agent_wallet_id;

        if (agentWalletAddress && agentWalletId) {
          console.log(`[Worker] Using session-specific Circle Developer-Controlled Wallet: ${agentWalletAddress}`);
          signer = {
            walletAddress: agentWalletAddress,
            async signLeg(resourceUrl: string) {
              const resp = await fetch(resourceUrl);
              if (resp.status !== 402) {
                throw new Error(`Expected x402 402 challenge, got ${resp.status}: ${await resp.text()}`);
              }
              const requiredHeader = resp.headers.get("PAYMENT-REQUIRED") || resp.headers.get("payment-required");
              if (!requiredHeader) {
                throw new Error("Arc Gateway did not return PAYMENT-REQUIRED header.");
              }
              const challenge = JSON.parse(Buffer.from(requiredHeader, "base64").toString("utf8"));
              const accepted = challenge.accepts[0];

              const now = Math.floor(Date.now() / 1000);
              const validAfter = now - 600;
              const validBefore = now + Math.max(Number(accepted.maxTimeoutSeconds || 0), 7 * 24 * 3600 + 600);
              const crypto = await import("node:crypto");
              const nonce = "0x" + Array.from(crypto.randomBytes(32)).map((b: any) => b.toString(16).padStart(2, "0")).join("");

              const typedData = {
                types: {
                  EIP712Domain: [
                    { name: "name", type: "string" },
                    { name: "version", type: "string" },
                    { name: "chainId", type: "uint256" },
                    { name: "verifyingContract", type: "address" },
                  ],
                  TransferWithAuthorization: [
                    { name: "from", type: "address" },
                    { name: "to", type: "address" },
                    { name: "value", type: "uint256" },
                    { name: "validAfter", type: "uint256" },
                    { name: "validBefore", type: "uint256" },
                    { name: "nonce", type: "bytes32" },
                  ],
                },
                primaryType: "TransferWithAuthorization" as const,
                domain: {
                  name: "GatewayWalletBatched",
                  version: "1",
                  chainId: 5042002, // Arc Testnet
                  verifyingContract: accepted.extra.verifyingContract,
                },
                message: {
                  from: agentWalletAddress,
                  to: accepted.payTo,
                  value: accepted.amount,
                  validAfter: String(validAfter),
                  validBefore: String(validBefore),
                  nonce,
                },
              };

              const headers: Record<string, string> = { "Content-Type": "application/json" };
              if (INTERNAL_SECRET) {
                headers["x-qma-internal-secret"] = INTERNAL_SECRET;
              }

              console.log(`[Worker] Requesting EIP-712 signature from Gateway for wallet ${agentWalletId}`);
              const signResp = await fetch(`${ARC_GATEWAY_URL.replace(/\/$/, "")}/api/wallet/sign-typed-data`, {
                method: "POST",
                headers,
                body: JSON.stringify({
                  walletId: agentWalletId,
                  data: typedData,
                })
              });

              if (!signResp.ok) {
                throw new Error(`Failed to sign typed data via Gateway: ${await signResp.text()}`);
              }

              const signResult = await signResp.json();
              const signature = signResult.signature;

              return {
                paymentHeader: Buffer.from(JSON.stringify({
                  x402Version: 2,
                  payload: {
                    signature,
                    authorization: {
                      from: agentWalletAddress,
                      to: accepted.payTo,
                      value: accepted.amount,
                      validAfter: String(validAfter),
                      validBefore: String(validBefore),
                      nonce,
                    },
                  },
                  accepted,
                  resource: challenge.resource,
                })).toString("base64")
              };
            }
          };
        } else if (process.env.AGENT_PRIVATE_KEY) {
          const account = privateKeyToAccount(process.env.AGENT_PRIVATE_KEY as any);
          signer = {
            walletAddress: account.address,
            async signLeg(resourceUrl: string) {
              const resp = await fetch(resourceUrl);
              if (resp.status !== 402) {
                throw new Error(`Expected x402 402 challenge, got ${resp.status}: ${await resp.text()}`);
              }
              const requiredHeader = resp.headers.get("PAYMENT-REQUIRED") || resp.headers.get("payment-required");
              if (!requiredHeader) {
                throw new Error("Arc Gateway did not return PAYMENT-REQUIRED header.");
              }
              const challenge = JSON.parse(Buffer.from(requiredHeader, "base64").toString("utf8"));
              const accepted = challenge.accepts[0];

              const now = Math.floor(Date.now() / 1000);
              const validAfter = now - 600;
              const validBefore = now + Math.max(Number(accepted.maxTimeoutSeconds || 0), 7 * 24 * 3600 + 600);
              const crypto = await import("node:crypto");
              const nonce = "0x" + Array.from(crypto.randomBytes(32)).map((b: any) => b.toString(16).padStart(2, "0")).join("");

              const typedData = {
                types: {
                  EIP712Domain: [
                    { name: "name", type: "string" },
                    { name: "version", type: "string" },
                    { name: "chainId", type: "uint256" },
                    { name: "verifyingContract", type: "address" },
                  ],
                  TransferWithAuthorization: [
                    { name: "from", type: "address" },
                    { name: "to", type: "address" },
                    { name: "value", type: "uint256" },
                    { name: "validAfter", type: "uint256" },
                    { name: "validBefore", type: "uint256" },
                    { name: "nonce", type: "bytes32" },
                  ],
                },
                primaryType: "TransferWithAuthorization" as const,
                domain: {
                  name: "GatewayWalletBatched",
                  version: "1",
                  chainId: 5042002,
                  verifyingContract: accepted.extra.verifyingContract,
                },
                message: {
                  from: account.address,
                  to: accepted.payTo,
                  value: BigInt(accepted.amount),
                  validAfter: BigInt(validAfter),
                  validBefore: BigInt(validBefore),
                  nonce,
                },
              };

              const signature = await account.signTypedData(typedData as any);
              return {
                paymentHeader: Buffer.from(JSON.stringify({
                  x402Version: 2,
                  payload: {
                    signature,
                    authorization: {
                      from: account.address,
                      to: accepted.payTo,
                      value: accepted.amount,
                      validAfter: String(validAfter),
                      validBefore: String(validBefore),
                      nonce,
                    },
                  },
                  accepted,
                  resource: challenge.resource,
                })).toString("base64")
              };
            }
          };
        } else {
          signer = createCircleAgentWalletSigner({
            address: process.env.AGENT_WALLET_ADDRESS || "0x4859d0d0babdcc8c4d8d2d116258fd0e5f7ff67d",
            chain: "ARC-TESTNET"
          });
        }

        // const signer = createCircleAgentWalletSigner({
        //   address: process.env.AGENT_WALLET_ADDRESS || "0x4859d0d0babdcc8c4d8d2d116258fd0e5f7ff67d",
        //     chain: "ARC-TESTNET"
        //   });
        const agent = new QmaAgent({ signer, apiUrl: API_BASE_URL });

        async function ensureAgentGatewayBalance(requiredBudget: number) {
          if (!agentWalletAddress || !agentWalletId) return;

          let gwBalance = 0;
          try {
            const gwBalRes = await fetch(`${ARC_GATEWAY_URL.replace(/\/$/, "")}/api/balance/${agentWalletAddress}`);
            if (gwBalRes.ok) {
              const gwData = await gwBalRes.json();
              const candidates = [
                gwData?.balance,
                gwData?.available,
                gwData?.amount,
                gwData?.total,
                gwData?.balances?.[0]?.amount,
                gwData?.balances?.[0]?.balance,
                gwData?.sources?.[0]?.amount,
                gwData?.sources?.[0]?.balance,
                gwData?.data?.balance,
                gwData?.data?.available,
                gwData?.data?.amount,
                gwData?.data?.total,
                gwData?.data?.balances?.[0]?.amount,
                gwData?.data?.balances?.[0]?.balance,
              ];
              for (const candidate of candidates) {
                if (candidate === undefined || candidate === null) continue;
                const raw = Number(candidate);
                if (!Number.isFinite(raw)) continue;
                gwBalance = raw > 1000 ? raw / 1_000_000 : raw;
                break;
              }
            }
          } catch (e) {
            console.error("[Worker] Error checking Gateway balance:", e);
          }

          console.log(`[Worker] Wallet ${agentWalletAddress} Gateway balance: ${gwBalance} USDC (required: ${requiredBudget} USDC)`);

          if (gwBalance >= requiredBudget) {
            return;
          }

          let onChainUsdc = 0;
          try {
            const balRes = await fetch(`${ARC_GATEWAY_URL.replace(/\/$/, "")}/api/wallet/${agentWalletId}/balance`);
            if (balRes.ok) {
              const bdata = await balRes.json();
              const tokenBalances = bdata.tokenBalances || [];
              for (const tb of tokenBalances) {
                if (tb?.token?.symbol === "USDC") {
                  onChainUsdc = parseFloat(tb.amount || "0");
                  break;
                }
              }
            }
          } catch (e) {
            console.error("[Worker] Error checking on-chain balance:", e);
          }

          console.log(`[Worker] Wallet ${agentWalletAddress} on-chain USDC balance: ${onChainUsdc} USDC`);

          const requiredTopUp = Math.max(requiredBudget - gwBalance, 0);
          if (onChainUsdc < requiredTopUp) {
            throw new Error(`Insufficient funds. Agent Wallet has ${onChainUsdc} USDC on-chain, but needs ${requiredTopUp} USDC more to satisfy Gateway budget.`);
          }

          console.log(`[Worker] Automatically depositing ${requiredTopUp.toFixed(6)} USDC from Agent Wallet into Gateway...`);
          const headers: Record<string, string> = { "Content-Type": "application/json" };
          if (INTERNAL_SECRET) {
            headers["x-qma-internal-secret"] = INTERNAL_SECRET;
          }
          const depRes = await fetch(`${ARC_GATEWAY_URL.replace(/\/$/, "")}/api/wallet/deposit`, {
            method: "POST",
            headers,
            body: JSON.stringify({
              walletId: agentWalletId,
              amountUsdc: requiredTopUp.toFixed(6)
            })
          });

          if (!depRes.ok) {
            throw new Error(`Gateway auto-deposit failed: ${await depRes.text()}`);
          }

          console.log("[Worker] Gateway deposit transaction submitted. Waiting for Gateway balance to update...");
          for (let i = 0; i < 20; i++) {
            await new Promise(resolve => setTimeout(resolve, 3000));
            try {
              const checkRes = await fetch(`${ARC_GATEWAY_URL.replace(/\/$/, "")}/api/balance/${agentWalletAddress}`);
              if (checkRes.ok) {
                const checkData = await checkRes.json();
                let currentGwBal = 0;
                const candidates = [
                  checkData?.balance,
                  checkData?.available,
                  checkData?.amount,
                  checkData?.total,
                  checkData?.balances?.[0]?.amount,
                  checkData?.balances?.[0]?.balance,
                ];
                for (const candidate of candidates) {
                  if (candidate === undefined || candidate === null) continue;
                  const raw = Number(candidate);
                  if (!Number.isFinite(raw)) continue;
                  currentGwBal = raw > 1000 ? raw / 1_000_000 : raw;
                  break;
                }
                if (currentGwBal >= requiredBudget) {
                  console.log(`[Worker] Gateway balance updated successfully: ${currentGwBal} USDC`);
                  return;
                }
              }
            } catch (e) { /* ignore */ }
          }
          throw new Error("Timeout waiting for Gateway balance to settle after deposit.");
        }

        async function pushEvent(sessionId: string, eventType: string, payload: any) {
          try {
            const res = await fetch(`${API_BASE_URL}/api/v1/sessions/${sessionId}/events`, {
              method: "POST",
              headers: sessionHeaders(true),
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
              const res = await fetch(`${API_BASE_URL}/api/v1/sessions/${session.id}`, {
                headers: sessionHeaders(),
              });
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

            // Auto-deposit on-chain USDC to Gateway prepaid balance if needed
            await ensureAgentGatewayBalance(session.budget_usdc);

            // Support resume: if session.runtime_state exists, pass it as initialState
            await agent.run({
              task: session.task,
              sessionBudgetUsdc: session.budget_usdc,
              maxPricePerReportUsdc: Math.min(5, session.budget_usdc), // prevent policy error
              maxPurchases: parsedMaxPurchases,
              pollIntervalSeconds: 5, // Check/buy every 5s instead of default 60s
              executionMode: "live",
              initialState: session.runtime_state || undefined
            }, ac.signal);
          } finally {
            clearInterval(statusCheckInterval);
          }

          console.log(`[Worker] Session ${session.id} finished.`);
          // Mark as completed, failed or stopped
          const finalStatus = ac.signal.aborted ? "stopped" : (agent.getState()?.status || "completed");
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

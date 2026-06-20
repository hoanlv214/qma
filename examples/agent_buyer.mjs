#!/usr/bin/env node
/**
 * QMA autonomous buyer agent demo.
 *
 * Dry-run mode is the default and is safe for demos:
 *   node examples/agent_buyer.mjs --dry-run
 *
 * Live payment mode requires a funded Arc Testnet private key with Circle
 * Gateway balance already deposited:
 *   AGENT_PRIVATE_KEY=0x... node examples/agent_buyer.mjs --live --tier preview
 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { createPublicClient, createWalletClient, http } from "viem";
import { privateKeyToAccount } from "viem/accounts";

const DEFAULT_API = "https://qma-api.onrender.com";
const ARC_CHAIN_ID = 5042002;
const ARC_TESTNET_CHAIN = {
  id: ARC_CHAIN_ID,
  name: "Arc Testnet",
  nativeCurrency: { name: "USDC", symbol: "USDC", decimals: 18 },
  rpcUrls: {
    default: { http: [process.env.ARC_TESTNET_RPC || "https://rpc.testnet.arc.network"] },
  },
  blockExplorers: {
    default: { name: "Arcscan", url: "https://testnet.arcscan.app" },
  },
};

function loadLocalEnv() {
  const candidates = [
    path.resolve(process.cwd(), ".env"),
    path.resolve(process.cwd(), "..", ".env"),
  ];
  const envPath = candidates.find((candidate) => fs.existsSync(candidate));
  if (!envPath) return;
  for (const rawLine of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const [key, ...rest] = line.split("=");
    const cleanKey = key.trim();
    if (!cleanKey || process.env[cleanKey]) continue;
    process.env[cleanKey] = rest.join("=").trim().replace(/^['"]|['"]$/g, "");
  }
}

loadLocalEnv();

function argValue(name, fallback = null) {
  const prefixed = `--${name}=`;
  const hit = process.argv.find((arg) => arg.startsWith(prefixed));
  if (hit) return hit.slice(prefixed.length);
  const index = process.argv.indexOf(`--${name}`);
  if (index >= 0 && process.argv[index + 1]) return process.argv[index + 1];
  return fallback;
}

function hasFlag(name) {
  return process.argv.includes(`--${name}`);
}

function apiUrl(path) {
  return `${CONFIG.apiUrl}${path}`;
}

function b64encode(obj) {
  return Buffer.from(JSON.stringify(obj), "utf8").toString("base64");
}

function b64decode(value) {
  return JSON.parse(Buffer.from(value, "base64").toString("utf8"));
}

function randomNonceHex() {
  return `0x${crypto.randomBytes(32).toString("hex")}`;
}

function normalizeTier(tier) {
  return tier === "full" ? "full" : "preview";
}

function short(value) {
  const text = String(value || "");
  return text.length > 14 ? `${text.slice(0, 8)}...${text.slice(-6)}` : text;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function gatewayBaseFromInvoice(invoice) {
  return new URL(invoice.arc_gateway_url).origin;
}

function extractGatewayBalanceUsdc(data) {
  const candidates = [
    data?.balance,
    data?.available,
    data?.amount,
    data?.balances?.[0]?.amount,
    data?.balances?.[0]?.balance,
    data?.sources?.[0]?.amount,
    data?.sources?.[0]?.balance,
    data?.data?.balances?.[0]?.amount,
  ];
  for (const candidate of candidates) {
    if (candidate === undefined || candidate === null) continue;
    const raw = Number(candidate);
    if (!Number.isFinite(raw)) continue;
    return raw > 1000 ? raw / 1_000_000 : raw;
  }
  return null;
}

async function request(path, options = {}) {
  const resp = await fetch(apiUrl(path), options);
  const text = await resp.text();
  const data = text ? JSON.parse(text) : {};
  if (!resp.ok) {
    throw new Error(`${path} returned ${resp.status}: ${JSON.stringify(data)}`);
  }
  return data;
}

async function gatewayRequest(invoice, path) {
  const base = gatewayBaseFromInvoice(invoice);
  const resp = await fetch(`${base}${path}`);
  const text = await resp.text();
  const data = text ? JSON.parse(text) : {};
  if (!resp.ok) {
    throw new Error(`${path} returned ${resp.status}: ${JSON.stringify(data)}`);
  }
  return data;
}

async function checkGatewayBalance(invoice, address) {
  const data = await gatewayRequest(invoice, `/api/balance/${address}`);
  return extractGatewayBalanceUsdc(data);
}

async function getWalletStatus(invoice, address) {
  return gatewayRequest(invoice, `/api/wallet-status/${address}`);
}

function normalizeTx(tx) {
  return {
    to: tx.to,
    data: tx.data,
    gas: tx.gas ? BigInt(tx.gas) : undefined,
  };
}

async function sendAndWait(walletClient, publicClient, tx, label) {
  const hash = await walletClient.sendTransaction(normalizeTx(tx));
  console.log(`${label} tx: ${short(hash)}`);
  const receipt = await publicClient.waitForTransactionReceipt({ hash, timeout: 120_000 });
  if (receipt.status !== "success") {
    throw new Error(`${label} transaction failed: ${hash}`);
  }
  return hash;
}

async function waitForGatewayBalance(invoice, address, requiredAmount) {
  let latest = null;
  for (let i = 0; i < 45; i += 1) {
    latest = await checkGatewayBalance(invoice, address);
    if (latest !== null && latest + 1e-9 >= requiredAmount) return latest;
    await sleep(2000);
  }
  return latest;
}

async function ensureGatewayBalance(invoice, account) {
  const requiredAmount = Number(invoice.amount);
  const gatewayBalance = await checkGatewayBalance(invoice, account.address);
  const walletStatus = await getWalletStatus(invoice, account.address);
  const onChainUsdc = Number(walletStatus?.usdc?.formatted || 0);
  const allowance = Number(walletStatus?.allowance?.formatted || 0);

  console.log(`Gateway balance: ${(gatewayBalance ?? 0).toFixed(6)} USDC`);
  console.log(`Wallet USDC: ${onChainUsdc.toFixed(6)} | Allowance: ${allowance.toFixed(6)} USDC`);

  if (gatewayBalance !== null && gatewayBalance + 1e-9 >= requiredAmount) {
    return gatewayBalance;
  }

  if (!CONFIG.autoDeposit) {
    throw new Error(`Gateway balance is insufficient. Need ${requiredAmount} USDC. Re-run with --auto-deposit or deposit via the web UI first.`);
  }

  const requiredTopUp = Math.max(requiredAmount - (gatewayBalance || 0), 0);
  const depositAmount = Math.max(CONFIG.depositUsdc, requiredTopUp);
  if (onChainUsdc + 1e-9 < depositAmount) {
    throw new Error(`Wallet has ${onChainUsdc.toFixed(6)} USDC, but auto-deposit needs ${depositAmount.toFixed(6)} USDC.`);
  }

  console.log(`Auto-depositing ${depositAmount.toFixed(6)} USDC to Circle Gateway...`);
  const calldata = await gatewayRequest(
    invoice,
    `/api/deposit-calldata/${account.address}?amount=${depositAmount.toFixed(6)}&approveAmount=${CONFIG.approveUsdc.toFixed(6)}`
  );

  const publicClient = createPublicClient({
    chain: ARC_TESTNET_CHAIN,
    transport: http(CONFIG.rpcUrl),
  });
  const walletClient = createWalletClient({
    account,
    chain: ARC_TESTNET_CHAIN,
    transport: http(CONFIG.rpcUrl),
  });

  if (allowance + 1e-9 < depositAmount) {
    await sendAndWait(walletClient, publicClient, calldata.approveTx, "Approve USDC");
  } else {
    console.log("Approval skipped: allowance is already enough.");
  }

  await sendAndWait(walletClient, publicClient, calldata.depositTx, "Gateway deposit");
  console.log("Waiting for Circle Gateway balance to update...");
  const refreshed = await waitForGatewayBalance(invoice, account.address, requiredAmount);
  if (refreshed === null || refreshed + 1e-9 < requiredAmount) {
    throw new Error(`Deposit confirmed, but Gateway balance is still ${refreshed ?? "unavailable"} USDC. Wait a bit and retry.`);
  }
  console.log(`Gateway balance ready: ${refreshed.toFixed(6)} USDC`);
  return refreshed;
}

async function chooseRecommendation() {
  const data = await request(`/api/v1/agent/recommendations?limit=${CONFIG.limit}`);
  const picks = data.recommendations || [];
  if (!picks.length) throw new Error("QMA returned no recommendations.");

  const requestedSymbol = CONFIG.symbol?.trim().toUpperCase();
  const tier = CONFIG.tier;
  const maxPrice = CONFIG.maxPriceUsdc;
  const budget = CONFIG.budgetUsdc;

  const affordable = picks
    .filter((pick) => !requestedSymbol || pick.symbol === requestedSymbol)
    .map((pick) => ({
      ...pick,
      agent_tier: tier || normalizeTier(pick.suggested_tier),
      agent_price: tier === "full" ? data.pricing.full_usdc : tier === "preview" ? data.pricing.preview_usdc : pick.suggested_price_usdc,
    }))
    .filter((pick) => Number(pick.agent_price) <= maxPrice && Number(pick.agent_price) <= budget)
    .sort((a, b) => Number(b.score) - Number(a.score));

  if (!affordable.length) {
    throw new Error(`No affordable recommendation found for budget=${budget} maxPrice=${maxPrice}.`);
  }
  return { pick: affordable[0], pricing: data.pricing };
}

async function createInvoice(pick) {
  return request("/api/v1/payment/invoice", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...pick.query,
      provider_id: pick.provider_id || "funding_memory",
      buyer_type: "agent",
      tier: pick.agent_tier,
      resource_type: "qma_signal_report",
    }),
  });
}

async function signX402Payment(invoice, account) {
  const challengeResp = await fetch(invoice.arc_gateway_url);
  if (challengeResp.status !== 402) {
    throw new Error(`Expected x402 402 challenge, got ${challengeResp.status}: ${await challengeResp.text()}`);
  }
  const requiredHeader = challengeResp.headers.get("PAYMENT-REQUIRED") || challengeResp.headers.get("payment-required");
  if (!requiredHeader) throw new Error("Arc Gateway did not return PAYMENT-REQUIRED header.");

  const challenge = b64decode(requiredHeader);
  const accepted = challenge.accepts[0];
  const chainId = Number(String(accepted.network).split(":")[1] || ARC_CHAIN_ID);
  const now = Math.floor(Date.now() / 1000);
  const validBefore = String(now + Math.max(Number(accepted.maxTimeoutSeconds || 0), 7 * 24 * 3600 + 600));
  const validAfter = String(now - 600);
  const nonce = randomNonceHex();

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
    primaryType: "TransferWithAuthorization",
    domain: {
      name: "GatewayWalletBatched",
      version: "1",
      chainId,
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

  const signature = await account.signTypedData(typedData);
  return {
    paymentHeader: b64encode({
      x402Version: 2,
      payload: {
        signature,
        authorization: {
          from: account.address,
          to: accepted.payTo,
          value: accepted.amount,
          validAfter,
          validBefore,
          nonce,
        },
      },
      accepted,
      resource: challenge.resource,
    }),
  };
}

async function settlePayment(invoice, paymentHeader) {
  const resp = await fetch(invoice.arc_gateway_url, {
    headers: { "payment-signature": paymentHeader },
  });
  const data = await resp.json().catch(async () => ({ error: await resp.text() }));
  if (!resp.ok) {
    throw new Error(`Arc Gateway settlement failed: ${JSON.stringify(data)}`);
  }
  return data;
}

async function verifyPayment(invoice, settlement, account) {
  return request(`/api/v1/payment/verify?invoice_id=${encodeURIComponent(invoice.invoice_id)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      settlement_id: settlement.settlementId,
      invoice_secret: invoice.invoice_secret,
      payer_address: account.address,
      amount_usdc: Number(settlement.amount_usdc),
    }),
  });
}

async function fetchReport(invoice, verifyData, pick) {
  const endpoint = pick.agent_tier === "preview"
    ? `/api/v1/providers/${encodeURIComponent(invoice.provider_id)}/preview`
    : `/api/v1/providers/${encodeURIComponent(invoice.provider_id)}/full-report`;
  return request(`${endpoint}?invoice_id=${encodeURIComponent(invoice.invoice_id)}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-QMA-Access-Token": verifyData.access_token,
    },
    body: JSON.stringify(pick.query),
  });
}

const CONFIG = {
  apiUrl: String(process.env.QMA_API_URL || argValue("api", DEFAULT_API)).replace(/\/$/, ""),
  privateKey: process.env.AGENT_PRIVATE_KEY || argValue("private-key"),
  budgetUsdc: Number(process.env.AGENT_BUDGET_USDC || argValue("budget", "0.01")),
  maxPriceUsdc: Number(process.env.AGENT_MAX_PRICE_USDC || argValue("max-price", "0.005")),
  depositUsdc: Number(process.env.AGENT_GATEWAY_DEPOSIT_USDC || argValue("deposit", "1")),
  approveUsdc: Number(process.env.AGENT_GATEWAY_APPROVE_USDC || argValue("approve", "10")),
  rpcUrl: process.env.ARC_TESTNET_RPC || argValue("rpc", "https://rpc.testnet.arc.network"),
  tier: argValue("tier") ? normalizeTier(argValue("tier")) : null,
  symbol: argValue("symbol"),
  limit: Number(argValue("limit", "8")),
  live: hasFlag("live"),
  autoDeposit: !hasFlag("no-auto-deposit"),
};

async function main() {
  console.log("QMA autonomous buyer agent");
  console.log(`API: ${CONFIG.apiUrl}`);
  console.log(`Mode: ${CONFIG.live ? "LIVE x402 payment" : "DRY RUN"}`);
  console.log(`Budget: ${CONFIG.budgetUsdc} USDC | Max price: ${CONFIG.maxPriceUsdc} USDC`);

  const { pick } = await chooseRecommendation();
  console.log(`\nAgent pick: ${pick.symbol} score=${pick.score} tier=${pick.agent_tier} price=${pick.agent_price} USDC`);
  console.log(`Reasons: ${(pick.reasons || []).join(" | ") || "n/a"}`);

  const invoice = await createInvoice(pick);
  console.log(`\nInvoice: ${invoice.invoice_id}`);
  console.log(`Provider: ${invoice.provider_id} | Amount: ${invoice.amount} ${invoice.currency}`);
  console.log(`Gateway: ${invoice.arc_gateway_url}`);

  if (!CONFIG.live) {
    console.log("\nDry run complete. The agent selected a report and created an invoice without spending USDC.");
    console.log("Run with --live and AGENT_PRIVATE_KEY=0x... to sign x402 and fetch the paid JSON report.");
    return;
  }

  if (!CONFIG.privateKey) {
    throw new Error("Live mode requires AGENT_PRIVATE_KEY=0x... for a funded test wallet.");
  }

  const account = privateKeyToAccount(CONFIG.privateKey);
  console.log(`\nAgent wallet: ${account.address}`);
  await ensureGatewayBalance(invoice, account);
  const { paymentHeader } = await signX402Payment(invoice, account);
  const settlement = await settlePayment(invoice, paymentHeader);
  console.log(`Settlement: ${settlement.settlementId} (${settlement.status || "received"})`);

  const verifyData = await verifyPayment(invoice, settlement, account);
  console.log(`Verified: ${verifyData.status} tx=${verifyData.transaction_hash ? short(verifyData.transaction_hash) : "batch pending"}`);

  const report = await fetchReport(invoice, verifyData, pick);
  console.log("\nPaid JSON report:");
  console.log(JSON.stringify({
    symbol: report.query_symbol || report.symbol || pick.symbol,
    tier: report.tier || pick.agent_tier,
    provider: report.provider_id,
    regime: report.regime_cluster,
    rough_win_rate: report.rough_win_rate,
    avg_profit: report.avg_profit,
    top_analogs: report.top_analogs || report.analog_symbols,
    invoice: report.invoice,
  }, null, 2));
}

main().catch((err) => {
  console.error(`\nAgent failed: ${err.message}`);
  process.exitCode = 1;
});

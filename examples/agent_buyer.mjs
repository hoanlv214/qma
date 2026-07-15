#!/usr/bin/env node
/**
 * QMA autonomous buyer agent demo.
 *
 * Dry-run mode is the default and is safe for demos:
 *   node examples/agent_buyer.mjs --dry-run
 *   node examples/agent_buyer.mjs --dry-run --wallet 0x...  # checks paid history policy
 *
 * Live payment mode requires a funded Arc Testnet private key with Circle
 * Gateway balance already deposited:
 *   AGENT_PRIVATE_KEY=0x... node examples/agent_buyer.mjs --live --tier preview
 */
import crypto from "node:crypto";
import { spawn } from "node:child_process";
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

function runChildProcess(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, { stdio: "inherit", env: process.env });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (signal) reject(new Error(`Child agent stopped by ${signal}.`));
      else if (code === 0) resolve();
      else reject(new Error(`Payment executor exited with code ${code}.`));
    });
  });
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

function tierPrice(pricing = {}, tier = "preview") {
  const normalized = normalizeTier(tier);
  const keys = normalized === "preview"
    ? ["preview_usdc", "preview_base_usdc"]
    : ["full_usdc", "full_base_usdc"];
  for (const key of keys) {
    if (pricing[key] !== undefined && pricing[key] !== null && Number.isFinite(Number(pricing[key]))) {
      return Number(pricing[key]);
    }
  }
  return null;
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

async function loadWalletEntitlements(address) {
  if (!address) return [];
  try {
    const data = await request(`/api/v1/entitlements/wallet/${address}`);
    return data.entitlements || [];
  } catch (err) {
    console.warn(`Could not load wallet entitlements for ${short(address)}: ${err.message}`);
    return [];
  }
}

function entitlementTier(entry = {}) {
  return normalizeTier(entry.tier || entry.report?.tier || entry.report?.invoice?.tier || "full");
}

function entitlementSymbol(entry = {}) {
  return String(entry.symbol || entry.query?.symbol || entry.report?.query_symbol || entry.report?.query?.symbol || "").trim().toUpperCase();
}

function findSymbolEntitlement(entitlements = [], symbol, tier) {
  const normalizedSymbol = String(symbol || "").trim().toUpperCase();
  const normalizedTier = normalizeTier(tier);
  return entitlements.find((entry) => (
    entitlementSymbol(entry) === normalizedSymbol
    && entitlementTier(entry) === normalizedTier
  )) || null;
}

function recommendationTierPrice(pick = {}, pricing = {}, tier = "preview") {
  const normalizedTier = normalizeTier(tier);
  if (normalizeTier(pick.suggested_tier || "preview") === normalizedTier
    && pick.suggested_price_usdc !== undefined
    && Number.isFinite(Number(pick.suggested_price_usdc))) {
    return Number(pick.suggested_price_usdc);
  }
  return tierPrice(pricing, normalizedTier) ?? Number(pick.suggested_price_usdc || 0);
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

async function chooseRecommendation(entitlements = []) {
  const data = await request(`/api/v1/agent/recommendations?limit=${CONFIG.limit}`);
  const picks = data.recommendations || [];
  if (!picks.length) throw new Error("QMA returned no recommendations.");

  const requestedSymbol = CONFIG.symbol?.trim().toUpperCase();
  const requestedProvider = CONFIG.providerId?.trim();
  const forcedTier = CONFIG.tier;
  const maxPrice = CONFIG.maxPriceUsdc;
  const budget = CONFIG.budgetUsdc;

  const evaluated = picks
    .filter((pick) => !requestedSymbol || String(pick.symbol || "").toUpperCase() === requestedSymbol)
    .filter((pick) => !requestedProvider || String(pick.provider_id || "funding_memory") === requestedProvider)
    .map((pick) => {
      const symbol = String(pick.symbol || pick.query?.symbol || "").toUpperCase();
      const fullEntry = findSymbolEntitlement(entitlements, symbol, "full");
      const previewEntry = findSymbolEntitlement(entitlements, symbol, "preview");
      let agentTier = forcedTier || normalizeTier(pick.suggested_tier);
      const upgradeFromPreview = !forcedTier && agentTier === "preview" && previewEntry && !fullEntry;
      if (upgradeFromPreview) agentTier = "full";
      const agentPrice = recommendationTierPrice(pick, data.pricing || {}, agentTier);
      let skipReason = "";
      if (fullEntry) {
        skipReason = "Full Report already purchased";
      } else if (forcedTier && findSymbolEntitlement(entitlements, symbol, forcedTier)) {
        skipReason = `${forcedTier} already purchased`;
      } else if (!Number.isFinite(Number(agentPrice)) || Number(agentPrice) <= 0) {
        skipReason = "missing price";
      } else if (Number(agentPrice) > budget) {
        skipReason = `over budget (${Number(agentPrice).toFixed(3)} > ${budget.toFixed(3)})`;
      } else if (Number(agentPrice) > maxPrice) {
        skipReason = `over max/report (${Number(agentPrice).toFixed(3)} > ${maxPrice.toFixed(3)})`;
      }
      return {
        ...pick,
        agent_tier: agentTier,
        agent_price: Number(agentPrice),
        agent_upgrade_from_preview: Boolean(upgradeFromPreview),
        agent_skip_reason: skipReason,
        agent_value_density: Number(agentPrice) > 0 ? Number(pick.score || 0) / Number(agentPrice) : 0,
      };
    });

  for (const pick of evaluated.slice(0, 8)) {
    if (pick.agent_skip_reason) {
      console.log(`Skip ${pick.symbol}: ${pick.agent_skip_reason}`);
    } else if (pick.agent_upgrade_from_preview) {
      console.log(`Candidate ${pick.symbol}: preview already paid, evaluating full upgrade at ${pick.agent_price.toFixed(3)} USDC`);
    } else {
      console.log(`Candidate ${pick.symbol}: score=${pick.score} tier=${pick.agent_tier} price=${pick.agent_price.toFixed(3)} USDC`);
    }
  }

  const affordable = evaluated
    .filter((pick) => !pick.agent_skip_reason)
    .sort((a, b) => {
      const upgradeDiff = Number(Boolean(b.agent_upgrade_from_preview)) - Number(Boolean(a.agent_upgrade_from_preview));
      if (upgradeDiff) return upgradeDiff;
      const densityDiff = Number(b.agent_value_density || 0) - Number(a.agent_value_density || 0);
      return densityDiff || Number(b.score || 0) - Number(a.score || 0);
    });

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
      provider_id: CONFIG.providerId || pick.provider_id || "funding_memory",
      buyer_type: "agent",
      tier: pick.agent_tier,
      resource_type: "qma_signal_report",
      synthetic: CONFIG.synthetic,
      agent_label: CONFIG.agentLabel,
      run_source: CONFIG.runSource,
    }),
  });
}

async function signX402Payment(resourceUrl, account) {
  const challengeResp = await fetch(resourceUrl);
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

async function settlePayment(resourceUrl, paymentHeader) {
  const resp = await fetch(resourceUrl, {
    headers: { "payment-signature": paymentHeader },
  });
  const data = await resp.json().catch(async () => ({ error: await resp.text() }));
  if (!resp.ok) {
    throw new Error(`Arc Gateway settlement failed: ${JSON.stringify(data)}`);
  }
  return data;
}

function invoiceSplitLegs(invoice = {}) {
  return Array.isArray(invoice.split_legs) && invoice.split_legs.length
    ? invoice.split_legs
    : Array.isArray(invoice.split?.legs)
      ? invoice.split.legs
      : [];
}

function legResourceUrl(leg = {}) {
  return leg.resource || leg.arc_gateway_url || leg.url;
}

async function paySplitInvoice(invoice, account) {
  const settlements = [];
  const legs = invoiceSplitLegs(invoice);
  if (!legs.length) throw new Error("Split invoice has no split_legs.");

  for (const leg of legs) {
    if (leg.status === "paid" && leg.settlement_id && leg.sidecar_receipt) {
      settlements.push({
        leg_id: leg.leg_id,
        settlement_id: leg.settlement_id,
        pay_to: leg.pay_to,
        amount_raw: String(leg.amount_raw),
        sidecar_receipt: leg.sidecar_receipt,
      });
      continue;
    }
    const resourceUrl = legResourceUrl(leg);
    if (!resourceUrl) throw new Error(`Split leg ${leg.leg_id || leg.role || "unknown"} has no resource URL.`);
    if (String(leg.pay_to || "").toLowerCase() === account.address.toLowerCase()) {
      throw new Error(`Agent wallet is the ${leg.role || leg.leg_id} split recipient. Use a separate buyer wallet.`);
    }

    console.log(`Paying ${leg.role || leg.leg_id} leg: ${leg.amount_usdc} USDC -> ${short(leg.pay_to)}`);
    const { paymentHeader } = await signX402Payment(resourceUrl, account);
    const settlement = await settlePayment(resourceUrl, paymentHeader);
    const settlementId = settlement.settlement_id || settlement.settlementId;
    if (!settlementId || !settlement.sidecar_receipt) {
      throw new Error(`Split leg did not return settlement_id and sidecar_receipt: ${JSON.stringify(settlement)}`);
    }
    console.log(`Settled ${leg.role || leg.leg_id}: ${short(settlementId)} (${settlement.status || "received"})`);
    settlements.push({
      leg_id: settlement.leg_id || leg.leg_id,
      settlement_id: settlementId,
      pay_to: settlement.pay_to || leg.pay_to,
      amount_raw: String(settlement.amount_raw || leg.amount_raw),
      sidecar_receipt: settlement.sidecar_receipt,
    });
  }

  return settlements;
}

async function verifyPayment(invoice, settlement, account) {
  const settlementId = settlement.settlementId || settlement.settlement_id;
  return request(`/api/v1/payment/verify?invoice_id=${encodeURIComponent(invoice.invoice_id)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      settlement_id: settlementId,
      invoice_secret: invoice.invoice_secret,
      payer_address: account.address,
      amount_usdc: Number(settlement.amount_usdc),
    }),
  });
}

async function verifySplitPayment(invoice, splitSettlements, account) {
  return request(`/api/v1/payment/verify?invoice_id=${encodeURIComponent(invoice.invoice_id)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      invoice_secret: invoice.invoice_secret,
      payer_address: account.address,
      split_settlements: splitSettlements,
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
  apiUrl: String(argValue("api") || process.env.QMA_API_URL || DEFAULT_API).replace(/\/$/, ""),
  privateKey: process.env.AGENT_PRIVATE_KEY || process.env.QMA_AGENT_PRIVATE_KEY || argValue("private-key"),
  budgetUsdc: Number(argValue("budget") || process.env.AGENT_BUDGET_USDC || "0.01"),
  maxPriceUsdc: Number(argValue("max-price") || process.env.AGENT_MAX_PRICE_USDC || "0.005"),
  depositUsdc: Number(argValue("deposit") || process.env.AGENT_GATEWAY_DEPOSIT_USDC || "1"),
  approveUsdc: Number(argValue("approve") || process.env.AGENT_GATEWAY_APPROVE_USDC || "10"),
  rpcUrl: argValue("rpc") || process.env.ARC_TESTNET_RPC || "https://rpc.testnet.arc.network",
  policyWallet: process.env.AGENT_WALLET_ADDRESS || process.env.QMA_AGENT_WALLET_ADDRESS || argValue("wallet") || argValue("buyer-wallet"),
  providerId: process.env.PROVIDER_ID || argValue("provider"),
  tier: argValue("tier") ? normalizeTier(argValue("tier")) : null,
  symbol: argValue("symbol"),
  limit: Math.min(25, Math.max(1, Number(process.env.AGENT_RECOMMENDATION_LIMIT || argValue("limit", "8")))),
  live: hasFlag("live"),
  autoDeposit: !hasFlag("no-auto-deposit"),
  synthetic: String(process.env.QMA_SYNTHETIC_RUN || argValue("synthetic", "false")).toLowerCase() === "true",
  agentLabel: process.env.QMA_AGENT_LABEL || argValue("agent-label") || null,
  runSource: process.env.QMA_RUN_SOURCE || argValue("run-source") || null,
};

async function main() {
  console.log("QMA autonomous buyer agent");
  console.log(`API: ${CONFIG.apiUrl}`);
  console.log(`Mode: ${CONFIG.live ? "LIVE x402 payment" : "DRY RUN"}`);
  console.log(`Budget: ${CONFIG.budgetUsdc} USDC | Max price: ${CONFIG.maxPriceUsdc} USDC`);

  let account = null;
  if (CONFIG.privateKey) {
    account = privateKeyToAccount(CONFIG.privateKey);
    console.log(`Agent wallet: ${account.address}`);
  } else if (CONFIG.live) {
    throw new Error("Live mode requires AGENT_PRIVATE_KEY=0x... for a funded test wallet.");
  }

  const policyWallet = account?.address || CONFIG.policyWallet;
  const entitlements = policyWallet ? await loadWalletEntitlements(policyWallet) : [];
  if (policyWallet) {
    console.log(`Loaded ${entitlements.length} paid entitlements for policy checks (${short(policyWallet)}).`);
  } else {
    console.log("No agent wallet loaded; dry-run policy cannot check paid entitlements. Pass --wallet 0x... to test upgrade/skip policy.");
  }

  const { pick } = await chooseRecommendation(entitlements);
  console.log(`\nAgent pick: ${pick.symbol} score=${pick.score} tier=${pick.agent_tier} price=${pick.agent_price} USDC`);
  if (pick.agent_upgrade_from_preview) {
    console.log("Policy: preview was already paid, so the agent is upgrading to full instead of rebuying preview.");
  }
  console.log(`Reasons: ${(pick.reasons || []).join(" | ") || "n/a"}`);

  const invoice = await createInvoice(pick);
  console.log(`\nInvoice: ${invoice.invoice_id}`);
  console.log(`Provider: ${invoice.provider_id} | Amount: ${invoice.amount} ${invoice.currency}`);
  console.log(`Gateway: ${invoice.arc_gateway_url}`);
  if (invoiceSplitLegs(invoice).length) {
    console.log("Split legs:");
    for (const leg of invoiceSplitLegs(invoice)) {
      console.log(`- ${leg.role || leg.leg_id}: ${leg.amount_usdc} USDC -> ${short(leg.pay_to)}`);
    }
  }

  if (!CONFIG.live) {
    console.log("\nDry run complete. The agent selected a report and created an invoice without spending USDC.");
    console.log("Run with --live and AGENT_PRIVATE_KEY=0x... to sign x402 and fetch the paid JSON report.");
    return;
  }

  console.log(`\nAgent wallet: ${account.address}`);
  await ensureGatewayBalance(invoice, account);
  const splitLegs = invoiceSplitLegs(invoice);
  const verifyData = splitLegs.length
    ? await verifySplitPayment(invoice, await paySplitInvoice(invoice, account), account)
    : await (async () => {
      const { paymentHeader } = await signX402Payment(invoice.arc_gateway_url, account);
      const settlement = await settlePayment(invoice.arc_gateway_url, paymentHeader);
      console.log(`Settlement: ${settlement.settlementId || settlement.settlement_id} (${settlement.status || "received"})`);
      return verifyPayment(invoice, settlement, account);
    })();
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

async function requestBackendDecision(prompt, wallet) {
  const response = await fetch(`${CONFIG.apiUrl}/api/v1/agent/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      wallet,
      budget_usdc: CONFIG.budgetUsdc,
      max_price_usdc: CONFIG.maxPriceUsdc,
      limit: CONFIG.limit,
    }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`Agent decision API returned HTTP ${response.status}: ${data.detail || "unknown error"}`);
  return data;
}

function cliUsdc(value) {
  return Number(value || 0).toFixed(6);
}

function printAgentDecision(result, prompt) {
  const plan = result.plan;
  const resolved = result.resolved_candidate;
  if (hasFlag("json")) {
    console.log(JSON.stringify(result));
    return;
  }
  if (hasFlag("quiet")) {
    console.log(resolved
      ? `Selected ${resolved.symbol} at ${cliUsdc(resolved.price_usdc)} USDC\nDry run complete`
      : `No candidate selected\nDry run complete`);
    return;
  }

  console.log("\nQMA LLM plan validated");
  console.log(`Goal: ${prompt}`);
  console.log(`Candidates evaluated: ${result.candidate_count}`);
  if (resolved) {
    console.log(`\nSelected: ${resolved.symbol}`);
    console.log(`Provider: ${resolved.provider_id}`);
    console.log(`Tier: ${resolved.tier}`);
    console.log(`Score: ${Number(resolved.score).toFixed(1)}`);
    console.log(`Validated price: ${cliUsdc(resolved.price_usdc)} USDC`);
    console.log(`Max price: ${cliUsdc(plan.max_price_usdc)} USDC`);
    console.log(`Budget remaining: ${cliUsdc(Number(plan.budget_usdc) - Number(resolved.price_usdc))} USDC`);
    console.log(`\nReason:\n${plan.reason}`);
  } else {
    console.log(`\nAction: ${plan.action}`);
    console.log(`Reason:\n${plan.reason}`);
  }
  if (result.rejected_candidates?.length) {
    console.log("\nRejected:");
    result.rejected_candidates.slice(0, 3).forEach((item) => {
      console.log(`- ${item.candidate_id}: ${item.reason_code}`);
    });
  }
  if (hasFlag("verbose")) {
    console.log("\nPolicy checks:");
    Object.entries(result.policy_check || {}).forEach(([key, value]) => console.log(`- ${key}: ${value}`));
    console.log("\nCandidates:");
    (result.evaluated_candidates || []).forEach((item, index) => {
      console.log(`${index + 1}. ${item.symbol} | ${item.provider_id} | ${item.tier} | score=${Number(item.score).toFixed(1)} | price=${cliUsdc(item.price_usdc)} | ${item.status}`);
    });
    if (result.canonical_query) {
      console.log("\nCanonical query:");
      console.log(JSON.stringify(result.canonical_query, null, 2));
    }
  }
  console.log(`\nMode: ${CONFIG.live ? "Live executor" : "Dry run"}`);
  console.log(CONFIG.live ? "Payment executor will use the canonical resolved candidate." : "No invoice created. No USDC spent.");
}

async function runLlmMode() {
  const prompt = argValue("prompt", process.env.AGENT_PROMPT || "Find the best affordable report opportunity.");
  const planningWallet = CONFIG.privateKey
    ? privateKeyToAccount(CONFIG.privateKey).address
    : CONFIG.policyWallet || undefined;
  let result;

  if (!hasFlag("local-llm")) {
    const serverDecision = await requestBackendDecision(prompt, planningWallet);
    result = serverDecision;
  } else {
    const { QmaClient, OpenAiDecisionGenerator, executeDryRun, planWithLlm } = await import("../agents/dist/index.js");
    const context = await new QmaClient(CONFIG.apiUrl).loadDecisionContext({
      prompt,
      budgetUsdc: CONFIG.budgetUsdc,
      maxPriceUsdc: CONFIG.maxPriceUsdc,
      wallet: planningWallet,
      limit: CONFIG.limit,
    });
    const localPlan = await planWithLlm(new OpenAiDecisionGenerator(), context);
    const dryRun = executeDryRun(localPlan, context);
    const publicPlan = {
      action: localPlan.action,
      candidate_id: localPlan.candidateId,
      requested_tier: localPlan.requestedTier,
      budget_usdc: localPlan.budgetUsdc,
      max_price_usdc: localPlan.maxPriceUsdc,
      reason: localPlan.reason,
      rejected_candidate_ids: localPlan.rejectedCandidateIds,
    };
    result = {
      plan: publicPlan,
      validation: dryRun.validation,
      resolved_candidate: dryRun.validation.candidate ? {
        candidate_id: dryRun.validation.candidate.candidateId,
        provider_id: dryRun.validation.candidate.providerId,
        symbol: dryRun.validation.candidate.symbol,
        tier: localPlan.requestedTier === "auto" ? dryRun.validation.candidate.suggestedTier : localPlan.requestedTier,
        score: dryRun.validation.candidate.score,
        price_usdc: dryRun.validation.priceUsdc || 0,
        value_density: dryRun.validation.priceUsdc ? dryRun.validation.candidate.score / dryRun.validation.priceUsdc : 0,
      } : null,
      policy_check: {},
      rejected_candidates: localPlan.rejectedCandidateIds.map((candidateId) => ({ candidate_id: candidateId, reason_code: "POLICY_REJECTED", reason: "Model-suggested rejection; canonical reason unavailable in local mode." })),
      evaluated_candidates: [],
      candidate_count: context.candidates.length,
      decision_source: "llm",
    };
  }

  if (!result.validation.valid) {
    if (hasFlag("json")) {
      console.log(JSON.stringify(result));
    } else {
      console.error("\nLLM plan rejected");
      result.validation.errors.forEach((error) => console.error(`- ${error}`));
      console.error("No invoice created. No USDC spent.");
    }
    return;
  }
  if (hasFlag("json") && CONFIG.live) {
    throw new Error("--json is supported for dry-run output only; omit --json for live execution.");
  }
  printAgentDecision(result, prompt);
  const plan = result.plan;
  const resolved = result.resolved_candidate;
  if (plan.action !== "purchase" || !resolved) {
    return;
  }
  if (!CONFIG.live) {
    console.log("LLM dry-run complete. No invoice was created and no USDC was spent.");
    return;
  }

  // Transitional bridge: the validated LLM decision constrains the existing
  // QMA split-payment executor, which refreshes recommendations before paying.
  // Circle Agent Wallet signing is not silently substituted here.
  const childArgs = [
    process.argv[1],
    "--no-llm",
    "--live",
    "--symbol", resolved.symbol,
    "--provider", resolved.provider_id,
    "--tier", resolved.tier,
    "--budget", String(plan.budget_usdc),
    "--max-price", String(plan.max_price_usdc),
    "--api", CONFIG.apiUrl,
  ];
  if (hasFlag("auto-deposit")) childArgs.push("--auto-deposit");
  else childArgs.push("--no-auto-deposit");
  await runChildProcess(childArgs);
}

const entrypoint = hasFlag("llm") && !hasFlag("no-llm") ? runLlmMode : main;
entrypoint().catch((err) => {
  console.error(`\nAgent failed: ${err.message}`);
  process.exitCode = 1;
});

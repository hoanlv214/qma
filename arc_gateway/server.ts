import express from "express";
import { createGatewayMiddleware } from "@circle-fin/x402-batching/server";
import {
  createPublicClient,
  encodeFunctionData,
  erc20Abi,
  formatUnits,
  http,
  parseAbi,
  parseUnits,
} from "viem";
import { decodeBatch } from "./decode-batch.ts";
import fs from "node:fs";
import path from "node:path";

type PaidRequest = express.Request & {
  payment?: {
    verified: boolean;
    payer: string;
    amount: string;
    network: string;
    transaction?: string;
  };
};

function loadLocalEnv() {
  const envPath = path.resolve(process.cwd(), "..", ".env");
  if (!fs.existsSync(envPath)) return;
  for (const rawLine of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const [key, ...rest] = line.split("=");
    if (!process.env[key.trim()]) {
      process.env[key.trim()] = rest.join("=").trim().replace(/^['"]|['"]$/g, "");
    }
  }
}

loadLocalEnv();

const PORT = Number(process.env.PORT ?? process.env.QMA_ARC_GATEWAY_PORT ?? "3000");
const SELLER =
  process.env.QMA_ARC_SELLER_ADDRESS ??
  "0x933a2405f84c224be1ef373ba16e992e1f459682";
const AMOUNT = process.env.QMA_ARC_AMOUNT ?? "$0.005";
const DEFAULT_DEPOSIT_USDC = process.env.QMA_ARC_DEFAULT_DEPOSIT_USDC ?? "1.00";
const DEFAULT_APPROVE_USDC = process.env.QMA_ARC_APPROVE_USDC ?? "10.00";
const GATEWAY_API =
  process.env.GATEWAY_API ??
  process.env.QMA_CIRCLE_GATEWAY_API ??
  "https://gateway-api-testnet.circle.com";
const ARC_EXPLORER =
  process.env.ARC_EXPLORER ??
  process.env.QMA_ARC_EXPLORER ??
  "https://testnet.arcscan.app";
const BALANCES_URL = `${GATEWAY_API}/v1/balances`;
const GATEWAY_WALLET =
  process.env.GATEWAY_WALLET ??
  "0x0077777d7EBA4688BDeF3E311b846F25870A19B9";
const NETWORK = "eip155:5042002";
const ARC_DOMAIN = 26;
const ARC_TESTNET_USDC =
  "0x3600000000000000000000000000000000000000" as `0x${string}`;
const GATEWAY_WALLET_ADDRESS = GATEWAY_WALLET as `0x${string}`;
const publicClient = createPublicClient({
  transport: http(process.env.ARC_TESTNET_RPC ?? "https://rpc.testnet.arc.network"),
});
const GATEWAY_WALLET_ABI = parseAbi([
  "function deposit(address token,uint256 amount)",
]);

const app = express();

app.use((req, res, next) => {
  const origin = req.headers.origin ?? "*";
  res.setHeader("Access-Control-Allow-Origin", origin);
  res.setHeader("Vary", "Origin");
  res.setHeader(
    "Access-Control-Allow-Headers",
    "Content-Type, payment-signature",
  );
  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  res.setHeader(
    "Access-Control-Expose-Headers",
    "PAYMENT-REQUIRED, payment-required",
  );
  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }
  next();
});

app.use("/qma-access", (req, res, next) => {
  const originalEnd = res.end.bind(res);
  const chunks: Buffer[] = [];
  res.end = ((chunk?: unknown, encoding?: BufferEncoding | (() => void), cb?: () => void) => {
    if (chunk) {
      chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
    }
    const body = Buffer.concat(chunks).toString("utf8");
    if (res.statusCode >= 400) {
      console.log(
        `qma-access ${res.statusCode} paymentHeader=${Boolean(req.headers["payment-signature"])} body=${body}`,
      );
    }
    return originalEnd(chunk as never, encoding as never, cb);
  }) as typeof res.end;
  next();
});

const gateway = createGatewayMiddleware({
  sellerAddress: SELLER,
  facilitatorUrl: GATEWAY_API,
  networks: [NETWORK],
});

app.get("/health", (_req, res) => {
  res.json({
    status: "ok",
    gateway: "circle-x402-batching",
    network: NETWORK,
    seller: SELLER,
    amount: AMOUNT,
  });
});

function amountForRequest(req: express.Request) {
  const requested = Number(req.query.amount_usdc ?? "");
  if (Number.isFinite(requested) && requested > 0) {
    return `$${requested.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")}`;
  }
  const tier = String(req.query.tier ?? "full").toLowerCase();
  if (tier === "preview") {
    return `$${process.env.QMA_PRICE_PREVIEW_USDC ?? "0.001"}`;
  }
  if (tier === "full") {
    return `$${process.env.QMA_PRICE_FULL_USDC ?? AMOUNT.replace(/^\$/, "")}`;
  }
  return AMOUNT;
}

app.get("/qma-access", (req, res, next) => {
  gateway.require(amountForRequest(req))(req, res, next);
}, (req: PaidRequest, res) => {
  const { payer, amount, network, transaction } = req.payment!;
  const amountUsdc = formatUnits(BigInt(amount), 6);
  const symbol = String(req.query.symbol ?? "UNKNOWN").toUpperCase();
  const tier = String(req.query.tier ?? "full").toLowerCase();
  console.log(
    `QMA paid ${amountUsdc} USDC tier=${tier} by ${payer} on ${network} settlement=${transaction ?? "?"}`,
  );
  res.json({
    status: "paid",
    product: "qma-report",
    symbol,
    tier,
    paid_by: payer,
    amount_raw: amount,
    amount_usdc: amountUsdc,
    network,
    settlementId: transaction,
  });
});

app.get("/api/balance/:address", async (req, res) => {
  try {
    const r = await fetch(BALANCES_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: "USDC",
        sources: [{ domain: ARC_DOMAIN, depositor: req.params.address }],
      }),
    });
    const text = await r.text();
    res.status(r.status).type("application/json").send(text);
  } catch (err) {
    res.status(502).json({ error: String((err as Error).message ?? err) });
  }
});

app.get("/api/deposit-calldata/:address", (req, res) => {
  try {
    const amount = String(req.query.amount ?? DEFAULT_DEPOSIT_USDC);
    const approveAmount = String(req.query.approveAmount ?? DEFAULT_APPROVE_USDC);
    const rawAmount = parseUnits(amount, 6);
    const rawApproveAmount = parseUnits(approveAmount, 6);
    const approveData = encodeFunctionData({
      abi: erc20Abi,
      functionName: "approve",
      args: [GATEWAY_WALLET_ADDRESS, rawApproveAmount],
    });
    const depositData = encodeFunctionData({
      abi: GATEWAY_WALLET_ABI,
      functionName: "deposit",
      args: [ARC_TESTNET_USDC, rawAmount],
    });
    res.json({
      amount,
      rawAmount: rawAmount.toString(),
      approveAmount,
      rawApproveAmount: rawApproveAmount.toString(),
      depositor: req.params.address,
      usdc: ARC_TESTNET_USDC,
      gatewayWallet: GATEWAY_WALLET,
      approveTx: {
        from: req.params.address,
        to: ARC_TESTNET_USDC,
        data: approveData,
      },
      depositTx: {
        from: req.params.address,
        to: GATEWAY_WALLET,
        data: depositData,
        gas: "0x1d4c0",
      },
    });
  } catch (err) {
    res.status(400).json({ error: String((err as Error).message ?? err) });
  }
});

app.get("/api/wallet-status/:address", async (req, res) => {
  try {
    const owner = req.params.address as `0x${string}`;
    const [usdcBalance, allowance] = await Promise.all([
      publicClient.readContract({
        address: ARC_TESTNET_USDC,
        abi: erc20Abi,
        functionName: "balanceOf",
        args: [owner],
      }),
      publicClient.readContract({
        address: ARC_TESTNET_USDC,
        abi: erc20Abi,
        functionName: "allowance",
        args: [owner, GATEWAY_WALLET_ADDRESS],
      }),
    ]);
    res.json({
      address: owner,
      usdc: {
        raw: usdcBalance.toString(),
        formatted: formatUnits(usdcBalance, 6),
      },
      allowance: {
        raw: allowance.toString(),
        formatted: formatUnits(allowance, 6),
      },
      gatewayWallet: GATEWAY_WALLET,
      usdcAddress: ARC_TESTNET_USDC,
      defaultDepositUsdc: DEFAULT_DEPOSIT_USDC,
      defaultApproveUsdc: DEFAULT_APPROVE_USDC,
    });
  } catch (err) {
    res.status(502).json({ error: String((err as Error).message ?? err) });
  }
});

app.get("/api/settlement/:id", async (req, res) => {
  const r = await fetch(`${GATEWAY_API}/v1/x402/transfers/${req.params.id}`);
  res.status(r.status).type("application/json").send(await r.text());
});

app.get("/api/batch-tx/:id", async (req, res) => {
  const sr = await fetch(`${GATEWAY_API}/v1/x402/transfers/${req.params.id}`);
  if (!sr.ok) {
    res.status(sr.status).send(await sr.text());
    return;
  }

  const settlement = (await sr.json()) as {
    status: string;
    updatedAt: string;
  };
  if (settlement.status !== "completed" && settlement.status !== "confirmed") {
    res.json({ batchTx: null, status: settlement.status });
    return;
  }

  const tr = await fetch(
    `${ARC_EXPLORER}/api/v2/addresses/${GATEWAY_WALLET}/transactions?filter=to`,
  );
  const { items } = (await tr.json()) as {
    items: { hash: string; timestamp: string; method: string | null }[];
  };
  const updatedAt = new Date(settlement.updatedAt).getTime();
  const candidate = items.find(
    (t) =>
      t.method === "submitBatch" &&
      new Date(t.timestamp).getTime() <= updatedAt + 5_000,
  );

  res.json({
    batchTx: candidate?.hash ?? null,
    status: settlement.status,
    explorerUrl: candidate ? `${ARC_EXPLORER}/tx/${candidate.hash}` : null,
  });
});

app.get("/api/decode-batch/:hash", async (req, res) => {
  try {
    const decoded = await decodeBatch(req.params.hash as `0x${string}`);
    res.json({
      ...decoded,
      blockNumber: decoded.blockNumber.toString(),
      entries: decoded.entries.map((e) => ({
        address: e.address,
        deltaRaw: e.delta.toString(),
        usdc: e.usdc,
      })),
    });
  } catch (err) {
    res.status(400).json({ error: String((err as Error).message ?? err) });
  }
});

app.listen(PORT, () => {
  console.log(`QMA Arc Gateway listening on http://127.0.0.1:${PORT}`);
  console.log(`seller: ${SELLER}`);
  console.log(`amount: ${AMOUNT}`);
});

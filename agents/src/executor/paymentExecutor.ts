import { spawn } from "node:child_process";
import type { AgentPaymentSigner, PaymentSettlement } from "../wallets/signer.js";

export interface InvoiceSplitLeg {
  leg_id: string;
  role?: string;
  status?: string;
  resource?: string;
  arc_gateway_url?: string;
  pay_to: string;
  amount_raw: string | number;
  amount_usdc?: string | number;
  settlement_id?: string;
  sidecar_receipt?: string;
  payer_address?: string | null;
  gateway_status?: string | null;
}

export interface AgentInvoice {
  invoice_id?: string;
  arc_gateway_url?: string;
  amount?: string | number;
  split_legs?: InvoiceSplitLeg[];
}

export interface SettlementProof extends PaymentSettlement {
  leg_id: string;
  settlement_id: string;
  pay_to: string;
  amount_raw: string;
  amount_usdc?: string | number;
  sidecar_receipt: string;
  payer_address?: string | null;
  gateway_status?: string | null;
}

export interface PaymentExecutionResult {
  settlements: SettlementProof[];
}

export interface PaymentExecutor {
  execute(input: { invoice: AgentInvoice; signer?: AgentPaymentSigner }): Promise<PaymentExecutionResult>;
}

export interface CircleAgentWalletExecutorOptions {
  address: string;
  chain: string;
  runCircle?: CircleCommandRunner;
}

export type CircleCommandRunner = (args: string[]) => Promise<unknown>;

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function rawAmount(value: unknown): string {
  return String(value ?? "").trim();
}

function numberAmount(value: unknown): number {
  const amount = Number(value);
  return Number.isFinite(amount) && amount > 0 ? amount : 0;
}

function sameAddress(left: string, right: string): boolean {
  return left.toLowerCase() === right.toLowerCase();
}

function settlementBody(value: unknown): Record<string, unknown> {
  const root = record(value);
  return record(root.data) && Object.keys(record(root.data)).length ? record(root.data) : root;
}

function resourceUrlForLeg(leg: InvoiceSplitLeg): string {
  const resourceUrl = text(leg.resource) || text(leg.arc_gateway_url);
  if (!resourceUrl) throw new Error(`Split leg ${leg.leg_id} has no x402 resource URL.`);
  return resourceUrl;
}

function invoiceLegs(invoice: AgentInvoice): InvoiceSplitLeg[] {
  if (Array.isArray(invoice.split_legs) && invoice.split_legs.length) return invoice.split_legs;
  const resourceUrl = text(invoice.arc_gateway_url);
  if (!resourceUrl) throw new Error("Invoice has neither split_legs nor arc_gateway_url.");
  const amount = numberAmount(invoice.amount);
  if (!amount) throw new Error("Invoice has no positive amount for its single payment leg.");
  return [{
    leg_id: "single",
    role: "payment",
    resource: resourceUrl,
    pay_to: "",
    amount_raw: "",
    amount_usdc: amount,
  }];
}

function alreadySettled(leg: InvoiceSplitLeg): SettlementProof | null {
  if (leg.status !== "paid") return null;
  const settlementId = text(leg.settlement_id);
  const sidecarReceipt = text(leg.sidecar_receipt);
  if (!settlementId || !sidecarReceipt) {
    throw new Error(`Paid split leg ${leg.leg_id} is missing its settlement proof.`);
  }
  return {
    leg_id: leg.leg_id,
    settlement_id: settlementId,
    pay_to: leg.pay_to,
    amount_raw: rawAmount(leg.amount_raw),
    amount_usdc: leg.amount_usdc,
    sidecar_receipt: sidecarReceipt,
    payer_address: leg.payer_address,
    gateway_status: leg.gateway_status,
  };
}

function normalizeSettlement(leg: InvoiceSplitLeg, value: unknown): SettlementProof {
  const body = settlementBody(value);
  const settlementId = text(body.settlement_id) || text(body.settlementId);
  const sidecarReceipt = text(body.sidecar_receipt);
  if (!settlementId || !sidecarReceipt) {
    throw new Error(`Payment for split leg ${leg.leg_id} returned no settlement_id and sidecar_receipt.`);
  }

  const returnedLegId = text(body.leg_id);
  if (returnedLegId && returnedLegId !== leg.leg_id) {
    throw new Error(`Payment returned leg ${returnedLegId}; expected ${leg.leg_id}.`);
  }

  const returnedPayTo = text(body.pay_to);
  if (returnedPayTo && leg.pay_to && !sameAddress(returnedPayTo, leg.pay_to)) {
    throw new Error(`Payment returned pay_to ${returnedPayTo}; expected ${leg.pay_to}.`);
  }

  const returnedAmount = body.amount_raw;
  if (returnedAmount !== undefined && rawAmount(leg.amount_raw) && rawAmount(returnedAmount) !== rawAmount(leg.amount_raw)) {
    throw new Error(`Payment returned amount_raw ${String(returnedAmount)}; expected ${rawAmount(leg.amount_raw)}.`);
  }
  const returnedAmountUsdc = body.amount_usdc;
  const amountUsdc = typeof returnedAmountUsdc === "string" || typeof returnedAmountUsdc === "number"
    ? returnedAmountUsdc
    : leg.amount_usdc;

  return {
    ...body,
    leg_id: leg.leg_id,
    settlement_id: settlementId,
    pay_to: returnedPayTo || leg.pay_to,
    amount_raw: rawAmount(returnedAmount ?? leg.amount_raw),
    amount_usdc: amountUsdc,
    sidecar_receipt: sidecarReceipt,
    payer_address: text(body.payer) || text(body.payer_address) || null,
    gateway_status: text(body.gateway_status) || text(body.status) || null,
  };
}

async function settleSignedLeg(leg: InvoiceSplitLeg, signer: AgentPaymentSigner): Promise<PaymentSettlement> {
  const signLeg = signer.signLeg;
  if (typeof signLeg !== "function") {
    throw new Error(`No payment authorizer is configured for split leg ${leg.leg_id}.`);
  }
  const signature = await signLeg(resourceUrlForLeg(leg));
  if (!text(signature.paymentHeader)) throw new Error(`Payment signer returned an empty header for ${leg.leg_id}.`);
  const response = await fetch(resourceUrlForLeg(leg), {
    method: "GET",
    headers: { "payment-signature": signature.paymentHeader },
  });
  const bodyText = await response.text();
  let body: unknown = {};
  try {
    body = bodyText ? JSON.parse(bodyText) : {};
  } catch {
    throw new Error(`Payment settlement for ${leg.leg_id} returned non-JSON data.`);
  }
  if (!response.ok) {
    throw new Error(`Payment settlement for ${leg.leg_id} returned HTTP ${response.status}.`);
  }
  return record(body);
}

/**
 * Execute the invoice legs sequentially. A split leg is never retried here:
 * after a transport failure its outcome is unknown and the caller must first
 * reconcile the invoice status. This preserves the `(invoice_id, leg_id)`
 * idempotency boundary and prevents duplicate payment attempts.
 */
export function createPaymentExecutor(defaultSigner?: AgentPaymentSigner): PaymentExecutor {
  return {
    async execute({ invoice, signer }): Promise<PaymentExecutionResult> {
      const activeSigner = signer || defaultSigner;
      if (!activeSigner) throw new Error("No payment authorizer is configured.");
      const settlements: SettlementProof[] = [];
      for (const leg of invoiceLegs(invoice)) {
        const recovered = alreadySettled(leg);
        if (recovered) {
          settlements.push(recovered);
          continue;
        }
        if (activeSigner.walletAddress && leg.pay_to && sameAddress(activeSigner.walletAddress, leg.pay_to)) {
          throw new Error(`Payment wallet is the ${leg.role || leg.leg_id} recipient; refusing self-payment.`);
        }

        const amountUsdc = numberAmount(leg.amount_usdc);
        const rawSettlement = activeSigner.payLeg
          ? await activeSigner.payLeg({ resourceUrl: resourceUrlForLeg(leg), legId: leg.leg_id, amountUsdc })
          : await settleSignedLeg(leg, activeSigner);
        settlements.push(normalizeSettlement(leg, rawSettlement));
      }
      return { settlements };
    },
  };
}

function circleCliBinary(): string {
  return process.platform === "win32" ? "circle.cmd" : "circle";
}

function quoteWindowsArg(value: string): string {
  if (value.includes('"')) throw new Error("Circle CLI argument contains an unsupported quote character.");
  return `"${value}"`;
}

function defaultRunCircle(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const isWindows = process.platform === "win32";
    const child = isWindows
      ? spawn(process.env.ComSpec || "cmd.exe", [
        "/d", "/s", "/c", [circleCliBinary(), ...args.map(quoteWindowsArg)].join(" "),
      ], { windowsVerbatimArguments: true, stdio: ["ignore", "pipe", "pipe"], env: process.env })
      : spawn(circleCliBinary(), args, { stdio: ["ignore", "pipe", "pipe"], env: process.env });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk: Buffer) => { stdout += chunk.toString(); });
    child.stderr.on("data", (chunk: Buffer) => { stderr += chunk.toString(); });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code !== 0) {
        reject(new Error(`Circle CLI failed (${code}): ${(stderr || stdout).trim().slice(0, 500) || "unknown error"}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch {
        reject(new Error(`Circle CLI returned non-JSON output: ${stdout.trim().slice(0, 500)}`));
      }
    });
  });
}

/** Circle Agent Wallet adapter for the shared sequential executor. */
export function createCircleAgentWalletSigner(options: CircleAgentWalletExecutorOptions): AgentPaymentSigner {
  const address = text(options.address);
  const chain = text(options.chain);
  if (!address) throw new Error("Circle Agent Wallet address is required.");
  if (!chain) throw new Error("Circle Agent Wallet chain is required.");
  const runCircle = options.runCircle || defaultRunCircle;

  return {
    walletAddress: address,
    async signLeg(): Promise<never> {
      throw new Error("Circle Agent Wallet payments must use the Circle CLI pay adapter.");
    },
    async payLeg({ resourceUrl, amountUsdc }): Promise<PaymentSettlement> {
      if (!amountUsdc) throw new Error("Circle Agent Wallet payment requires a positive leg amount.");
      const result = await runCircle([
        "services", "pay", resourceUrl,
        "--address", address,
        "--chain", chain,
        "--max-amount", String(amountUsdc),
        "--output", "json",
        "--quiet",
      ]);
      return settlementBody(result);
    },
  };
}

export function createCircleAgentWalletExecutor(options: CircleAgentWalletExecutorOptions): PaymentExecutor {
  const signer = createCircleAgentWalletSigner(options);
  return createPaymentExecutor(signer);
}

export interface PaymentSignature {
  paymentHeader: string;
  settlementHint?: string;
}

export interface AgentPaymentSigner {
  signLeg(resourceUrl: string): Promise<PaymentSignature>;
}

export type WalletMode = "dry-run" | "browser" | "circle-agent-wallet";

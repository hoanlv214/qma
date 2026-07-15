import type { AgentPaymentSigner } from "../wallets/signer.js";

export interface PaymentExecutor {
  execute(input: { invoice: unknown; signer: AgentPaymentSigner }): Promise<unknown>;
}

/**
 * Placeholder boundary. Live QMA split payment is deliberately not wired here
 * until the Circle Agent Wallet signer contract is proven against both legs.
 */
export function createUnwiredPaymentExecutor(): PaymentExecutor {
  return {
    async execute(): Promise<never> {
      throw new Error("Live payment executor is not enabled in agents yet.");
    },
  };
}

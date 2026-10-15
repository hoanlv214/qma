import { AppKit } from "@circle-fin/app-kit";
import { createViemAdapterFromPrivateKey } from "@circle-fin/adapter-viem-v2";

export interface AppKitBridgeParams {
  privateKey: `0x${string}`;
  fromChain: "Base_Sepolia" | "Arbitrum_Sepolia" | "Ethereum_Sepolia" | "Polygon_Amoy";
  toChain?: "Arc_Testnet";
  amountUsdc: string;
}

export interface AppKitBridgeResult {
  success: boolean;
  txHash?: string;
  amount?: string;
  state?: string;
  error?: string;
}

export class CircleAppKitManager {
  private readonly kit: AppKit;

  constructor() {
    this.kit = new AppKit();
  }

  /**
   * Get supported chains for cross-chain stablecoin actions.
   */
  getSupportedChains(action: "bridge" | "swap" | "earn" | "unifiedBalance" = "bridge") {
    if (action === "bridge") {
      return this.kit.getSupportedChains("bridge");
    }
    return this.kit.getSupportedChains(action);
  }

  /**
   * Estimate CCTP bridge fee and timing.
   */
  async estimateBridge({
    fromChain,
    toChain = "Arc_Testnet",
    amountUsdc,
  }: {
    fromChain: string;
    toChain?: string;
    amountUsdc: string;
  }) {
    try {
      const kitWithEstimate = this.kit as unknown as {
        estimateBridge?: (args: Record<string, unknown>) => Promise<unknown>;
      };
      const estimate = await kitWithEstimate.estimateBridge?.({
        from: fromChain,
        to: toChain,
        amount: amountUsdc,
        token: "USDC",
      });
      return { success: true, estimate };
    } catch (err: unknown) {
      return { success: false, error: err instanceof Error ? err.message : "Estimation failed." };
    }
  }

  /**
   * Execute CCTP Crosschain Bridge to Arc Testnet.
   */
  async bridgeToArc({
    privateKey,
    fromChain,
    toChain = "Arc_Testnet",
    amountUsdc,
  }: AppKitBridgeParams): Promise<AppKitBridgeResult> {
    try {
      const adapter = createViemAdapterFromPrivateKey({
        privateKey,
      });

      type BridgeInput = Parameters<AppKit["bridge"]>[0];
      const result = await this.kit.bridge({
        from: {
          chain: fromChain as unknown as BridgeInput["from"]["chain"],
          adapter,
        },
        to: {
          chain: toChain as unknown as BridgeInput["to"]["chain"],
          adapter,
        },
        amount: amountUsdc,
        token: "USDC",
        config: {
          transferSpeed: "FAST" as unknown as NonNullable<BridgeInput["config"]>["transferSpeed"],
        },
      });

      const bridgeResult = result as unknown as {
        amount?: string;
        state?: string;
        destination?: { txHash?: string };
        source?: { txHash?: string };
      };

      return {
        success: true,
        amount: bridgeResult?.amount,
        state: bridgeResult?.state,
        txHash: bridgeResult?.destination?.txHash || bridgeResult?.source?.txHash,
      };
    } catch (err: unknown) {
      return {
        success: false,
        error: err instanceof Error ? err.message : "Bridge execution failed.",
      };
    }
  }
}

export const circleAppKitManager = new CircleAppKitManager();

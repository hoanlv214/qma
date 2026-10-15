import { createAppKit } from "@reown/appkit/react";
import { defineChain, type AppKitNetwork } from "@reown/appkit/networks";
import { WagmiAdapter } from "@reown/appkit-adapter-wagmi";
import { ARC_CHAIN } from "./network";
import { registerAppKitProviderSource, type Eip1193Provider } from "../services/wallet";

export const arcTestnetChain: AppKitNetwork = defineChain({
  id: ARC_CHAIN.chainId,
  name: ARC_CHAIN.name,
  chainNamespace: "eip155",
  caipNetworkId: `eip155:${ARC_CHAIN.chainId}`,
  nativeCurrency: {
    name: "USDC",
    symbol: "USDC",
    decimals: 18,
  },
  rpcUrls: {
    default: {
      http: [ARC_CHAIN.rpcUrl],
    },
  },
  blockExplorers: {
    default: {
      name: ARC_CHAIN.name,
      url: ARC_CHAIN.explorerUrl,
    },
  },
});

import { appConfig } from "./app";

// 1. Get projectId from env or use centralized config
export const projectId =
  (import.meta.env.VITE_WALLETCONNECT_PROJECT_ID as string) ||
  appConfig.walletConnect.projectId;

// 2. Initialize WagmiAdapter
export const wagmiAdapter = new WagmiAdapter({
  networks: [arcTestnetChain],
  projectId,
  ssr: false,
});

// 3. Initialize Reown AppKit instance
export const appKit = createAppKit({
  adapters: [wagmiAdapter],
  networks: [arcTestnetChain],
  defaultNetwork: arcTestnetChain,
  metadata: {
    name: "QMA",
    description: "Financial Intelligence Marketplace & Agent Commerce on Arc",
    url: typeof window !== "undefined" ? window.location.origin : "https://qma-three.vercel.app/",
    icons: ["https://qma-three.vercel.app/arc-logo.png"],
  },
  projectId,
  features: {
    analytics: false,
    email: false,
    socials: [],
  },
  themeMode: "dark",
  themeVariables: {
    "--w3m-accent": "#58a6ff",
    "--w3m-border-radius-master": "2px",
  },
});

export async function openAppKitModal(): Promise<void> {
  await appKit.open();
}

export async function closeAppKitModal(): Promise<void> {
  await appKit.close();
}

export function getAppKitAccount() {
  const account = appKit.getAccount();
  const address = appKit.getAddress();
  return {
    isConnected: Boolean(account?.isConnected || appKit.getIsConnectedState()),
    address: address || account?.address || "",
  };
}

// Register the ACTIVE AppKit provider as the app's single wallet source.
// Signing and transaction code reads it through getWalletProvider()
// (services/wallet) so WalletConnect / QR connections sign with the right
// wallet — not just whatever extension sits on window.ethereum.
registerAppKitProviderSource(() => {
  try {
    const provider = (appKit as unknown as { getWalletProvider?: () => unknown }).getWalletProvider?.();
    return provider && typeof (provider as { request?: unknown }).request === "function"
      ? (provider as Eip1193Provider)
      : null;
  } catch {
    return null;
  }
});

/**
 * Network Profiles & Multi-Chain Configuration
 *
 * Sourced directly from the shared Single Source of Truth: `config/networks.json`
 * Toggle between "testnet" and "mainnet" seamlessly using VITE_NETWORK_MODE.
 */

import networksData from "../../../config/networks.json";
import appData from "../../../config/app.json";

export type NetworkMode = "testnet" | "mainnet";

const configuredDefaultMode = (((appData as any)?.network?.defaultMode || "mainnet") as string).trim().toLowerCase();

export const NETWORK_MODE: NetworkMode =
  ((import.meta.env.VITE_NETWORK_MODE || configuredDefaultMode).trim().toLowerCase() === "testnet")
    ? "testnet"
    : "mainnet";

export const IS_TESTNET: boolean = NETWORK_MODE === "testnet";
export const IS_MAINNET: boolean = NETWORK_MODE === "mainnet";

export interface NativeCurrencyConfig {
  name: string;
  symbol: string;
  decimals: number;
}

export interface SupportedCrossChain {
  id: string;
  name: string;
  chainId: number;
  chainIdHex: string;
  cctpDomain: number;
  explorerUrl: string;
  rpcUrl: string;
  usdcAddress: `0x${string}`;
  nativeCurrency: NativeCurrencyConfig;
}

export interface CircleContractsConfig {
  gatewayWallet: `0x${string}`;
  gatewayMinter: `0x${string}`;
  cctpTokenMessenger: `0x${string}`;
  gatewayApiUrl: string;
}

export interface ArcChainConfig extends SupportedCrossChain {
  eurcAddress: `0x${string}`;
  usycVaultAddress?: string;
  shieldContractAddress?: string;
}

// Active profile raw data loaded from shared config/networks.json based on NETWORK_MODE
const rawProfile = IS_TESTNET ? networksData.testnet : networksData.mainnet;

export const ARC_CHAIN: ArcChainConfig = {
  id: "arc",
  name: rawProfile.arc.name,
  chainId: rawProfile.arc.chainId,
  chainIdHex: rawProfile.arc.chainIdHex,
  cctpDomain: rawProfile.arc.cctpDomain,
  explorerUrl: rawProfile.arc.explorerUrl,
  rpcUrl: rawProfile.arc.rpcUrl,
  usdcAddress: rawProfile.arc.usdcAddress as `0x${string}`,
  eurcAddress: rawProfile.arc.eurcAddress as `0x${string}`,
  usycVaultAddress: rawProfile.arc.usycVaultAddress,
  shieldContractAddress: rawProfile.arc.shieldContractAddress,
  nativeCurrency: rawProfile.arc.nativeCurrency,
};

export const SUPPORTED_CROSS_CHAINS: SupportedCrossChain[] = rawProfile.crossChains.map((c) => ({
  id: c.id,
  name: c.name,
  chainId: c.chainId,
  chainIdHex: c.chainIdHex,
  cctpDomain: c.cctpDomain,
  explorerUrl: c.explorerUrl,
  rpcUrl: c.rpcUrl,
  usdcAddress: c.usdcAddress as `0x${string}`,
  nativeCurrency: c.nativeCurrency,
}));

export const CIRCLE_CONTRACTS: CircleContractsConfig = {
  gatewayWallet: rawProfile.contracts.gatewayWallet as `0x${string}`,
  gatewayMinter: rawProfile.contracts.gatewayMinter as `0x${string}`,
  cctpTokenMessenger: rawProfile.contracts.cctpTokenMessenger as `0x${string}`,
  gatewayApiUrl: rawProfile.contracts.gatewayApiUrl,
};

export const ARC_TOKENS = {
  USDC: {
    symbol: "USDC",
    name: "USD Coin (Native Gas)",
    address: ARC_CHAIN.usdcAddress,
    decimals: 6,
  },
  EURC: {
    symbol: "EURC",
    name: "Euro Coin",
    address: ARC_CHAIN.eurcAddress,
    decimals: 6,
  },
};

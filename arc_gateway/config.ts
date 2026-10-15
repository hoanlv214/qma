import fs from "node:fs";
import path from "node:path";
import { loadEnvFile } from "./load-env.js";

/**
 * Single configuration entry point for the Arc gateway.
 *
 * - `.env` / process env: only the network mode, secrets and deployment wiring.
 * - `config/networks.json`: per-network public chain data (selected by QMA_NETWORK_MODE).
 * - `config/app.json`: network-independent business configuration.
 */

loadEnvFile(path.resolve(process.cwd(), ".env"));
loadEnvFile(path.resolve(process.cwd(), "..", ".env"));

export type Address = `0x${string}`;

export interface ArcNetworkConfig {
  name: string;
  chainId: number;
  cctpDomain: number;
  rpcUrl: string;
  explorerUrl: string;
  usdcAddress: Address;
}

export interface NetworkContractsConfig {
  gatewayWallet: Address;
  gatewayMinter: Address;
  gatewayApiUrl: string;
  circleArcUsdcTokenId: string | null;
}

export interface NetworkProfile {
  arc: ArcNetworkConfig;
  contracts: NetworkContractsConfig;
}

export interface AppConfig {
  platform: { treasuryAddress: Address };
  services: { arcGatewayPort: number };
  pricing: { previewUsdc: number; fullUsdc: number };
  gateway: { defaultDepositUsdc: number; defaultApproveUsdc: number; maxFeeRaw: string };
}

function readConfigJson<T>(fileName: string): T {
  const candidates = [
    path.resolve(process.cwd(), "config", fileName),
    path.resolve(process.cwd(), "..", "config", fileName),
  ];
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) {
    throw new Error(`Unable to locate config/${fileName}`);
  }
  return JSON.parse(fs.readFileSync(found, "utf8")) as T;
}

export const appConfig: AppConfig = readConfigJson<AppConfig>("app.json");
const defaultNetworkMode = ((appConfig as any)?.network?.defaultMode ?? "mainnet") as string;
export const isMainnet = (process.env.QMA_NETWORK_MODE ?? defaultNetworkMode).trim().toLowerCase() === "mainnet";

const networks = readConfigJson<{ testnet: NetworkProfile; mainnet: NetworkProfile }>("networks.json");
export const networkProfile: NetworkProfile = isMainnet ? networks.mainnet : networks.testnet;

/** Optional env value: secrets and deployment wiring that may legitimately be absent. */
export function optionalEnv(name: string): string | undefined {
  const value = process.env[name]?.trim();
  return value ? value : undefined;
}

/** Required env value: fail fast instead of silently falling back to a hardcoded default. */
export function requireEnv(name: string): string {
  const value = optionalEnv(name);
  if (!value) {
    throw new Error(`Missing required environment variable ${name}`);
  }
  return value;
}

/** USDC amount as an x402 price string, e.g. 0.005 -> "$0.005". */
export function usdcPrice(amount: number): string {
  return `$${amount.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")}`;
}

/** USDC amount as a fixed 2-decimal string for UI defaults, e.g. 1 -> "1.00". */
export function usdcDisplay(amount: number): string {
  return amount.toFixed(2);
}

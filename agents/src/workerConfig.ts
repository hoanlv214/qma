/**
 * Configuration for the autonomous background worker (deployment-only service).
 *
 * - process env / `.env`: network mode, secrets and inter-service URLs only.
 * - `config/networks.json`: per-network public chain data (selected by QMA_NETWORK_MODE).
 * - `config/app.json`: network-independent service settings.
 */

import * as fs from "node:fs";
import * as path from "node:path";

function loadEnvFile(envPath: string): void {
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, "utf-8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [key, ...valueParts] = trimmed.split("=");
    const varKey = key.trim();
    if (!process.env[varKey]) {
      process.env[varKey] = valueParts.join("=").trim().replace(/^['"]|['"]$/g, "");
    }
  }
}

loadEnvFile(path.resolve(process.cwd(), ".env"));
loadEnvFile(path.resolve(process.cwd(), "..", ".env"));

interface NetworkProfile {
  arc: { chainId: number; name: string };
}

interface WorkerAppConfig {
  services: {
    workerPort: number;
    workerMaxConcurrentSessions: number;
    workerPollIntervalMs: number;
  };
}

function readConfigJson<T>(fileName: string): T {
  const found = [
    path.resolve(process.cwd(), "config", fileName),
    path.resolve(process.cwd(), "..", "config", fileName),
  ].find((candidate) => fs.existsSync(candidate));
  if (!found) {
    throw new Error(`Unable to locate config/${fileName}`);
  }
  return JSON.parse(fs.readFileSync(found, "utf8")) as T;
}

function optionalEnv(name: string): string | undefined {
  const value = process.env[name]?.trim();
  return value ? value : undefined;
}

function requireEnv(name: string): string {
  const value = optionalEnv(name);
  if (!value) {
    throw new Error(`Missing required environment variable ${name}`);
  }
  return value.replace(/\/$/, "");
}

const appConfig = readConfigJson<WorkerAppConfig>("app.json");
const defaultNetworkMode = ((appConfig as any)?.network?.defaultMode ?? "mainnet") as string;
export const isMainnet = (process.env.QMA_NETWORK_MODE ?? defaultNetworkMode).trim().toLowerCase() === "mainnet";

const networks = readConfigJson<{ testnet: NetworkProfile; mainnet: NetworkProfile }>("networks.json");
const networkProfile = isMainnet ? networks.mainnet : networks.testnet;

export const workerConfig = {
  apiBaseUrl: requireEnv("QMA_API_URL"),
  arcGatewayUrl: requireEnv("QMA_ARC_GATEWAY_URL"),
  internalSecret: optionalEnv("QMA_ARC_GATEWAY_INTERNAL_SECRET") ?? "",
  arcChainId: networkProfile.arc.chainId,
  // PORT is injected by the hosting platform (Render); locally the configured port is used.
  port: Number(optionalEnv("PORT") ?? appConfig.services.workerPort),
  maxConcurrentSessions: appConfig.services.workerMaxConcurrentSessions,
  pollIntervalMs: appConfig.services.workerPollIntervalMs,
  instanceId: optionalEnv("RENDER_INSTANCE_ID") ?? String(process.pid),
} as const;

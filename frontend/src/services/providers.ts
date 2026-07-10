import { requestJson } from "./api";
import type { ProviderSummary } from "../types/qma";

export function listProviders(includeDisabled = false) {
  const suffix = includeDisabled ? "?include_disabled=true" : "";
  return requestJson<{ providers: ProviderSummary[] }>(`/api/v1/providers${suffix}`);
}

export function getProviderStats(providerId: string) {
  return requestJson<Record<string, unknown>>(`/api/v1/providers/${encodeURIComponent(providerId)}/stats`);
}

export function getAgentRecommendations(limit = 8) {
  return requestJson<Record<string, unknown>>(`/api/v1/agent/recommendations?limit=${encodeURIComponent(String(limit))}`);
}

import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { listProviders } from "../services/providers";
import type { Provider } from "../types/qma";

interface UseProvidersOptions {
  activeQuery: Record<string, any>;
  setActiveQuery: Dispatch<SetStateAction<Record<string, any>>>;
}

const DEFAULT_PROVIDERS: Provider[] = [
  {
    provider_id: "funding_memory",
    provider_name: "Funding Memory (MEXC Futures)",
    category: "crypto_funding",
    description: "MEXC futures funding anomaly memory",
    owner_wallet: "0x23e7c029a287a83d80b2e084e008211658dda11d",
    ui_schema: {
      fields: [
        { key: "fundingRate", label: "Funding Rate", type: "number", default: -0.0025 },
        { key: "marketCap", label: "Market Cap ($)", type: "number", default: 10000000 },
        { key: "circRatio", label: "Circulating Ratio", type: "number", default: 0.65 },
        { key: "fromATH", label: "Distance from ATH (%)", type: "number", default: -50 },
        { key: "volume24h", label: "24h Volume ($)", type: "number", default: 2000000 },
      ],
    },
  },
  {
    provider_id: "oi_memory",
    provider_name: "OI Memory (MEXC Open Interest)",
    category: "crypto_funding",
    description: "MEXC open interest crowding memory",
    owner_wallet: "0x23e7c029a287a83d80b2e084e008211658dda11d",
    ui_schema: {
      fields: [
        { key: "openInterest", label: "Open Interest ($)", type: "number", default: 5000000 },
        { key: "marketCap", label: "Market Cap ($)", type: "number", default: 10000000 },
        { key: "circRatio", label: "Circulating Ratio", type: "number", default: 0.65 },
        { key: "fromATH", label: "Distance from ATH (%)", type: "number", default: -50 },
        { key: "volume24h", label: "24h Volume ($)", type: "number", default: 2000000 },
      ],
    },
  },
  {
    provider_id: "polymarket_divergence",
    provider_name: "Polymarket Prediction Divergence",
    category: "prediction_market",
    description: "Cross-market prediction divergence engine between Polymarket and perpetual futures",
    owner_wallet: "0x3333333333333333333333333333333333333333",
    ui_schema: {
      fields: [
        { key: "symbol", label: "Target Symbol", type: "string", default: "BTC" },
        { key: "event_title", label: "Prediction Question", type: "string", default: "When will Bitcoin hit $150k?" },
        { key: "market_probability", label: "Polymarket Prob", type: "number", default: 0.28, step: 0.01 },
        { key: "perpetual_funding_8h", label: "Perp Funding (%)", type: "number", default: 0.015, step: 0.005 },
        { key: "basis_spread_bps", label: "Basis Spread (bps)", type: "number", default: 45, step: 5 },
      ],
    },
  },
  {
    provider_id: "pyth_stress_band",
    provider_name: "Pyth Low-Latency Stress Band",
    category: "market_stress",
    description: "Sub-second oracle stress analytics powered by Pyth Network Hermes",
    owner_wallet: "0x4444444444444444444444444444444444444444",
    ui_schema: {
      fields: [
        { key: "symbol", label: "Oracle Feed", type: "string", default: "ETH/USD" },
        { key: "price", label: "Pyth Price ($)", type: "number", default: 2515.50, step: 0.5 },
        { key: "confidence_interval", label: "Confidence (±$)", type: "number", default: 1.25, step: 0.05 },
        { key: "exponent", label: "Feed Exponent", type: "integer", default: -8 },
      ],
    },
  },
];

export function useProviders({ activeQuery, setActiveQuery }: UseProvidersOptions) {
  const [selectedProviderId, setSelectedProviderId] = useState("funding_memory");
  const [providers, setProviders] = useState<Provider[]>(DEFAULT_PROVIDERS);

  const loadProviders = async () => {
    try {
      const data = await listProviders();
      const raw = (data.providers as Provider[]) || [];
      // Deduplicate by provider_id (backend may return duplicates)
      const seen = new Set<string>();
      const unique = raw.filter((p) => {
        if (seen.has(p.provider_id)) return false;
        seen.add(p.provider_id);
        return true;
      });
      setProviders(unique.length > 0 ? unique : DEFAULT_PROVIDERS);
    } catch (err) {
      console.warn("Failed to load providers list", err);
    }
  };

  useEffect(() => {
    loadProviders();
  }, []);

  const handleProviderChange = (providerId: string) => {
    setSelectedProviderId(providerId);
    const target = providers.find((provider) => provider.provider_id === providerId);
    if (target?.ui_schema?.fields) {
      const fieldsQuery: Record<string, any> = { symbol: activeQuery.symbol || "HYPE" };
      target.ui_schema.fields.forEach((field) => {
        fieldsQuery[field.key] = field.default !== undefined ? field.default : "";
      });
      setActiveQuery(fieldsQuery);
    }
  };

  return {
    providers,
    selectedProviderId,
    setSelectedProviderId,
    loadProviders,
    handleProviderChange,
  };
}

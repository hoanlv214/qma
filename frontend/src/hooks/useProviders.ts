import { useState, type Dispatch, type SetStateAction } from "react";
import { API_BASE_URL } from "../services/api";
import type { Provider } from "../types/qma";

interface UseProvidersOptions {
  activeQuery: Record<string, any>;
  setActiveQuery: Dispatch<SetStateAction<Record<string, any>>>;
}

export function useProviders({ activeQuery, setActiveQuery }: UseProvidersOptions) {
  const [selectedProviderId, setSelectedProviderId] = useState("funding_memory");
  const [providers, setProviders] = useState<Provider[]>([]);

  const loadProviders = async () => {
    try {
      const resp = await fetch(`${API_BASE_URL}/api/v1/providers`);
      if (!resp.ok) return;
      const data = await resp.json();
      setProviders(data.providers || []);
    } catch (err) {
      console.warn("Failed to load providers list", err);
    }
  };

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

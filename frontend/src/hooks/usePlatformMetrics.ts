import { useState } from "react";
import { API_BASE_URL } from "../services/api";

export function usePlatformMetrics() {
  const [metrics, setMetrics] = useState({
    paid_count: 0,
    revenue_usdc: 0,
    available_usdc: 0,
  });

  const loadPlatformSummary = async () => {
    const resp = await fetch(`${API_BASE_URL}/api/v1/platform/summary`);
    if (!resp.ok) throw new Error(`Platform summary returned ${resp.status}`);
    const data = await resp.json();
    setMetrics({
      paid_count: data.current_paid_count ?? data.paid_count ?? 0,
      revenue_usdc: data.revenue_usdc || 0,
      available_usdc: data.seller_gateway_balance?.available_usdc ?? data.available_usdc ?? 0,
    });
    return data;
  };

  return { metrics, loadPlatformSummary };
}

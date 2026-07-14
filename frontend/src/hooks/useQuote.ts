import { useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "../services/api";

interface UseQuoteOptions {
  activeQuery: Record<string, any>;
  selectedProviderId: string;
}

export function useQuote({ activeQuery, selectedProviderId }: UseQuoteOptions) {
  const [quotedPrices, setQuotedPrices] = useState<Record<string, number>>({});
  const quoteTimer = useRef<any>(null);

  const scheduleQuoteRefresh = () => {
    clearTimeout(quoteTimer.current);
    quoteTimer.current = setTimeout(async () => {
      try {
        const tiers = ["preview", "full"];
        const results = await Promise.all(
          tiers.map(async (tier) => {
            const resp = await fetch(`${API_BASE_URL}/api/v1/payment/quote`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                ...activeQuery,
                provider_id: selectedProviderId,
                tier,
              }),
            });
            if (!resp.ok) return [tier, null];
            const resData = await resp.json();
            return [tier, Number(resData.amount_usdc)];
          })
        );
        const nextQuotes: Record<string, number> = {};
        results.forEach(([tier, value]) => {
          if (tier && value !== null) nextQuotes[tier as string] = value as number;
        });
        setQuotedPrices(nextQuotes);
      } catch (err) {
        console.warn("Quote refresh failed", err);
      }
    }, 400);
  };

  useEffect(() => {
    if (activeQuery?.symbol) {
      scheduleQuoteRefresh();
    }
  }, [activeQuery, selectedProviderId]);

  return {
    quotedPrices,
    quoteTimer,
    scheduleQuoteRefresh,
  };
}

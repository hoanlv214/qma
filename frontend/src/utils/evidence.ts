/**
 * Utility for computing verifiable exchange evidence URLs
 */

export function getFallbackEvidenceUrl(exchange: string, sym: string): string {
  const ex = (exchange || "").toUpperCase();
  const cleanSym = (sym || "BTC").toUpperCase().replace(/[-_].*$/, "");

  if (ex === "BYBIT") {
    return `https://api.bybit.com/v5/market/tickers?category=linear&symbol=${cleanSym}USDT`;
  }
  if (ex === "BINANCE") {
    return `https://api.binance.com/api/v3/ticker/24hr?symbol=${cleanSym}USDT`;
  }
  if (ex === "OKX") {
    return `https://www.okx.com/api/v5/public/funding-rate?instId=${cleanSym}-USDT-SWAP`;
  }
  return `https://contract.mexc.com/api/v1/contract/funding_rate/${cleanSym}_USDT`;
}

export function resolveEvidenceUrl(rawUrl?: string, exchange?: string, symbol?: string): string {
  if (rawUrl && typeof rawUrl === "string" && rawUrl.startsWith("http")) {
    return rawUrl;
  }
  return getFallbackEvidenceUrl(exchange || "BYBIT", symbol || "CVC");
}

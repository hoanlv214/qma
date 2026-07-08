import { API_BASE_URL } from "./api";
import { getInjectedWallet } from "./wallet";

interface WalletProfileCache {
  token: string;
  expiresAt: number;
}

export function walletProfileTokenCacheKey(account: string) {
  return `qma_wallet_profile_token_${account.toLowerCase()}`;
}

export function clearWalletProfileSession(account: string) {
  if (!account) return;
  sessionStorage.removeItem(walletProfileTokenCacheKey(account));
}

export function clearAllWalletProfileSessions() {
  const keys: string[] = [];
  for (let i = 0; i < sessionStorage.length; i += 1) {
    const key = sessionStorage.key(i);
    if (key && key.startsWith("qma_wallet_profile_token_")) keys.push(key);
  }
  keys.forEach((key) => sessionStorage.removeItem(key));
}

export function getCachedWalletProfileToken(account: string) {
  if (!account) return "";
  const normalized = account.toLowerCase();
  const raw = sessionStorage.getItem(walletProfileTokenCacheKey(normalized));
  if (!raw) return "";
  try {
    const cached = JSON.parse(raw) as WalletProfileCache;
    if (cached?.token && Number(cached.expiresAt || 0) > Date.now() + 15_000) {
      return cached.token;
    }
  } catch {
    // Older builds stored the raw JWT. Drop it so an expired token cannot poison reloads.
  }
  clearWalletProfileSession(normalized);
  return "";
}

export function walletProfileMessage(account: string, nonce: string, issuedAt: number) {
  return [
    "QMA Wallet Profile Access",
    `Wallet: ${account.toLowerCase()}`,
    `Nonce: ${nonce}`,
    `Issued At: ${issuedAt}`,
    "Purpose: unlock-paid-report-snapshots",
  ].join("\n");
}

export async function requestWalletProfileSession(account: string) {
  const normalized = account.toLowerCase();
  const cached = getCachedWalletProfileToken(normalized);
  if (cached) return cached;

  const provider = getInjectedWallet();
  if (!provider) throw new Error("Connect the wallet owner to unlock private report snapshots.");

  const accounts = await provider.request<string[]>({ method: "eth_requestAccounts" });
  const active = accounts?.[0] ? String(accounts[0]) : "";
  if (active.toLowerCase() !== normalized) {
    throw new Error("Connected wallet does not match this private profile.");
  }

  const issuedAt = Math.floor(Date.now() / 1000);
  const nonce = `${issuedAt}-${Math.random().toString(36).slice(2)}`;
  const message = walletProfileMessage(normalized, nonce, issuedAt);
  const signature = await provider.request<string>({
    method: "personal_sign",
    params: [message, active],
  });

  const resp = await fetch(`${API_BASE_URL}/api/v1/wallets/${normalized}/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      nonce,
      issued_at: issuedAt,
      signature,
    }),
  });
  if (!resp.ok) {
    const payload = await resp.json().catch(() => ({}));
    throw new Error(payload.detail || "Could not unlock private profile.");
  }

  const data = await resp.json();
  const token = data.wallet_token || "";
  if (!token) return "";

  const expiresInMs = Math.max(30, Number(data.expires_in || 3600)) * 1000;
  sessionStorage.setItem(walletProfileTokenCacheKey(normalized), JSON.stringify({
    token,
    expiresAt: Date.now() + expiresInMs,
  }));
  return token;
}

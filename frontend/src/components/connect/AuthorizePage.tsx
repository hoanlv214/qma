import { useCallback, useEffect, useState } from "react";
import { requestJson, API_BASE_URL } from "../../services/api";
import {
  getCachedWalletProfileToken,
  requestWalletProfileSession,
} from "../../services/walletProfileSession";
import { getInjectedWallet } from "../../services/wallet";

// Deep links are opened by cloud AI apps, so they must point at a publicly
// reachable HTTPS MCP URL. Priority: VITE_QMA_MCP_PUBLIC_URL (dev tunnel)
// > API_BASE_URL (production) > localhost (local browser flows only).
const MCP_ENDPOINT = import.meta.env.VITE_QMA_MCP_PUBLIC_URL
  || (API_BASE_URL ? `${API_BASE_URL}/mcp` : "http://localhost:8000/mcp");
const CLAUDE_DEEP_LINK = `https://claude.ai/new?modal=add-custom-connector&connectorName=QMA&connectorUrl=${encodeURIComponent(MCP_ENDPOINT)}#settings/customize-connectors`;
const CHATGPT_DEEP_LINK = "https://chatgpt.com/plugins#settings/Connectors?create-connector=true&redirectAfter=%2Fplugins";

interface OAuthParams {
  clientId: string;
  codeChallenge: string;
  redirectUri: string;
  state: string;
}

interface ConnectionRow {
  client_id: string;
  client_name: string;
  caps: { max_price_usdc?: number; budget_usdc?: number };
  status: string;
  created_at?: string;
}

function readOAuthParams(): OAuthParams | null {
  const params = new URLSearchParams(window.location.search);
  const clientId = params.get("client_id") || "";
  const codeChallenge = params.get("code_challenge") || "";
  if (!clientId || !codeChallenge) return null;
  return {
    clientId,
    codeChallenge,
    redirectUri: params.get("redirect_uri") || "",
    state: params.get("state") || "",
  };
}

export function AuthorizePage() {
  const [oauthParams] = useState<OAuthParams | null>(() => readOAuthParams());
  const [account, setAccount] = useState<string>(() => localStorage.getItem("qma_connected_wallet") || "");
  const [maxPriceUsdc, setMaxPriceUsdc] = useState("0.05");
  const [budgetUsdc, setBudgetUsdc] = useState("5");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [issuedCode, setIssuedCode] = useState("");
  const [copiedUrl, setCopiedUrl] = useState(false);
  const [connections, setConnections] = useState<ConnectionRow[]>([]);
  const [connectionsOwner, setConnectionsOwner] = useState("");

  const loadConnections = useCallback(async (wallet: string) => {
    try {
      const cached = getCachedWalletProfileToken(wallet);
      const token = cached || (await requestWalletProfileSession(wallet));
      if (!token) return;
      const data = await requestJson<{ connections?: ConnectionRow[] }>(
        `/api/v1/oauth/connections?owner_wallet=${wallet.toLowerCase()}`,
        { headers: { "X-QMA-Wallet-Token": token } },
      );
      setConnections(data?.connections || []);
      setConnectionsOwner(wallet.toLowerCase());
    } catch {
      setConnections([]);
    }
  }, []);

  // Auto-inherit connected wallet on mount without popping up unnecessary dialogs
  useEffect(() => {
    const saved = localStorage.getItem("qma_connected_wallet");
    if (saved) {
      const normalized = saved.toLowerCase();
      setAccount(normalized);
      if (getCachedWalletProfileToken(normalized)) {
        void loadConnections(normalized);
      }
    }

    const provider = getInjectedWallet();
    if (provider?.request) {
      provider
        .request<string[]>({ method: "eth_accounts" })
        .then((accs) => {
          const active = accs?.[0] ? String(accs[0]).toLowerCase() : "";
          if (active) {
            setAccount(active);
            localStorage.setItem("qma_connected_wallet", active);
            void loadConnections(active);
          }
        })
        .catch(() => {});
    }
  }, [loadConnections]);

  useEffect(() => {
    if (!oauthParams) return;
    document.title = "Authorize your AI agent — QMA";
  }, [oauthParams]);

  const authorize = async () => {
    if (!oauthParams) return;
    setError("");
    setBusy(true);
    try {
      const provider = getInjectedWallet();
      if (!provider) throw new Error("No wallet extension found. Install Rabby, OKX Wallet, or MetaMask first.");
      
      let active = account;
      if (!active) {
        const accounts = await provider.request<string[]>({ method: "eth_requestAccounts" });
        active = accounts?.[0] ? String(accounts[0]).toLowerCase() : "";
        if (!active) throw new Error("Connect a wallet to continue.");
        setAccount(active);
        localStorage.setItem("qma_connected_wallet", active);
      }

      // Reuse cached valid session token if present, otherwise trigger one-time signature
      const walletToken = getCachedWalletProfileToken(active) || (await requestWalletProfileSession(active));
      if (!walletToken) throw new Error("Wallet signature was cancelled.");

      const data = await requestJson<{ code?: string }>(
        `/api/v1/oauth/approve?owner_wallet=${active}`,
        {
          method: "POST",
          headers: { "X-QMA-Wallet-Token": walletToken, "Content-Type": "application/json" },
          body: JSON.stringify({
            client_id: oauthParams.clientId,
            code_challenge: oauthParams.codeChallenge,
            redirect_uri: oauthParams.redirectUri,
            caps: {
              max_price_usdc: Number(maxPriceUsdc) || 0.05,
              budget_usdc: Number(budgetUsdc) || 5,
            },
          }),
        },
      );
      const code = data?.code || "";
      if (!code) throw new Error("Approval returned no authorization code.");
      setIssuedCode(code);

      if (oauthParams.redirectUri) {
        const joiner = oauthParams.redirectUri.includes("?") ? "&" : "?";
        const target = `${oauthParams.redirectUri}${joiner}code=${encodeURIComponent(code)}${oauthParams.state ? `&state=${encodeURIComponent(oauthParams.state)}` : ""}`;
        window.location.replace(target);
        return;
      }
      await loadConnections(active);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (clientId: string) => {
    try {
      const token = getCachedWalletProfileToken(connectionsOwner) || (await requestWalletProfileSession(connectionsOwner));
      await requestJson(
        `/api/v1/oauth/revoke?owner_wallet=${connectionsOwner}`,
        {
          method: "POST",
          headers: { "X-QMA-Wallet-Token": token, "Content-Type": "application/json" },
          body: JSON.stringify({ client_id: clientId }),
        },
      );
      await loadConnections(connectionsOwner);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const panelStyle: React.CSSProperties = {
    maxWidth: 520,
    margin: "72px auto",
    padding: 28,
    borderRadius: 16,
    background: "rgba(255,255,255,0.04)",
    border: "1px solid rgba(255,255,255,0.10)",
    fontFamily: "inherit",
  };

  if (!oauthParams) {
    return (
      <div style={panelStyle}>
        <h1 style={{ marginTop: 0 }}>AI agent connections</h1>
        <p style={{ opacity: 0.75 }}>
          Connect QMA market memory to your AI app. Picking an app below opens its
          connector dialog with QMA pre-filled — you only confirm inside the app,
          sign the wallet proof here, and set spend caps.
        </p>

        <div style={{ display: "grid", gap: 10, marginTop: 16 }}>
          <a
            href={CLAUDE_DEEP_LINK}
            target="_blank"
            rel="noopener noreferrer"
            style={{ display: "block", textAlign: "center", padding: "12px 16px", borderRadius: 10, fontWeight: 600, background: "#d97757", color: "#fff", textDecoration: "none" }}
          >
            Connect with Claude →
          </a>
          <button
            onClick={async () => {
              try { await navigator.clipboard.writeText(MCP_ENDPOINT); setCopiedUrl(true); } catch { setError("Copy failed — paste manually: " + MCP_ENDPOINT); }
              window.open(CHATGPT_DEEP_LINK, "_blank", "noopener");
            }}
            style={{ padding: "12px 16px", borderRadius: 10, fontWeight: 600, cursor: "pointer" }}
          >
            {copiedUrl ? "URL copied — Connect with ChatGPT →" : "Connect with ChatGPT (copies URL) →"}
          </button>
        </div>
        {copiedUrl && (
          <p style={{ opacity: 0.6, fontSize: 12, marginTop: 8 }}>
            In ChatGPT's "Create connector" dialog, paste: <code style={{ wordBreak: "break-all" }}>{MCP_ENDPOINT}</code>
          </p>
        )}

        <p style={{ opacity: 0.6, fontSize: 13, marginTop: 22 }}>
          Or connect your wallet below to review and revoke existing connections.
        </p>
        <button onClick={() => {
          getInjectedWallet()?.request<string[]>({ method: "eth_requestAccounts" }).then((accs) => {
            const active = accs?.[0] ? String(accs[0]).toLowerCase() : "";
            if (active) {
              setAccount(active);
              localStorage.setItem("qma_connected_wallet", active);
              void loadConnections(active);
            }
          });
        }} disabled={busy}>
          {account ? `Connected: ${account.slice(0, 10)}…${account.slice(-6)}` : "Connect wallet to manage connections"}
        </button>
        {connections.length > 0 && (
          <div style={{ marginTop: 18, display: "grid", gap: 10 }}>
            {connections.map((row) => (
              <div key={row.client_id} style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "10px 12px", borderRadius: 10, background: "rgba(255,255,255,0.05)" }}>
                <div>
                  <div style={{ fontWeight: 600 }}>{row.client_name}</div>
                  <div style={{ opacity: 0.65, fontSize: 12 }}>
                    status {row.status} · cap ${row.caps?.max_price_usdc ?? "?"}/report · budget ${row.caps?.budget_usdc ?? "?"}
                  </div>
                </div>
                {row.status === "active" && (
                  <button onClick={() => void revoke(row.client_id)}>Revoke</button>
                )}
              </div>
            ))}
          </div>
        )}
        {error && <p style={{ color: "#ff6b6b" }}>{error}</p>}
      </div>
    );
  }

  return (
    <div style={panelStyle}>
      <h1 style={{ marginTop: 0 }}>Authorize your AI agent</h1>
      <p style={{ opacity: 0.75 }}>
        An MCP client (<strong>{oauthParams.clientId.slice(0, 18)}…</strong>) wants to query QMA market
        memory on your behalf. Purchases run from your own QMA Agent Wallet within the caps below —
        you can revoke anytime and withdraw remaining funds.
      </p>

      {account && (
        <div style={{ padding: "10px 14px", borderRadius: 8, background: "rgba(255,255,255,0.06)", fontSize: 13, marginTop: 14 }}>
          Connected Wallet: <strong style={{ fontFamily: "monospace" }}>{account.slice(0, 8)}…{account.slice(-6)}</strong>
        </div>
      )}

      <label style={{ display: "block", marginTop: 14, fontSize: 13, opacity: 0.8 }}>
        Max spend per report (USDC)
        <input
          type="number" min={0.001} step={0.001} value={maxPriceUsdc}
          onChange={(event) => setMaxPriceUsdc(event.target.value)}
          style={{ width: "100%", marginTop: 4, padding: "8px 10px", borderRadius: 8, background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.15)", color: "inherit" }}
        />
      </label>
      <label style={{ display: "block", marginTop: 12, fontSize: 13, opacity: 0.8 }}>
        Total budget for this connection (USDC)
        <input
          type="number" min={0.001} step={0.5} value={budgetUsdc}
          onChange={(event) => setBudgetUsdc(event.target.value)}
          style={{ width: "100%", marginTop: 4, padding: "8px 10px", borderRadius: 8, background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,255,255,0.15)", color: "inherit" }}
        />
      </label>

      {issuedCode ? (
        <div style={{ marginTop: 18 }}>
          <p>✅ Connected. Return to your AI app — the code below was delivered automatically.</p>
          <code style={{ wordBreak: "break-all", fontSize: 12, opacity: 0.7 }}>{issuedCode}</code>
        </div>
      ) : (
        <button
          onClick={() => void authorize()}
          disabled={busy}
          style={{ marginTop: 20, width: "100%", padding: "12px 16px", borderRadius: 10, fontWeight: 600, cursor: busy ? "wait" : "pointer" }}
        >
          {busy
            ? "Authorizing…"
            : account
              ? `Authorize as ${account.slice(0, 6)}…${account.slice(-4)}`
              : "Connect wallet & authorize"}
        </button>
      )}
      {error && <p style={{ color: "#ff6b6b" }}>{error}</p>}
      <p style={{ opacity: 0.45, fontSize: 12, marginTop: 18 }}>
        Wallet proof uses a one-time signature (QMA Wallet Profile Access). QMA never sees your
        private keys. Funds live in a dedicated Agent Wallet and are withdrawable at any time.
      </p>
    </div>
  );
}

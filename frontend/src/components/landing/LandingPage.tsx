import { useEffect, useState } from "react";
import { API_BASE_URL } from "../../services/api";

type RequestState = "loading" | "loaded" | "unavailable";

interface Metrics {
  unique_payers: number;
  paid_count: number;
  agent_unlocks: number;
  revenue_usdc: number;
  preview_count: number;
  full_count: number;
  state: RequestState;
}

export function LandingPage({ onNavigate }: { onNavigate: (route: any) => void }) {
  const [metrics, setMetrics] = useState<Metrics>({
    unique_payers: 0,
    paid_count: 0,
    agent_unlocks: 0,
    revenue_usdc: 0,
    preview_count: 0,
    full_count: 0,
    state: "loading",
  });

  useEffect(() => {
    async function loadLandingTraction() {
      try {
        const resp = await fetch(`${API_BASE_URL}/api/v1/metrics?payment_page_size=1&payer_page_size=1`, {
          headers: { Accept: "application/json" },
        });
        if (!resp.ok) throw new Error(`metrics ${resp.status}`);
        const data = await resp.json();
        const tierCounts = data.tier_counts || {};
        const buyerTypes = data.buyer_type_counts || {};
        setMetrics({
          unique_payers: data.unique_payers ?? 0,
          paid_count: data.current_paid_count ?? data.paid_count ?? 0,
          agent_unlocks: buyerTypes.agent ?? 0,
          revenue_usdc: data.revenue_usdc ?? 0,
          preview_count: tierCounts.preview ?? 0,
          full_count: tierCounts.full ?? 0,
          state: "loaded",
        });
      } catch (err) {
        console.warn("Landing traction unavailable", err);
        setMetrics((prev) => ({ ...prev, state: "unavailable" }));
      }
    }
    loadLandingTraction();
  }, []);

  function compactNumber(value: number) {
    return new Intl.NumberFormat("en-US", {
      notation: value >= 10000 ? "compact" : "standard",
      maximumFractionDigits: 1,
    }).format(value);
  }

  function formatRevenue(value: number) {
    if (value === 0) return "0";
    if (value < 1) return value.toFixed(3);
    return compactNumber(value);
  }

  function renderMetricValue(value: number) {
    return metrics.state === "loaded" ? compactNumber(value) : "—";
  }

  return (
    <main className="new-landing">
      {/* Navigation */}
      <nav className="new-landing-nav">
        <div className="new-nav-container">
          <a href="/" className="new-logo" title="QMA" onClick={(e) => e.preventDefault()}>
            <span className="new-logo-text">QMA</span>
          </a>
          <div className="new-nav-links">
            <button type="button" className="new-nav-item" onClick={() => onNavigate("marketplace")}>
              Marketplace
            </button>
            <a className="new-nav-item" href={`${API_BASE_URL}/docs`} target="_blank" rel="noopener noreferrer">
              Docs
            </a>
            <a className="new-nav-item" href="https://github.com/hoanlv214/qma" target="_blank" rel="noopener noreferrer">
              GitHub
            </a>
            <button type="button" className="new-nav-cta" onClick={() => onNavigate("app")}>
              Launch App
            </button>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="new-hero">
        <div className="new-hero-container">
          <div className="new-hero-label">Evidence-Based Market Research</div>
          <h1 className="new-hero-title">See what happened the last time the market looked like this</h1>
          <p className="new-hero-subtitle">
            Match live market signals to historical analogs. Access lightweight Preview reports or comprehensive Full analysis via pay-per-query x402 payments. Built for traders, researchers, and bounded AI agents.
          </p>
          <div className="new-hero-actions">
            <button type="button" className="new-btn new-btn-primary" onClick={() => onNavigate("app")}>
              Launch App
            </button>
            <a href={`${API_BASE_URL}/docs`} target="_blank" rel="noopener noreferrer" className="new-btn new-btn-secondary">
              Read Docs
            </a>
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="new-features">
        <div className="new-features-container">
          <div className="new-feature-card">
            <div className="new-feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </div>
            <h3>Market Memory Analysis</h3>
            <p>Instantly compare today's live signals against years of historical data.</p>
          </div>
          <div className="new-feature-card">
            <div className="new-feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="2" y="5" width="20" height="14" rx="2" />
                <path d="M2 10h20" />
              </svg>
            </div>
            <h3>Evidence-Backed Reports</h3>
            <p>Get detailed distribution outcomes, win rates, and similar event histories.</p>
          </div>
          <div className="new-feature-card">
            <div className="new-feature-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
                <polyline points="10 17 15 12 10 7" />
                <line x1="15" y1="12" x2="3" y2="12" />
              </svg>
            </div>
            <h3>Persistent Unlocks</h3>
            <p>No subscriptions. Reports are bound to your wallet, accessible anytime.</p>
          </div>
        </div>
      </section>

      {/* Stats Section */}
      <section className="new-stats">
        <div className="new-stats-container">
          <div className="new-stat-item">
            <div className="new-stat-value">{renderMetricValue(metrics.unique_payers)}</div>
            <div className="new-stat-label">Paying Wallets</div>
          </div>
          <div className="new-stat-item">
            <div className="new-stat-value">{renderMetricValue(metrics.paid_count)}</div>
            <div className="new-stat-label">Reports Unlocked</div>
          </div>
          <div className="new-stat-item">
            <div className="new-stat-value">{renderMetricValue(metrics.agent_unlocks)}</div>
            <div className="new-stat-label">Agent Unlocks</div>
          </div>
          <div className="new-stat-item">
            <div className="new-stat-value">{metrics.state === "loaded" ? formatRevenue(metrics.revenue_usdc) : "—"}</div>
            <div className="new-stat-label">USDC Volume</div>
          </div>
        </div>
      </section>

      {/* Info Section */}
      <section className="new-info">
        <div className="new-info-container">
          <div className="new-info-content">
            <h2>A Marketplace for Market Intelligence</h2>
            <p>
              QMA operates as a decentralized platform for historical market context. Independent intelligence providers publish priced report tiers as APIs. Users and bounded agents query instantly, and entitlements persist on-chain.
            </p>
            <div className="new-info-list">
              <div className="new-info-item">
                <span className="new-info-label">Reports Bound To</span>
                <span className="new-info-value">Provider, Signal, and Tier</span>
              </div>
              <div className="new-info-item">
                <span className="new-info-label">Settlement Model</span>
                <span className="new-info-value">Creator 80% / Platform 20% split (on Arc Testnet)</span>
              </div>
              <div className="new-info-item">
                <span className="new-info-label">Payment & Entitlements</span>
                <span className="new-info-value">Tracked and settled for each purchase</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* How Market-Memory Works */}
      <section className="new-how-it-works">
        <div className="new-how-container">
          <h2>How Market-Memory Retrieval Works</h2>
          <div className="new-steps">
            <div className="new-step">
              <div className="new-step-number">1</div>
              <h3>Submit Signal</h3>
              <p>Describe a live market condition: price level, volume spike, volatility shift, or custom parameters.</p>
            </div>
            <div className="new-step">
              <div className="new-step-number">2</div>
              <h3>Match to History</h3>
              <p>QMA finds historical events with similar characteristics and retrieves provider data.</p>
            </div>
            <div className="new-step">
              <div className="new-step-number">3</div>
              <h3>Pay and Unlock</h3>
              <p>Pay once per report (Preview or Full tier). Entitlement persists in your wallet.</p>
            </div>
          </div>
        </div>
      </section>

      {/* Preview vs Full Tiers */}
      <section className="new-tiers">
        <div className="new-tiers-container">
          <h2>Report Tiers</h2>
          <div className="new-tiers-grid">
            <div className="new-tier-card">
              <h3>Preview</h3>
              <p className="new-tier-desc">Lightweight snapshot—signal match metadata, outcome distribution, win rate.</p>
              <div className="new-tier-use">For exploratory queries and automated agent scanning.</div>
            </div>
            <div className="new-tier-card">
              <h3>Full</h3>
              <p className="new-tier-desc">Comprehensive report—event timeline, correlation analysis, detailed distributions, provider notes.</p>
              <div className="new-tier-use">For traders, researchers, and high-confidence trading decisions.</div>
            </div>
          </div>
          <div className="new-tiers-note">
            Agents can upgrade Preview to Full for the incremental price difference.
          </div>
        </div>
      </section>

      {/* Human Purchase Flow */}
      <section className="new-human-flow">
        <div className="new-flow-container">
          <h2>For Traders & Researchers</h2>
          <div className="new-flow-steps">
            <div className="new-flow-step">
              <div className="new-flow-label">1. Connect Wallet</div>
              <p>Link your wallet (Arc Testnet). Entitlements are bound to your address.</p>
            </div>
            <div className="new-flow-step">
              <div className="new-flow-label">2. Submit Signal</div>
              <p>Describe market conditions or pick from live signals. Choose Preview or Full tier.</p>
            </div>
            <div className="new-flow-step">
              <div className="new-flow-label">3. Approve Payment</div>
              <p>Pay one-time USDC amount. No subscriptions—pay only for reports you want.</p>
            </div>
            <div className="new-flow-step">
              <div className="new-flow-label">4. Access Anytime</div>
              <p>Report unlocked permanently to your wallet. Re-query for free, upgrade to Full anytime.</p>
            </div>
          </div>
        </div>
      </section>

      {/* Bounded Agent Purchase Flow */}
      <section className="new-agent-api">
        <div className="new-agent-container">
          <div className="new-agent-content">
            <h2>Bounded-Agent Purchase Flow</h2>
            <p>Agents query the market-memory API within enforced policy boundaries. Reports are bound to the agent wallet and callable by permission.</p>
            <div className="new-agent-policies">
              <div className="new-policy-item">
                <span className="new-policy-label">Budget Cap</span>
                <span className="new-policy-desc">Per-purchase maximum spend enforced before query execution.</span>
              </div>
              <div className="new-policy-item">
                <span className="new-policy-label">Maximum Price Per Query</span>
                <span className="new-policy-desc">Reject reports exceeding max_price_usdc threshold.</span>
              </div>
              <div className="new-policy-item">
                <span className="new-policy-label">Provider & Tier Allowlist</span>
                <span className="new-policy-desc">Query only approved providers and report tiers.</span>
              </div>
              <div className="new-policy-item">
                <span className="new-policy-label">Duplicate Prevention</span>
                <span className="new-policy-desc">Skip re-purchase of already-unlocked reports.</span>
              </div>
              <div className="new-policy-item">
                <span className="new-policy-label">Upgrade Path</span>
                <span className="new-policy-desc">Agents can upgrade Preview reports to Full for incremental cost.</span>
              </div>
            </div>
            <div className="new-agent-actions">
              <a href={`${API_BASE_URL}/docs`} target="_blank" rel="noopener noreferrer" className="new-btn new-btn-primary">
                Open API Docs
              </a>
              <a href="https://github.com/hoanlv214/qma/blob/main/examples/README.md" target="_blank" rel="noopener noreferrer" className="new-btn new-btn-secondary">
                View Example
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Providers */}
      <section className="new-providers">
        <div className="new-providers-container">
          <h2>For Creators and Researchers</h2>
          <p>Monetize proprietary data. Package your intelligence as a query-based API and let QMA handle wallet-based entitlement and instant payments.</p>
          <div className="new-provider-actions">
            <button type="button" className="new-btn new-btn-primary" onClick={() => onNavigate("marketplace")}>
              Become a Provider
            </button>
            <a href={`${API_BASE_URL}/docs`} target="_blank" rel="noopener noreferrer" className="new-btn new-btn-secondary">
              View API Docs
            </a>
          </div>
        </div>
      </section>

      {/* Developer Strip */}
      <section className="new-dev-strip">
        <div className="new-dev-container">
          <div className="new-dev-content">
            <span className="new-dev-label">Open Source</span>
            <p>Build custom providers, extend the matching engine, or integrate settlement middleware.</p>
          </div>
          <a href="https://github.com/hoanlv214/qma" target="_blank" rel="noopener noreferrer" className="new-btn new-btn-secondary">
            View on GitHub
          </a>
        </div>
      </section>

      {/* Footer */}
      <footer className="new-footer">
        <div className="new-footer-container">
          <div className="new-footer-brand">
            <a href="/" className="new-logo" title="QMA" onClick={(e) => e.preventDefault()}>
              <span className="new-logo-text">QMA</span>
            </a>
            <p>Historical market intelligence. Evidence-backed reports from past analog events, not predictions.</p>
            <div className="new-socials">
              <a href="https://x.com/hoanlv21" target="_blank" rel="noopener noreferrer" title="X">X</a>
              <a href="https://github.com/hoanlv214/qma" target="_blank" rel="noopener noreferrer" title="GitHub">GitHub</a>
            </div>
          </div>
          <div className="new-footer-bottom">
            <p>&copy; 2024 QMA. All rights reserved.</p>
          </div>
        </div>
      </footer>
    </main>
  );
}

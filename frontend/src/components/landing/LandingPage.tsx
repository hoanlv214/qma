import { useEffect, useState } from "react";
import { API_BASE_URL } from "../../services/api";

interface Metrics {
  unique_payers: number;
  paid_count: number;
  agent_unlocks: number;
  revenue_usdc: number;
  preview_count: number;
  full_count: number;
}

export function LandingPage({ onNavigate }: { onNavigate: (route: any) => void }) {
  const [metrics, setMetrics] = useState<Metrics>({
    unique_payers: 0,
    paid_count: 0,
    agent_unlocks: 0,
    revenue_usdc: 0,
    preview_count: 0,
    full_count: 0,
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
          unique_payers: data.unique_payers || 0,
          paid_count: data.current_paid_count ?? data.paid_count ?? 0,
          agent_unlocks: buyerTypes.agent || 0,
          revenue_usdc: data.revenue_usdc || 0,
          preview_count: tierCounts.preview || 0,
          full_count: tierCounts.full || 0,
        });
      } catch (err) {
        console.warn("Landing traction unavailable", err);
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
            QMA retrieves similar historical market situations and generates evidence-backed reports. Compare today's signals with past events and unlock detailed memory reports with pay-per-query payments.
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
            <div className="new-stat-value">{compactNumber(metrics.unique_payers)}</div>
            <div className="new-stat-label">Active Wallets</div>
          </div>
          <div className="new-stat-item">
            <div className="new-stat-value">{compactNumber(metrics.paid_count)}</div>
            <div className="new-stat-label">Reports Unlocked</div>
          </div>
          <div className="new-stat-item">
            <div className="new-stat-value">{compactNumber(metrics.agent_unlocks)}</div>
            <div className="new-stat-label">API Integrations</div>
          </div>
          <div className="new-stat-item">
            <div className="new-stat-value">{Number(metrics.revenue_usdc).toFixed(0)}</div>
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
              QMA operates as a decentralized platform for historical market context. Independent intelligence providers package private datasets as paid APIs that users and autonomous agents can query instantly.
            </p>
            <div className="new-info-list">
              <div className="new-info-item">
                <span className="new-info-label">Active Providers</span>
                <span className="new-info-value">Funding Memory, OI Memory</span>
              </div>
              <div className="new-info-item">
                <span className="new-info-label">Coming Soon</span>
                <span className="new-info-value">Whale Memory, Social Memory</span>
              </div>
              <div className="new-info-item">
                <span className="new-info-label">Settlement</span>
                <span className="new-info-value">Instant USDC on Arc Testnet</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="new-how-it-works">
        <div className="new-how-container">
          <h2>How It Works</h2>
          <div className="new-steps">
            <div className="new-step">
              <div className="new-step-number">1</div>
              <h3>Pick a Signal</h3>
              <p>Select a live market anomaly or input custom parameters.</p>
            </div>
            <div className="new-step">
              <div className="new-step-number">2</div>
              <h3>Pay for Report</h3>
              <p>Pay a small USDC amount for exactly the report you want.</p>
            </div>
            <div className="new-step">
              <div className="new-step-number">3</div>
              <h3>View Comparison</h3>
              <p>View historical analog reports linked to your wallet.</p>
            </div>
          </div>
        </div>
      </section>

      {/* Who It's For */}
      <section className="new-audience">
        <div className="new-audience-container">
          <h2>Who It&apos;s For</h2>
          <div className="new-audience-grid">
            <div className="new-audience-card">
              <h3>Traders</h3>
              <p>Want historical context before making decisions—not price predictions.</p>
            </div>
            <div className="new-audience-card">
              <h3>Researchers</h3>
              <p>Need evidence and statistical distributions, not speculation.</p>
            </div>
            <div className="new-audience-card">
              <h3>AI Agents</h3>
              <p>Query via API, pay per call in USDC. {compactNumber(metrics.agent_unlocks)} agent unlocks on Arc testnet.</p>
            </div>
          </div>
        </div>
      </section>

      {/* Agent API */}
      <section className="new-agent-api">
        <div className="new-agent-container">
          <div className="new-agent-content">
            <h2>Agent-Native API</h2>
            <p>External agents can evaluate signals, settle payments, and receive structured JSON reports within their budget.</p>
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

      {/* Open Source */}
      <section className="new-open-source">
        <div className="new-open-source-container">
          <h2>Open Source Ecosystem</h2>
          <p>QMA is open-source. Build your own provider, customize the matching engine, or integrate the payment middleware.</p>
          <a href="https://github.com/hoanlv214/qma" target="_blank" rel="noopener noreferrer" className="new-btn new-btn-primary">
            View GitHub
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

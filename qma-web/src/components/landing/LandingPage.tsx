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

  const marqueeItems = [
    { value: compactNumber(metrics.unique_payers), label: "active wallets" },
    { value: compactNumber(metrics.paid_count), label: "reports unlocked" },
    { value: compactNumber(metrics.agent_unlocks), label: "API integrations" },
    { value: `${Number(metrics.revenue_usdc).toFixed(3)}`, label: "USDC volume" },
    { value: compactNumber(metrics.preview_count), label: "previews generated" },
    { value: compactNumber(metrics.full_count), label: "full reports delivered" },
  ];

  return (
    <main className="landing-shell">
      <nav className="landing-nav">
        <a href="/" className="logo-item qma-logo-item" title="QMA" onClick={(e) => e.preventDefault()}>
          <div className="logo-icon">QM</div>
          <div className="logo-text">QMA</div>
        </a>
        <div className="landing-nav-links">
          <button type="button" className="landing-nav-link text-btn" onClick={() => onNavigate("marketplace")}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"></path>
              <line x1="3" y1="6" x2="21" y2="6"></line>
              <path d="M16 10a4 4 0 0 1-8 0"></path>
            </svg>
            Marketplace
          </button>
          <a className="landing-nav-link" href={`${API_BASE_URL}/docs`} target="_blank" rel="noopener noreferrer">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
              <polyline points="10 9 9 9 8 9"></polyline>
            </svg>
            Docs
          </a>
          <a className="landing-nav-link" href="https://github.com/hoanlv214/qma" target="_blank" rel="noopener noreferrer">
            <svg viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.205 11.385.6.11.82-.26.82-.577v-2.234c-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22v3.293c0 .319.22.694.825.576C20.565 21.795 24 17.3 24 12c0-6.63-5.37-12-12-12z" />
            </svg>
            GitHub
          </a>
          <button type="button" className="landing-nav-link btn-green nav-cta text-btn" onClick={() => onNavigate("app")}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="7" y1="17" x2="17" y2="7"></line>
              <polyline points="7 7 17 7 17 17"></polyline>
            </svg>
            Launch App
          </button>
        </div>
      </nav>

      <section className="landing-hero">
        <div className="landing-kicker">Evidence-Based Market Research</div>
        <h1 className="landing-hero-title">See what happened the last time the market looked like this</h1>
        <p className="landing-hero-desc">
          QMA retrieves similar historical market situations and generates evidence-backed reports instead of
          trying to predict prices. Compare today's live signals with similar past events, and unlock detailed
          memory reports instantly using friction-free, pay-per-query payments.
        </p>
        <div className="landing-agent-note">
          <span className="landing-agent-note-label">Agent-native</span>
          <p className="landing-agent-note-text">QMA's ranking engine autonomously scores live funding anomalies and surfaces the signals most worth querying.</p>
        </div>
        <div className="landing-actions">
          <button type="button" className="btn-green landing-primary text-btn" onClick={() => onNavigate("app")}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="7" y1="17" x2="17" y2="7"></line>
              <polyline points="7 7 17 7 17 17"></polyline>
            </svg>
            Launch App
          </button>
          <a className="landing-secondary" href={`${API_BASE_URL}/docs`} target="_blank" rel="noopener noreferrer">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
              <polyline points="10 9 9 9 8 9"></polyline>
            </svg>
            Read Docs
          </a>
        </div>
      </section>

      {/* Partner Logos */}
      <section className="landing-partners-strip">
        <span className="section-eyebrow partners-label">Supported by</span>
        <div className="partners-logos">
          <a href="https://thecanteenapp.com/" target="_blank" rel="noopener noreferrer" title="Canteen">
            <img src="/assets/logos/canteen-logo.png" alt="Canteen" />
          </a>
          <a href="https://www.circle.com/" target="_blank" rel="noopener noreferrer" title="Circle">
            <img src="/assets/logos/circle-logo-white.svg" alt="Circle" />
          </a>
          <a href="https://www.arc.network/" target="_blank" rel="noopener noreferrer" title="Arc Testnet">
            <img src="/assets/logos/arc-logo-white.svg" alt="Arc Testnet" />
          </a>
        </div>
      </section>


      <section className="landing-traction-section" aria-label="Live QMA traction">
        <div className="section-eyebrow landing-traction-label">
          <span className="indicator-dot"></span>
          <span>Platform Activity</span>
        </div>
        <div className="landing-traction-strip">
          <div className="traction-marquee" aria-live="polite">
            <div className="traction-track" id="traction-track-a">
              {marqueeItems.map((item, idx) => (
                <div className="traction-item" key={`a-${idx}`}>
                  <strong className="traction-value">{item.value}</strong>
                  <span className="traction-label">{item.label}</span>
                </div>
              ))}
            </div>
            <div className="traction-track" id="traction-track-b" aria-hidden="true">
              {marqueeItems.map((item, idx) => (
                <div className="traction-item" key={`b-${idx}`}>
                  <strong className="traction-value">{item.value}</strong>
                  <span className="traction-label">{item.label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <div className="landing-grid">
        <article>
          <div className="feature-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </div>
          <h2>Market Memory Analysis</h2>
          <p className="landing-feature-desc">Instantly compare today's live signals against years of historical data to locate precise past
              situations that match the current setup.</p>
        </article>
        <article>
          <div className="feature-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="2" y="5" width="20" height="14" rx="2" />
              <path d="M2 10h20" />
            </svg>
          </div>
          <h2>Evidence-Backed Reports</h2>
          <p className="landing-feature-desc">Get detailed distribution outcomes, win rates, and similar event histories. Evaluate facts and
              statistical probabilities, not predictions.</p>
        </article>
        <article>
          <div className="feature-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
              <polyline points="10 17 15 12 10 7" />
              <line x1="15" y1="12" x2="3" y2="12" />
            </svg>
          </div>
          <h2>Persistent Unlocks</h2>
          <p className="landing-feature-desc">No monthly plans or hidden commitments. Reports are bound securely to your wallet credentials,
              allowing you to access them any time.</p>
        </article>
      </div>

      <section className="landing-proof">
        <div>
          <div className="section-eyebrow landing-section-label">Open intelligence marketplace</div>
          <h2>A Marketplace for Market Intelligence</h2>
          <p className="landing-proof-desc">
            QMA operates as a decentralized platform for historical market context. Independent intelligence
            providers package private datasets - from funding rate histories and order flow dynamics to whale
            metrics and social indicators - as paid APIs that users and autonomous agents can query instantly.
          </p>
        </div>
        <div className="landing-proof-card">
          <div className="landing-proof-item"><span className="landing-proof-label">Active Providers</span><strong className="landing-proof-value">Funding Memory, OI Memory</strong></div>
          <div className="landing-proof-item"><span className="landing-proof-label">Coming Soon</span><strong className="landing-proof-value">Whale Memory, Social Memory</strong></div>
          <div className="landing-proof-item"><span className="landing-proof-label">Approach</span><strong className="landing-proof-value">Compare today's market with past setups</strong></div>
          <div className="landing-proof-item"><span className="landing-proof-label">Pricing</span><strong className="landing-proof-value">Pay only for the report you want</strong></div>
          <div className="landing-proof-item"><span className="landing-proof-label">Access</span><strong className="landing-proof-value">Connect wallet to view unlocked reports</strong></div>
          <div className="landing-proof-item"><span className="landing-proof-label">Settlement</span><strong className="landing-proof-value">Instant USDC on Arc Testnet</strong></div>
          <div className="landing-proof-item proof-tech"><span className="landing-proof-label">Tech</span><strong className="landing-proof-value">Arc Testnet USDC / Circle Gateway / x402-style API</strong></div>
        </div>
      </section>

      <section className="landing-flow">
        <div className="section-eyebrow landing-section-label">How it works</div>
        <div className="landing-flow-steps">
          <div className="flow-step">
            <div className="flow-step-num">Step 1</div>
            <span className="flow-step-title">Pick a Signal</span>
            <p className="flow-step-desc">Select a live market anomaly or input custom parameters representing a current market situation.</p>
          </div>
          <div className="flow-step">
            <div className="flow-step-num">Step 2</div>
            <span className="flow-step-title">Pay for This Report</span>
            <p className="flow-step-desc">Pay a small USDC amount for exactly the report you want - no subscription, settled instantly on Arc.</p>
          </div>
          <div className="flow-step">
            <div className="flow-step-num">Step 3</div>
            <span className="flow-step-title">Read the Historical Comparison</span>
            <p className="flow-step-desc">View the historical analog report showing past outcomes and statistical context, linked permanently to your wallet.</p>
          </div>
        </div>
      </section>

      <section className="landing-audience">
        <div className="section-eyebrow landing-section-label">Who it's for</div>
        <div className="landing-audience-grid">
          <article className="landing-audience-card--traders">
            <strong className="landing-audience-title">Traders</strong>
            <p className="landing-audience-desc">Want historical context before making decisions - not price predictions.</p>
          </article>
          <article className="landing-audience-card--researchers">
            <strong className="landing-audience-title">Researchers</strong>
            <p className="landing-audience-desc">Need evidence and statistical distributions, not speculation.</p>
          </article>
          <article className="landing-audience-card--agents">
            <strong className="landing-audience-title">AI Agents</strong>
            <p className="landing-audience-desc">Query via API, pay per call in USDC. <span>{compactNumber(metrics.agent_unlocks)}</span> autonomous agent unlocks logged on Arc testnet.</p>
          </article>
        </div>
      </section>

      <section className="landing-agent-api">
        <div>
          <div className="section-eyebrow landing-section-label">Agent-native API</div>
          <h2>External agents can buy reports without using the dashboard</h2>
          <p>
            A buyer agent can evaluate a ranked signal, create an invoice, settle the x402-style payment,
            and receive a structured JSON report within its budget.
          </p>
          <div className="landing-actions">
            <a className="btn-green landing-primary" href={`${API_BASE_URL}/docs`} target="_blank" rel="noopener noreferrer">Open API Docs</a>
            <a className="landing-secondary" href="https://github.com/hoanlv214/qma/blob/main/examples/README.md" target="_blank" rel="noopener noreferrer">View Agent Example</a>
          </div>
        </div>
        <pre className="agent-terminal" aria-label="Agent buyer flow example"><code><span className="t-prompt">$</span> <span className="t-cmd">npm run agent:dry</span>
<span className="t-key">pick:</span>    <span className="t-val">H</span>  score=<span className="t-num">41</span>  tier=<span className="t-badge">preview</span>
<span className="t-key">invoice:</span> <span className="t-dim">inv_...</span>  amount=<span className="t-green">0.001 USDC</span>
<span className="t-key">pay:</span>     x402 authorization <span className="t-green">accepted</span>
<span className="t-key">result:</span>  JSON report <span className="t-accent">unlocked ok</span></code></pre>
      </section>

      <section className="landing-builders">
        <div>
          <div className="section-eyebrow landing-section-label">For Creators and Researchers</div>
          <h2>Expose Private Data as Paid APIs</h2>
        </div>
        <div>
          <p className="landing-builders-desc">
            QMA provides a complete, reusable toolkit for creators who want to monetize proprietary data.
            Package your intelligence into a query-based API, define preview and full report pricing, and let
            QMA handle the wallet-based entitlement and instant micropayment tracking.
          </p>
          <div className="landing-actions" style={{ marginTop: 24 }}>
            <button type="button" className="btn-green landing-primary text-btn" onClick={() => onNavigate("marketplace")}>Become a Provider</button>
            <a className="landing-secondary" href={`${API_BASE_URL}/docs`} target="_blank" rel="noopener noreferrer">View API Docs</a>
          </div>
        </div>
      </section>

      <section className="landing-source" id="source-code">
        <div className="section-eyebrow landing-section-label">Open Source Ecosystem</div>
        <p className="landing-source-desc">
          QMA is open-source. Build your own provider, customize the analog matching engine, or integrate the
          payment middleware. The repository includes everything you need to run your own local marketplace and
          crawl custom historical datasets.
        </p>
        <div className="landing-actions" style={{ marginTop: 20 }}>
          <a className="btn-green landing-primary" href="https://github.com/hoanlv214/qma" target="_blank" rel="noopener noreferrer">View GitHub Repository</a>
        </div>
      </section>

      <footer className="landing-footer">
        <div className="landing-footer-cols landing-footer-cols--4">
          <div className="footer-col-brand">
            <a href="/" className="logo-item qma-logo-item" title="QMA" onClick={(e) => e.preventDefault()}>
              <div className="logo-icon">QM</div>
              <div className="logo-text">QMA</div>
            </a>
            <p className="footer-brand-desc">Historical market intelligence. Evidence-backed reports from past analog events, not predictions.</p>
            <div className="landing-socials footer-socials" aria-label="QMA footer social links">
              <a className="social-link" href="http://x.com/hoanlv21" target="_blank" rel="noopener noreferrer" title="X (Twitter)">
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                </svg>
              </a>
              <a className="social-link" href="https://github.com/hoanlv214/qma" target="_blank" rel="noopener noreferrer" title="GitHub">
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.205 11.385.6.11.82-.26.82-.577v-2.234c-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22v3.293c0 .319.22.694.825.576C20.565 21.795 24 17.3 24 12c0-6.63-5.37-12-12-12z" />
                </svg>
              </a>
              <a className="social-link" href="https://discordapp.com/users/711257217483014206" target="_blank" rel="noopener noreferrer" title="Discord">
                <svg viewBox="0 0 127.14 96.36" fill="currentColor">
                  <path d="M107.7,8.07A105.15,105.15,0,0,0,77.26,0a77.19,77.19,0,0,0-3.3,6.83A96.67,96.67,0,0,0,53.22,6.83,77.19,77.19,0,0,0,49.88,0,105.15,105.15,0,0,0,19.44,8.07C3.66,31.58-1.86,54.65,1,77.53A105.73,105.73,0,0,0,32,96.36a77.7,77.7,0,0,0,6.63-10.85,68.43,68.43,0,0,1-10.5-5c.9-.65,1.76-1.34,2.58-2.07a75.79,75.79,0,0,0,73,0c.82.73,1.68,1.42,2.58,2.07a68.43,68.43,0,0,1-10.5,5,77.7,77.7,0,0,0,6.63,10.85,105.73,105.73,0,0,0,31-18.83C129.87,54.65,124.34,31.58,107.7,8.07ZM42.45,65.69C36.18,65.69,31,60,31,53S36.18,40.36,42.45,40.36,53.83,46,53.83,53,48.72,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.24,60,73.24,53S78.41,40.36,84.69,40.36,96.07,46,96.07,53,91,65.69,84.69,65.69Z" />
                </svg>
              </a>
            </div>
          </div>
          <div className="landing-footer-col">
            <h3>Product</h3>
            <button type="button" className="text-btn footer-link-btn" onClick={() => onNavigate("app")}>Agent Picks</button>
            <button type="button" className="text-btn footer-link-btn" onClick={() => onNavigate("app")}>Preview Reports</button>
            <button type="button" className="text-btn footer-link-btn" onClick={() => onNavigate("app")}>Full Reports</button>
            <button type="button" className="text-btn footer-link-btn" onClick={() => onNavigate("profile")}>Wallet History</button>
          </div>
          <div className="landing-footer-col">
            <h3>Platform</h3>
            <a href="#source-code">Paid Intelligence Kit</a>
            <a href={`${API_BASE_URL}/api/v1/providers`} target="_blank" rel="noopener noreferrer">Provider API</a>
            <a href={`${API_BASE_URL}/docs`} target="_blank" rel="noopener noreferrer">API Docs</a>
            <a href="https://testnet.arcscan.app/" target="_blank" rel="noopener noreferrer">Arcscan Explorer</a>
          </div>
          <div className="landing-footer-col">
            <h3>Developers</h3>
            <a href="https://github.com/hoanlv214/qma" target="_blank" rel="noopener noreferrer">GitHub Repository</a>
            <a href="#source-code">Sample Data</a>
            <a href={`${API_BASE_URL}/openapi.json`} target="_blank" rel="noopener noreferrer">OpenAPI Spec</a>
          </div>
        </div>

        <div className="landing-footer-bottom">
          <span>2026 QMA. All rights reserved. Historical analogs only. Not financial advice. Running on Arc Testnet.</span>
          <span className="landing-status-dot">Arc Testnet live</span>
        </div>
      </footer>
    </main>
  );
}

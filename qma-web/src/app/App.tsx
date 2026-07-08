import { useMemo, useState } from "react";
import { AgentBuyerDemo } from "../components/agent/AgentBuyerDemo";
import { MarketplaceReview } from "../components/marketplace/MarketplaceReview";
import { PaywallPanel } from "../components/paywall/PaywallPanel";
import { ProfileOrdersPage } from "../components/profile/ProfileOrdersPage";
import { ReportWorkspace } from "../components/reports/ReportWorkspace";
import { FundArcWalletModal } from "../components/wallet/FundArcWalletModal";
import { WalletDropdown } from "../components/wallet/WalletDropdown";
import { routeFromPath, type QmaRoute } from "./routes";

export function App() {
  const initialRoute = useMemo(() => routeFromPath(window.location.pathname), []);
  const [route, setRoute] = useState<QmaRoute>(initialRoute);
  const [fundingOpen, setFundingOpen] = useState(false);

  const navigate = (next: QmaRoute) => {
    setRoute(next);
    window.history.pushState({}, "", next === "app" ? "/app" : `/${next}`);
  };

  return (
    <div className="qma-shell">
      <header className="qma-topbar">
        <button className="qma-brand" type="button" onClick={() => navigate("app")}>
          QMA
        </button>
        <nav className="qma-nav" aria-label="QMA sections">
          <button type="button" className={route === "app" ? "active" : ""} onClick={() => navigate("app")}>
            Signals
          </button>
          <button type="button" className={route === "profile" ? "active" : ""} onClick={() => navigate("profile")}>
            Profile
          </button>
          <button type="button" className={route === "marketplace" ? "active" : ""} onClick={() => navigate("marketplace")}>
            Marketplace
          </button>
        </nav>
        <WalletDropdown onFundArc={() => setFundingOpen(true)} />
      </header>

      {route === "app" ? (
        <main className="qma-workspace">
          <AgentBuyerDemo />
          <ReportWorkspace />
          <PaywallPanel />
        </main>
      ) : null}
      {route === "profile" ? <ProfileOrdersPage /> : null}
      {route === "marketplace" ? <MarketplaceReview /> : null}

      <FundArcWalletModal open={fundingOpen} onClose={() => setFundingOpen(false)} />
    </div>
  );
}

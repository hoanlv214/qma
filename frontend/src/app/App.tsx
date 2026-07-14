import { useMemo, useState, useEffect } from "react";
import { LandingPage } from "../components/landing/LandingPage";
import { AppPage } from "../components/reports/AppPage";
import { MarketplaceReview } from "../components/marketplace/MarketplaceReview";
import { ProfileOrdersPage } from "../components/profile/ProfileOrdersPage";
import { routeFromPath, type QmaRoute } from "./routes";
import { WalletProvider } from "../state/walletStore";

export function App() {
  const initialRoute = useMemo(() => routeFromPath(window.location.pathname), []);
  const [route, setRoute] = useState<QmaRoute>(initialRoute);

  const navigate = (next: QmaRoute) => {
    setRoute(next);
    window.history.pushState(
      {},
      "",
      next === "landing" ? "/" : next === "app" ? "/app" : `/${next}`
    );
  };

  // Sync window popstate (back/forward buttons)
  useEffect(() => {
    const handlePopState = () => {
      setRoute(routeFromPath(window.location.pathname));
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  // Update body class depending on the current route
  useEffect(() => {
    // Clear all possible body classes first
    document.body.classList.remove("landing-body", "body", "marketplace-body", "profile-body");

    if (route === "landing") {
      document.body.classList.add("landing-body");
    } else if (route === "app") {
      document.body.classList.add("body");
    } else if (route === "marketplace") {
      document.body.classList.add("marketplace-body");
    } else if (route === "profile") {
      document.body.classList.add("profile-body");
    }
  }, [route]);

  return (
    <WalletProvider>
      {route === "landing" && <LandingPage onNavigate={navigate} />}
      {route === "app" && <AppPage onNavigate={navigate} />}
      {route === "marketplace" && <MarketplaceReview onNavigate={navigate} />}
      {route === "profile" && <ProfileOrdersPage />}
    </WalletProvider>
  );
}

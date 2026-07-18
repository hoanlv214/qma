import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { LandingPage } from "../components/landing/LandingPage";
import { AppPage } from "../components/reports/AppPage";
import { MarketplaceReview } from "../components/marketplace/MarketplaceReview";
import { ProfileOrdersPage } from "../components/profile/ProfileOrdersPage";
import { TractionPage } from "../components/traction/TractionPage";
import { pathForRoute, routeFromPath, type QmaRoute } from "./routes";
import { WalletProvider } from "../state/walletStore";

const ApiDocsPage = lazy(() => import("../components/api-docs/ApiDocsPage").then((module) => ({ default: module.ApiDocsPage })));

export function App() {
  const initialRoute = useMemo(() => routeFromPath(window.location.pathname), []);
  const [route, setRoute] = useState<QmaRoute>(initialRoute);

  const navigate = (next: QmaRoute) => {
    setRoute(next);
    window.history.pushState({}, "", pathForRoute(next));
  };

  useEffect(() => {
    const handlePopState = () => {
      setRoute(routeFromPath(window.location.pathname));
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    document.body.classList.remove("landing-body", "body", "marketplace-body", "profile-body", "traction-body");

    if (route === "landing") {
      document.body.classList.add("landing-body");
    } else if (route === "app") {
      document.body.classList.add("body");
    } else if (route === "marketplace") {
      document.body.classList.add("marketplace-body");
    } else if (route === "profile") {
      document.body.classList.add("profile-body");
    } else if (route === "traction") {
      document.body.classList.add("traction-body");
    }
  }, [route]);

  return (
    <WalletProvider>
      {route === "landing" && <LandingPage onNavigate={navigate} />}
      {route === "app" && <AppPage onNavigate={navigate} />}
      {route === "marketplace" && <MarketplaceReview onNavigate={navigate} />}
      {route === "profile" && <ProfileOrdersPage />}
      {route === "traction" && <TractionPage onNavigate={navigate} />}
      {route === "docs" && (
        <Suspense fallback={null}>
          <ApiDocsPage />
        </Suspense>
      )}
    </WalletProvider>
  );
}

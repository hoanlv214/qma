export type QmaRoute = "landing" | "app" | "profile" | "marketplace" | "traction" | "docs";

export function routeFromPath(pathname: string): QmaRoute {
  const clean = pathname.replace(/\/$/, "");
  if (clean === "" || clean === "/index.html") return "landing";
  if (clean.startsWith("/profile") || clean.startsWith("/user")) return "profile";
  if (clean.startsWith("/marketplace")) return "marketplace";
  if (clean.startsWith("/traction") || clean.startsWith("/ledger")) return "traction";
  if (clean.startsWith("/docs")) return "docs";
  return "app";
}

export function pathForRoute(route: QmaRoute): string {
  if (route === "profile") return "/profile";
  if (route === "marketplace") return "/marketplace";
  if (route === "traction") return "/traction";
  if (route === "docs") return "/docs";
  if (route === "app") return "/app";
  return "/";
}


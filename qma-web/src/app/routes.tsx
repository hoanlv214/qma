export type QmaRoute = "landing" | "app" | "profile" | "marketplace";

export function routeFromPath(pathname: string): QmaRoute {
  const clean = pathname.replace(/\/$/, "");
  if (clean === "" || clean === "/index.html") return "landing";
  if (clean.startsWith("/profile") || clean.startsWith("/user")) return "profile";
  if (clean.startsWith("/marketplace")) return "marketplace";
  return "app";
}

export function pathForRoute(route: QmaRoute): string {
  if (route === "profile") return "/profile";
  if (route === "marketplace") return "/marketplace";
  if (route === "app") return "/app";
  return "/";
}


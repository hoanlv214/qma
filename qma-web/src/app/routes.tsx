export type QmaRoute = "app" | "profile" | "marketplace";

export function routeFromPath(pathname: string): QmaRoute {
  if (pathname.startsWith("/profile") || pathname.startsWith("/user")) return "profile";
  if (pathname.startsWith("/marketplace")) return "marketplace";
  return "app";
}

export function pathForRoute(route: QmaRoute): string {
  if (route === "profile") return "/profile";
  if (route === "marketplace") return "/marketplace";
  return "/app";
}

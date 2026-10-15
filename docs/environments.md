# QMA Environment Architecture: Local Development & Vercel Proxy

This guide documents the active runtime architecture and environment configuration of **QMA**.

---

## 1. Environment Matrix

| Dimension | Local Development (`dev`) | Production Deployment (`prod`) |
|---|---|---|
| **Frontend Web App** | `http://localhost:5173` | `https://qma-three.vercel.app` |
| **Public API Base** | `http://localhost:8000` | `https://qma-three.vercel.app` (Vercel Reverse Proxy) |
| **MCP Endpoint** | `http://localhost:8000/mcp` | `https://qma-three.vercel.app/mcp` |
| **Backend Engine** | Local FastAPI (`http://localhost:8000`) | Local FastAPI tunneled via `vercel.json` rewrites |
| **Arc Gateway Relay** | Local Node sidecar (`http://localhost:3000`) | Local Node sidecar (`http://localhost:3000`) |
| **Blockchain Network** | Arc Mainnet (Chain 5042) / Testnet (5042002) | Arc Mainnet (Chain 5042) / Testnet (5042002) |
| **Network Profile Config** | `config/networks.json` | `config/networks.json` |
| **Business & Service Config**| `config/app.json` | `config/app.json` |
| **Storage Engine** | Local PostgreSQL or Supabase | PostgreSQL / Supabase |

---

## 2. Configuration Profiles

### Profile A: Local Development (`.env` in repo root)

```bash
# Network Mode (toggle between mainnet and testnet)
QMA_NETWORK_MODE=mainnet
VITE_NETWORK_MODE=mainnet

# Local service endpoints
QMA_ARC_GATEWAY_URL=http://127.0.0.1:3000
QMA_API_URL=http://127.0.0.1:8000
API_BASE_URL=http://127.0.0.1:8000

# Storage
QMA_STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://postgres:...@localhost:5432/qma
```

---

### Profile B: Production Deployment (Vercel Proxy)

In production, frontend is deployed on Vercel at `https://qma-three.vercel.app`.
To keep backend infrastructure secure and concealed, all public traffic routes through Vercel's edge network using rewrites configured in `vercel.json`:

```json
{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://<your-tunnel-endpoint>/api/:path*" },
    { "source": "/mcp", "destination": "https://<your-tunnel-endpoint>/mcp" },
    { "source": "/mcp/:path*", "destination": "https://<your-tunnel-endpoint>/mcp/:path*" },
    { "source": "/health", "destination": "https://<your-tunnel-endpoint>/health" },
    { "source": "/healthz", "destination": "https://<your-tunnel-endpoint>/healthz" },
    { "source": "/docs", "destination": "https://<your-tunnel-endpoint>/docs" },
    { "source": "/:path*", "destination": "/" }
  ]
}
```

Public clients (browser, Claude, ChatGPT, Circle Marketplace, Agent CLI) interface exclusively with `https://qma-three.vercel.app`.

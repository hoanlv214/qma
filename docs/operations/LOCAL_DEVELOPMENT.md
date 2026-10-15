# Local Development & Multi-Environment Control Center

This document covers local operator tooling for developing, testing, and debugging QMA on a local workstation.

---

## 1. Unified Control Center Dashboard (`:7700`)

The project includes a standalone FastAPI multi-environment orchestrator dashboard running at `http://localhost:7700`.

To launch:
```powershell
control_center.bat
```
*(or run `.venv\Scripts\python.exe scripts\dev_control_center.py`)*

### Features:
- **Port Collision Guard**: Scans active ports (`8000`, `8001`, `3000`, `5173`, `5432`, `7700`). Shows process name (`python.exe`, `node.exe`), PID, and RAM usage.
- **Custom Port Inspector**: Enter any port (e.g. `8080`, `5000`) to inspect process details and force-kill stuck processes.
- **Batch Port Terminator**: `🧹 Free All Standard Ports` button frees 8000, 8001, 3000, and 5173 with one click.
- **1-Click Network Switcher**: Toggle DEV between Mainnet and Testnet instantly with automatic backend hot-reload.
- **Live Event Stream**: Real-time terminal log drawer.

---

## 2. Launching Local Environments

### A. Production Suite (24/7 for Vercel via Ngrok)
Runs the production configuration locally to feed the public Vercel frontend:
```powershell
start_all_services.bat
```
- **FastAPI Backend**: `http://localhost:8000` (Mainnet mode, `qma_mainnet` database, `reload=false`)
- **Arc Gateway**: `http://localhost:3000` (Node/Express relayer)
- **Agent Worker**: Background processing engine
- **Ngrok Static Tunnel**: Forwards `https://driveway-expansive-onyx.ngrok-free.dev` -> `http://localhost:8000`

### B. Developer Environment (Local Workspace)
Runs a sandboxed developer instance that will not conflict with or restart the production tunnel:
```powershell
start_dev.bat
```
- **FastAPI DEV Backend**: `http://localhost:8001` (Hot-reload enabled, `qma` testnet database)
- **Vite DEV Frontend**: `http://localhost:5173` (Proxies API calls to `:8001`)

---

## 3. Database Administration

QMA utilizes PostgreSQL with 16 forward-only migrations.

Apply migrations manually:
```powershell
# Apply to Mainnet database
.venv\Scripts\python.exe scripts\apply_migrations.py --network=mainnet

# Apply to Testnet database
.venv\Scripts\python.exe scripts\apply_migrations.py --network=testnet
```

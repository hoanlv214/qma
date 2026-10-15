#!/usr/bin/env python3
"""QMA Multi-Environment Control Center & Project Port Orchestrator.

Manages Local PROD (Port 8000, Mainnet 24/7 for Ngrok/Vercel) and DEV (Port 8001, Testnet/Mainnet).
Provides port collision detection, multi-project process inspector, custom port killer,
and a real-time web dashboard on http://localhost:7700.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import time
import json
import asyncio
import subprocess
from typing import Dict, Any, Optional, List
from collections import deque

import psutil
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

PYTHON_EXE = str(ROOT_DIR / ".venv" / "Scripts" / "python.exe")
if not os.path.exists(PYTHON_EXE):
    PYTHON_EXE = sys.executable

app = FastAPI(title="QMA Multi-Environment Control Center", version="2.0.0")

# Circular log buffers (max 500 lines per service)
SERVICE_LOGS: Dict[str, deque] = {
    "prod_backend": deque(maxlen=500),
    "dev_backend": deque(maxlen=500),
    "arc_gateway": deque(maxlen=500),
    "agent_worker": deque(maxlen=500),
    "frontend_dev": deque(maxlen=500),
    "ngrok_tunnel": deque(maxlen=500),
    "system": deque(maxlen=500),
}

MANAGED_PROCESSES: Dict[str, subprocess.Popen] = {}
DEV_NETWORK_MODE = "testnet"
CONFIG = {
    "dev_backend_port": 8001,
    "dev_frontend_port": 5173,
    "frontend_proxy_target": "http://localhost:8001",
}

def append_log(service_id: str, line: str):
    if service_id not in SERVICE_LOGS:
        SERVICE_LOGS[service_id] = deque(maxlen=500)
    ts = time.strftime("%H:%M:%S")
    formatted = f"[{ts}] {line.rstrip()}"
    SERVICE_LOGS[service_id].append(formatted)
    SERVICE_LOGS["system"].append(f"[{service_id.upper()}] {formatted}")

def find_pid_by_port(port: int) -> Optional[int]:
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" and conn.laddr and conn.laddr.port == port:
                return conn.pid
    except Exception:
        pass
    return None

def get_process_info(pid: Optional[int]) -> Dict[str, Any]:
    if not pid:
        return {"running": False, "pid": None, "name": None, "exe": None, "cmdline": None, "cpu": 0, "mem_mb": 0}
    try:
        p = psutil.Process(pid)
        try:
            exe = p.exe()
        except Exception:
            exe = None
        try:
            cmdline = " ".join(p.cmdline()[:5])
        except Exception:
            cmdline = None
        return {
            "running": True,
            "pid": pid,
            "name": p.name(),
            "exe": exe,
            "cmdline": cmdline,
            "cpu": round(p.cpu_percent(), 1),
            "mem_mb": p.memory_info().rss // (1024 * 1024),
            "create_time": p.create_time(),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"running": False, "pid": None, "name": None, "exe": None, "cmdline": None, "cpu": 0, "mem_mb": 0}

def kill_process_tree(pid: int) -> bool:
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except Exception:
                pass
        parent.kill()
        return True
    except Exception:
        return False

def check_postgres_databases() -> Dict[str, Any]:
    res = {
        "connected": False,
        "mainnet_db": {"name": "qma_mainnet", "tables": 0, "events": 0, "invoices": 0},
        "testnet_db": {"name": "qma", "tables": 0, "events": 0, "invoices": 0},
    }
    try:
        import psycopg2
        # Check mainnet
        try:
            c1 = psycopg2.connect("postgresql://postgres:Hoanlv%40214@localhost:5432/qma_mainnet", connect_timeout=2)
            with c1.cursor() as cur:
                cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
                res["mainnet_db"]["tables"] = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM public.qma_payment_events;")
                res["mainnet_db"]["events"] = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM public.qma_invoices;")
                res["mainnet_db"]["invoices"] = cur.fetchone()[0]
            c1.close()
            res["connected"] = True
        except Exception:
            pass

        # Check testnet
        try:
            c2 = psycopg2.connect("postgresql://postgres:Hoanlv%40214@localhost:5432/qma", connect_timeout=2)
            with c2.cursor() as cur:
                cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
                res["testnet_db"]["tables"] = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM public.qma_payment_events;")
                res["testnet_db"]["events"] = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM public.qma_invoices;")
                res["testnet_db"]["invoices"] = cur.fetchone()[0]
            c2.close()
            res["connected"] = True
        except Exception:
            pass
    except Exception:
        pass
    return res

def check_ngrok_public_url() -> Optional[str]:
    import urllib.request
    try:
        req = urllib.request.Request("http://127.0.0.1:4040/api/tunnels", headers={"User-Agent": "QMA-Control-Center"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode())
            tunnels = data.get("tunnels", [])
            for t in tunnels:
                if t.get("proto") == "https":
                    return t.get("public_url")
            if tunnels:
                return tunnels[0].get("public_url")
    except Exception:
        pass
    return "https://driveway-expansive-onyx.ngrok-free.dev"

def find_pid_by_name(process_name: str) -> Optional[int]:
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["name"] and p.info["name"].lower() == process_name.lower():
                return p.info["pid"]
        except Exception:
            pass
    return None

@app.get("/api/status")
async def get_system_status():
    dev_port = CONFIG["dev_backend_port"]
    fe_port = CONFIG["dev_frontend_port"]
    monitored_ports = [8000, dev_port, 3000, fe_port, 5432, 4040, 7700]
    port_status = {}
    for pt in monitored_ports:
        pid = find_pid_by_port(pt)
        port_status[pt] = get_process_info(pid)

    services = {
        "prod_backend": {
            "name": "PROD Backend (Vercel/Ngrok 24/7)",
            "port": 8000,
            "mode": "mainnet",
            "db": "qma_mainnet (Genesis)",
            "reload": False,
            "info": port_status[8000],
            "target": "https://driveway-expansive-onyx.ngrok-free.dev",
        },
        "dev_backend": {
            "name": "DEV Backend (Local Workspace)",
            "port": dev_port,
            "mode": DEV_NETWORK_MODE,
            "db": "qma" if DEV_NETWORK_MODE == "testnet" else "qma_mainnet",
            "reload": True,
            "info": port_status[dev_port],
            "target": f"http://localhost:{dev_port}",
        },
        "arc_gateway": {
            "name": "Arc Gateway (Node/Express)",
            "port": 3000,
            "info": port_status[3000],
            "target": "http://localhost:3000",
        },
        "frontend_dev": {
            "name": "Vite Frontend Dev",
            "port": fe_port,
            "info": port_status[fe_port],
            "target": f"http://localhost:{fe_port}",
            "proxy_target": CONFIG["frontend_proxy_target"],
        },
        "ngrok_tunnel": {
            "name": "Ngrok Static Tunnel",
            "port": 8000,
            "info": {"running": bool(find_pid_by_name("ngrok.exe"))},
            "public_url": check_ngrok_public_url(),
        }
    }

    db_stats = check_postgres_databases()

    return {
        "timestamp": time.time(),
        "dev_network_mode": DEV_NETWORK_MODE,
        "config": CONFIG,
        "ports": port_status,
        "services": services,
        "databases": db_stats,
    }

@app.post("/api/services/{service_id}/start")
async def start_service(service_id: str):
    global DEV_NETWORK_MODE, CONFIG
    append_log(service_id, f"Initiating start command for {service_id}...")

    if service_id == "prod_backend":
        pid = find_pid_by_port(8000)
        if pid:
            return {"success": False, "message": f"Port 8000 already in use by PID {pid}"}
        env = os.environ.copy()
        env["QMA_NETWORK_MODE"] = "mainnet"
        env["QMA_STORAGE_BACKEND"] = "postgres"
        env["QMA_BACKEND_PORT"] = "8000"
        env["QMA_BACKEND_RELOAD"] = "false"
        env["DATABASE_URL"] = "postgresql://postgres:Hoanlv%40214@localhost:5432/qma_mainnet"
        cmd = [PYTHON_EXE, str(ROOT_DIR / "scripts" / "run_backend_local.py"), "--port=8000", "--no-reload"]
        proc = subprocess.Popen(cmd, cwd=str(ROOT_DIR), env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
        MANAGED_PROCESSES["prod_backend"] = proc
        append_log(service_id, f"Launched Prod Backend on port 8000 (PID {proc.pid})")
        return {"success": True, "pid": proc.pid}

    elif service_id == "dev_backend":
        dev_port = CONFIG["dev_backend_port"]
        pid = find_pid_by_port(dev_port)
        if pid:
            return {"success": False, "message": f"Port {dev_port} already in use by PID {pid}"}
        env = os.environ.copy()
        env["QMA_NETWORK_MODE"] = DEV_NETWORK_MODE
        env["QMA_STORAGE_BACKEND"] = "postgres"
        env["QMA_BACKEND_PORT"] = str(dev_port)
        env["QMA_BACKEND_RELOAD"] = "true"
        target_db = "qma" if DEV_NETWORK_MODE == "testnet" else "qma_mainnet"
        env["DATABASE_URL"] = f"postgresql://postgres:Hoanlv%40214@localhost:5432/{target_db}"
        cmd = [PYTHON_EXE, str(ROOT_DIR / "scripts" / "run_backend_local.py"), f"--port={dev_port}", "--reload"]
        proc = subprocess.Popen(cmd, cwd=str(ROOT_DIR), env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
        MANAGED_PROCESSES["dev_backend"] = proc
        append_log(service_id, f"Launched Dev Backend on port {dev_port} in {DEV_NETWORK_MODE} mode (PID {proc.pid})")
        return {"success": True, "pid": proc.pid}

    elif service_id == "arc_gateway":
        pid = find_pid_by_port(3000)
        if pid:
            return {"success": False, "message": f"Port 3000 already in use by PID {pid}"}
        cmd = ["bun", "start"]
        gw_dir = ROOT_DIR / "arc_gateway"
        proc = subprocess.Popen(cmd, cwd=str(gw_dir), shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
        MANAGED_PROCESSES["arc_gateway"] = proc
        append_log(service_id, f"Launched Arc Gateway on port 3000 (PID {proc.pid})")
        return {"success": True, "pid": proc.pid}

    elif service_id == "frontend_dev":
        fe_port = CONFIG["dev_frontend_port"]
        pid = find_pid_by_port(fe_port)
        if pid:
            return {"success": False, "message": f"Port {fe_port} already in use by PID {pid}"}
        env = os.environ.copy()
        env["VITE_BACKEND_URL"] = CONFIG["frontend_proxy_target"]
        cmd = ["npm", "run", "dev", "--", "--port", str(fe_port)]
        fe_dir = ROOT_DIR / "frontend"
        proc = subprocess.Popen(cmd, cwd=str(fe_dir), env=env, shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
        MANAGED_PROCESSES["frontend_dev"] = proc
        append_log(service_id, f"Launched Frontend Dev on port {fe_port} proxying to {CONFIG['frontend_proxy_target']} (PID {proc.pid})")
        return {"success": True, "pid": proc.pid}

    elif service_id == "ngrok_tunnel":
        ngrok_pid = find_pid_by_name("ngrok.exe")
        if ngrok_pid:
            return {"success": True, "message": f"Ngrok already running (PID {ngrok_pid})"}
        cmd = ["ngrok", "http", "8000", "--url", "https://driveway-expansive-onyx.ngrok-free.dev"]
        proc = subprocess.Popen(cmd, cwd=str(ROOT_DIR), creationflags=subprocess.CREATE_NEW_CONSOLE)
        MANAGED_PROCESSES["ngrok_tunnel"] = proc
        append_log(service_id, f"Launched Ngrok Tunnel for port 8000 (PID {proc.pid})")
        return {"success": True, "pid": proc.pid}

    raise HTTPException(status_code=404, detail="Service not found")

@app.post("/api/services/{service_id}/stop")
async def stop_service(service_id: str):
    append_log(service_id, f"Stopping service {service_id}...")
    target_port = {
        "prod_backend": 8000,
        "dev_backend": CONFIG["dev_backend_port"],
        "arc_gateway": 3000,
        "frontend_dev": CONFIG["dev_frontend_port"],
    }.get(service_id)

    stopped = False
    if target_port:
        pid = find_pid_by_port(target_port)
        if pid:
            stopped = kill_process_tree(pid)
            append_log(service_id, f"Terminated PID {pid} listening on port {target_port}")

    if service_id == "ngrok_tunnel":
        pid = find_pid_by_name("ngrok.exe")
        if pid:
            stopped = kill_process_tree(pid)
            append_log(service_id, f"Terminated Ngrok (PID {pid})")

    if service_id in MANAGED_PROCESSES:
        p = MANAGED_PROCESSES.pop(service_id)
        try:
            p.kill()
            stopped = True
        except Exception:
            pass

    return {"success": stopped, "service": service_id}

@app.post("/api/services/{service_id}/restart")
async def restart_service(service_id: str):
    await stop_service(service_id)
    await asyncio.sleep(1.2)
    return await start_service(service_id)

@app.post("/api/dev/switch-network")
async def switch_dev_network(request: Request):
    global DEV_NETWORK_MODE
    body = await request.json()
    new_mode = str(body.get("mode", "")).strip().lower()
    if new_mode not in ("mainnet", "testnet"):
        raise HTTPException(status_code=400, detail="Invalid network mode. Choose 'mainnet' or 'testnet'.")

    DEV_NETWORK_MODE = new_mode
    append_log("dev_backend", f"Switched Dev Network Mode to: {new_mode.upper()}")

    pid = find_pid_by_port(CONFIG["dev_backend_port"])
    if pid:
        append_log("dev_backend", "Auto-restarting Dev Backend to apply new network...")
        await restart_service("dev_backend")

    return {"success": True, "mode": DEV_NETWORK_MODE}

@app.post("/api/config/update")
async def update_config(request: Request):
    global CONFIG
    body = await request.json()
    if "dev_backend_port" in body:
        CONFIG["dev_backend_port"] = int(body["dev_backend_port"])
    if "dev_frontend_port" in body:
        CONFIG["dev_frontend_port"] = int(body["dev_frontend_port"])
    if "frontend_proxy_target" in body:
        CONFIG["frontend_proxy_target"] = str(body["frontend_proxy_target"])
    append_log("system", f"Updated configuration: {CONFIG}")
    return {"success": True, "config": CONFIG}

@app.post("/api/ports/inspect/{port}")
async def inspect_port(port: int):
    pid = find_pid_by_port(port)
    if not pid:
        return {"listening": False, "port": port, "message": f"Port {port} is FREE (no process listening)"}
    info = get_process_info(pid)
    info["listening"] = True
    info["port"] = port
    return info

@app.post("/api/ports/kill/{port}")
async def kill_port(port: int):
    pid = find_pid_by_port(port)
    if not pid:
        return {"success": False, "message": f"No process listening on port {port}"}
    info = get_process_info(pid)
    killed = kill_process_tree(pid)
    append_log("system", f"⚡ Force-killed PID {pid} ({info.get('name')}) occupying port {port}")
    return {"success": killed, "port": port, "pid": pid, "process_name": info.get("name")}

@app.post("/api/actions/free-all-ports")
async def free_all_ports():
    target_ports = [8000, CONFIG["dev_backend_port"], 3000, CONFIG["dev_frontend_port"]]
    results = {}
    for pt in target_ports:
        pid = find_pid_by_port(pt)
        if pid:
            killed = kill_process_tree(pid)
            results[pt] = {"killed": killed, "pid": pid}
            append_log("system", f"Freed port {pt} (PID {pid})")
        else:
            results[pt] = {"killed": False, "message": "Already free"}
    return {"success": True, "details": results}

@app.post("/api/migrations/run")
async def run_migrations(request: Request):
    body = await request.json()
    target_net = str(body.get("network", "mainnet")).lower()
    append_log("system", f"Starting database migrations for {target_net.upper()}...")
    cmd = [PYTHON_EXE, str(ROOT_DIR / "scripts" / "apply_migrations.py"), f"--network={target_net}"]
    try:
        res = subprocess.run(cmd, cwd=str(ROOT_DIR), capture_output=True, text=True, timeout=60)
        append_log("system", f"Migrations Output:\n{res.stdout}")
        if res.stderr:
            append_log("system", f"Migrations Error:\n{res.stderr}")
        return {"success": res.returncode == 0, "output": res.stdout, "errors": res.stderr}
    except Exception as exc:
        append_log("system", f"Migration failed: {exc}")
        return {"success": False, "error": str(exc)}

@app.get("/api/logs")
async def get_all_logs():
    return {"logs": list(SERVICE_LOGS.get("system", []))}

@app.post("/api/logs/clear")
async def clear_logs():
    for buf in SERVICE_LOGS.values():
        buf.clear()
    append_log("system", "Logs cleared.")
    return {"success": True}

# HTML Cyber Dashboard Interface
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>QMA Multi-Environment Control Center</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --surface: #101626;
      --surface-border: rgba(255, 255, 255, 0.08);
      --surface-hover: #162035;
      --text: #f1f5f9;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --emerald: #10b981;
      --amber: #f59e0b;
      --rose: #f43f5e;
      --indigo: #6366f1;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', sans-serif;
      padding: 24px;
      line-height: 1.5;
    }
    .container { max-width: 1380px; margin: 0 auto; }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--surface-border);
    }
    .logo-area { display: flex; align-items: center; gap: 14px; }
    .logo-icon {
      width: 46px; height: 46px;
      background: linear-gradient(135deg, #0284c7, #38bdf8);
      border-radius: 12px;
      display: flex; align-items: center; justify-content: center;
      font-weight: 800; font-size: 22px; color: #fff;
      box-shadow: 0 0 25px rgba(56, 189, 248, 0.4);
    }
    .title h1 { font-size: 22px; font-weight: 800; letter-spacing: -0.02em; }
    .title p { font-size: 13px; color: var(--text-muted); }
    .top-actions { display: flex; align-items: center; gap: 10px; }
    .status-badge {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 6px 14px; border-radius: 999px;
      font-size: 12px; font-weight: 600;
      background: rgba(16, 185, 129, 0.12); color: var(--emerald);
      border: 1px solid rgba(16, 185, 129, 0.25);
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
    .dot-pulse { animation: pulse 2s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.85); } }

    /* Stats bar */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .stat-card {
      background: var(--surface);
      border: 1px solid var(--surface-border);
      border-radius: 14px;
      padding: 16px 20px;
      display: flex; flex-direction: column; gap: 6px;
    }
    .stat-card h3 { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; }
    .stat-val { font-size: 20px; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
    .stat-sub { font-size: 12px; color: var(--text-muted); }

    /* Services Grid */
    .services-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(410px, 1fr));
      gap: 20px;
      margin-bottom: 30px;
    }
    .service-card {
      background: var(--surface);
      border: 1px solid var(--surface-border);
      border-radius: 16px;
      padding: 22px;
      position: relative;
      display: flex; flex-direction: column; justify-content: space-between;
      transition: border-color 0.2s, transform 0.2s;
    }
    .service-card:hover { border-color: rgba(56, 189, 248, 0.35); transform: translateY(-2px); }
    .service-card.active-prod { border-left: 5px solid var(--emerald); }
    .service-card.active-dev { border-left: 5px solid var(--amber); }

    .card-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
    .service-title { font-size: 17px; font-weight: 700; }
    .service-port {
      font-family: 'JetBrains Mono', monospace; font-size: 13px; font-weight: 700;
      background: rgba(255, 255, 255, 0.06); padding: 4px 10px; border-radius: 8px;
      color: var(--primary);
    }
    .card-meta {
      font-size: 13px; color: var(--text-muted);
      display: flex; flex-direction: column; gap: 6px; margin-bottom: 18px;
    }
    .meta-row { display: flex; justify-content: space-between; }
    .meta-row span:last-child { font-family: 'JetBrains Mono', monospace; color: var(--text); }

    .actions-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
    button {
      cursor: pointer;
      font-family: 'Plus Jakarta Sans', sans-serif;
      font-size: 12px; font-weight: 600;
      padding: 8px 14px; border-radius: 8px;
      border: none; transition: all 0.2s;
      display: inline-flex; align-items: center; gap: 6px;
    }
    .btn-start { background: var(--emerald); color: #022c22; font-weight: 700; }
    .btn-start:hover { filter: brightness(1.2); }
    .btn-stop { background: rgba(244, 63, 94, 0.15); color: #fb7185; border: 1px solid rgba(244, 63, 94, 0.3); }
    .btn-stop:hover { background: rgba(244, 63, 94, 0.28); }
    .btn-restart { background: rgba(255, 255, 255, 0.08); color: var(--text); border: 1px solid var(--surface-border); }
    .btn-restart:hover { background: rgba(255, 255, 255, 0.16); }
    .btn-toggle { background: rgba(99, 102, 241, 0.15); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.35); font-weight: 700; }
    .btn-toggle:hover { background: rgba(99, 102, 241, 0.28); }
    .btn-kill { background: rgba(244, 63, 94, 0.12); color: #fb7185; padding: 5px 10px; font-size: 11px; border: 1px solid rgba(244, 63, 94, 0.25); }
    .btn-kill:hover { background: rgba(244, 63, 94, 0.25); }

    /* Section layout */
    .section-title { font-size: 16px; font-weight: 700; margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between; }

    /* Quick Port Scanner / Tool box */
    .tool-box {
      background: var(--surface); border: 1px solid var(--surface-border); border-radius: 14px;
      padding: 18px 22px; margin-bottom: 30px; display: flex; flex-direction: column; gap: 14px;
    }
    .tool-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .input-field {
      background: #060913; border: 1px solid var(--surface-border); border-radius: 8px;
      color: #fff; padding: 8px 14px; font-family: 'JetBrains Mono', monospace; font-size: 13px;
      outline: none; width: 140px;
    }
    .input-field:focus { border-color: var(--primary); }

    /* Ports Table */
    .ports-table {
      width: 100%; border-collapse: collapse;
      background: var(--surface); border: 1px solid var(--surface-border); border-radius: 14px;
      overflow: hidden; margin-bottom: 30px;
    }
    .ports-table th, .ports-table td { padding: 12px 18px; text-align: left; font-size: 13px; }
    .ports-table th { background: rgba(255, 255, 255, 0.03); color: var(--text-muted); font-size: 11px; text-transform: uppercase; }
    .ports-table tr:not(:last-child) td { border-bottom: 1px solid var(--surface-border); }
    .ports-table td:nth-child(1) { font-family: 'JetBrains Mono', monospace; font-weight: 700; color: var(--primary); }

    /* Logs drawer */
    .log-terminal {
      background: #050811; border: 1px solid var(--surface-border); border-radius: 14px;
      padding: 16px; font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #a5b4fc;
      height: 250px; overflow-y: auto; white-space: pre-wrap; line-height: 1.6;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="logo-area">
        <div class="logo-icon">Q</div>
        <div class="title">
          <h1>QMA Control Center</h1>
          <p>Multi-Environment Orchestrator, Port Collision Guard & Project Manager</p>
        </div>
      </div>
      <div class="top-actions">
        <div class="status-badge" id="postgres-badge">
          <span class="dot dot-pulse"></span>
          <span id="postgres-status">Checking Database...</span>
        </div>
        <button class="btn-stop" onclick="freeAllPorts()">🧹 Free All Standard Ports</button>
        <button class="btn-restart" onclick="loadStatus()">↻ Refresh</button>
      </div>
    </header>

    <!-- Top Stats -->
    <div class="stats-grid">
      <div class="stat-card">
        <h3>Mainnet Database (PROD)</h3>
        <div class="stat-val" id="db-mainnet-events" style="color: var(--emerald);">0 Events</div>
        <div class="stat-sub">DB: qma_mainnet &bull; Invoices: <span id="db-mainnet-invoices">0</span> &bull; Clean Genesis State</div>
      </div>
      <div class="stat-card">
        <h3>Testnet Database (DEV)</h3>
        <div class="stat-val" id="db-testnet-events" style="color: var(--amber);">1,745 Events</div>
        <div class="stat-sub">DB: qma &bull; Invoices: <span id="db-testnet-invoices">2,772</span> &bull; Historical Tests</div>
      </div>
      <div class="stat-card">
        <h3>Ngrok Public Tunnel (24/7)</h3>
        <div class="stat-val" style="font-size: 14px; color: var(--primary);">driveway-expansive-onyx.ngrok-free.dev</div>
        <div class="stat-sub">Forwards strictly to PROD (Port 8000) for Vercel</div>
      </div>
    </div>

    <!-- Core Services Grid -->
    <div class="section-title">
      <span>🚀 Core Services & Dual-Environment Controller</span>
      <span style="font-size: 12px; color: var(--text-muted); font-weight: 500;">PROD and DEV run completely isolated!</span>
    </div>
    <div class="services-grid" id="services-container">
      <!-- Injected via JavaScript -->
    </div>

    <!-- Port Collision Guard & Custom Inspector -->
    <div class="section-title">
      <span>⚡ Port Collision Guard & Inspector (Quản lý Port dự án)</span>
      <span style="font-size: 12px; color: var(--text-muted); font-weight: 500;">Auto-detects which project/process occupies 8000, 5173, etc.</span>
    </div>
    
    <div class="tool-box">
      <div class="tool-row">
        <span style="font-size: 13px; font-weight: 600;">🔍 Custom Port Inspector:</span>
        <input type="number" id="inspect-port-input" class="input-field" placeholder="Port (e.g. 8000)" value="8000" />
        <button class="btn-restart" onclick="inspectCustomPort()">Inspect Process</button>
        <button class="btn-kill" onclick="killCustomPort()">⚡ Force Kill This Port</button>
      </div>
      <div id="inspect-result" style="font-size: 12px; font-family: 'JetBrains Mono', monospace; color: var(--text-muted); display: none;"></div>
    </div>

    <table class="ports-table">
      <thead>
        <tr>
          <th>Port</th>
          <th>Usage Role</th>
          <th>Status</th>
          <th>Process Name</th>
          <th>PID</th>
          <th>Memory</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody id="ports-tbody">
        <!-- Injected via JavaScript -->
      </tbody>
    </table>

    <!-- Realtime Logs -->
    <div class="section-title">
      <span>📋 Live Orchestrator & Process Logs</span>
      <button class="btn-restart" style="padding: 4px 10px; font-size: 11px;" onclick="clearLogs()">Clear Logs</button>
    </div>
    <div class="log-terminal" id="log-terminal">Initializing Control Center event stream...</div>
  </div>

  <script>
    async function loadStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        renderStats(data);
        renderServices(data);
        renderPorts(data);
      } catch (err) {
        console.error("Failed to load status:", err);
      }
    }

    function renderStats(data) {
      const db = data.databases;
      if (db.connected) {
        document.getElementById('postgres-status').textContent = 'PostgreSQL Local (5432) Online';
      } else {
        document.getElementById('postgres-status').textContent = 'PostgreSQL Disconnected';
      }
      document.getElementById('db-mainnet-events').textContent = `${db.mainnet_db.events} Events`;
      document.getElementById('db-mainnet-invoices').textContent = db.mainnet_db.invoices;
      document.getElementById('db-testnet-events').textContent = `${db.testnet_db.events} Events`;
      document.getElementById('db-testnet-invoices').textContent = db.testnet_db.invoices;
    }

    function renderServices(data) {
      const s = data.services;
      const cfg = data.config;
      const container = document.getElementById('services-container');
      container.innerHTML = `
        <!-- PROD Backend -->
        <div class="service-card active-prod">
          <div class="card-head">
            <div>
              <div class="service-title">🟢 PROD Backend (Port 8000)</div>
              <div style="font-size: 12px; color: var(--emerald); font-weight: 600;">Mainnet 24/7 &bull; For Vercel / Ngrok</div>
            </div>
            <span class="service-port">:8000</span>
          </div>
          <div class="card-meta">
            <div class="meta-row"><span>Status:</span><span>${s.prod_backend.info.running ? '🟢 RUNNING' : '⚪ STOPPED'}</span></div>
            <div class="meta-row"><span>PID / Process:</span><span>${s.prod_backend.info.pid ? s.prod_backend.info.pid + ' (' + s.prod_backend.info.name + ')' : '—'}</span></div>
            <div class="meta-row"><span>Target Database:</span><span>qma_mainnet</span></div>
            <div class="meta-row"><span>Auto-Reload:</span><span>DISABLED (Rock Solid 24/7)</span></div>
          </div>
          <div class="actions-row">
            ${s.prod_backend.info.running
              ? `<button class="btn-stop" onclick="serviceAction('prod_backend', 'stop')">Stop PROD</button>
                 <button class="btn-restart" onclick="serviceAction('prod_backend', 'restart')">Restart</button>`
              : `<button class="btn-start" onclick="serviceAction('prod_backend', 'start')">Start PROD (8000)</button>`}
            <a href="http://localhost:8000/docs" target="_blank" style="text-decoration: none;">
              <button class="btn-restart">Docs :8000</button>
            </a>
          </div>
        </div>

        <!-- DEV Backend -->
        <div class="service-card active-dev">
          <div class="card-head">
            <div>
              <div class="service-title">🟡 DEV Backend (Port ${cfg.dev_backend_port})</div>
              <div style="font-size: 12px; color: var(--amber); font-weight: 600;">Local Workspace &bull; Auto-Reload ON</div>
            </div>
            <span class="service-port">:${cfg.dev_backend_port}</span>
          </div>
          <div class="card-meta">
            <div class="meta-row"><span>Status:</span><span>${s.dev_backend.info.running ? '🟢 RUNNING' : '⚪ STOPPED'}</span></div>
            <div class="meta-row"><span>Network Mode:</span><span style="font-weight: 700; color: var(--amber);">${data.dev_network_mode.toUpperCase()}</span></div>
            <div class="meta-row"><span>Target Database:</span><span>${s.dev_backend.db}</span></div>
            <div class="meta-row"><span>PID / Process:</span><span>${s.dev_backend.info.pid ? s.dev_backend.info.pid + ' (' + s.dev_backend.info.name + ')' : '—'}</span></div>
          </div>
          <div class="actions-row">
            ${s.dev_backend.info.running
              ? `<button class="btn-stop" onclick="serviceAction('dev_backend', 'stop')">Stop DEV</button>
                 <button class="btn-restart" onclick="serviceAction('dev_backend', 'restart')">Reload</button>`
              : `<button class="btn-start" onclick="serviceAction('dev_backend', 'start')">Start DEV (${cfg.dev_backend_port})</button>`}
            <button class="btn-toggle" onclick="toggleDevNetwork('${data.dev_network_mode === 'testnet' ? 'mainnet' : 'testnet'}')">
              ⇄ Switch to ${data.dev_network_mode === 'testnet' ? 'MAINNET' : 'TESTNET'}
            </button>
            <a href="http://localhost:${cfg.dev_backend_port}/docs" target="_blank" style="text-decoration: none;">
              <button class="btn-restart">Docs :${cfg.dev_backend_port}</button>
            </a>
          </div>
        </div>

        <!-- Arc Gateway -->
        <div class="service-card">
          <div class="card-head">
            <div>
              <div class="service-title">⚡ Arc Gateway</div>
              <div style="font-size: 12px; color: var(--text-muted);">Arc Network Signing & Relayer</div>
            </div>
            <span class="service-port">:3000</span>
          </div>
          <div class="card-meta">
            <div class="meta-row"><span>Status:</span><span>${s.arc_gateway.info.running ? '🟢 RUNNING' : '⚪ STOPPED'}</span></div>
            <div class="meta-row"><span>PID:</span><span>${s.arc_gateway.info.pid || '—'}</span></div>
            <div class="meta-row"><span>Endpoint:</span><span>http://localhost:3000</span></div>
          </div>
          <div class="actions-row">
            ${s.arc_gateway.info.running
              ? `<button class="btn-stop" onclick="serviceAction('arc_gateway', 'stop')">Stop Gateway</button>`
              : `<button class="btn-start" onclick="serviceAction('arc_gateway', 'start')">Start Gateway</button>`}
          </div>
        </div>

        <!-- Frontend Dev -->
        <div class="service-card">
          <div class="card-head">
            <div>
              <div class="service-title">💻 Frontend Dev (Vite)</div>
              <div style="font-size: 12px; color: var(--text-muted);">Local Developer UI</div>
            </div>
            <span class="service-port">:${cfg.dev_frontend_port}</span>
          </div>
          <div class="card-meta">
            <div class="meta-row"><span>Status:</span><span>${s.frontend_dev.info.running ? '🟢 RUNNING' : '⚪ STOPPED'}</span></div>
            <div class="meta-row"><span>Proxy Target:</span><span>${s.frontend_dev.proxy_target}</span></div>
            <div class="meta-row"><span>PID:</span><span>${s.frontend_dev.info.pid || '—'}</span></div>
          </div>
          <div class="actions-row">
            ${s.frontend_dev.info.running
              ? `<button class="btn-stop" onclick="serviceAction('frontend_dev', 'stop')">Stop Vite</button>`
              : `<button class="btn-start" onclick="serviceAction('frontend_dev', 'start')">Start Vite</button>`}
            <a href="http://localhost:${cfg.dev_frontend_port}" target="_blank" style="text-decoration: none;">
              <button class="btn-restart">Open App :${cfg.dev_frontend_port}</button>
            </a>
          </div>
        </div>

        <!-- Ngrok Tunnel -->
        <div class="service-card">
          <div class="card-head">
            <div>
              <div class="service-title">🌐 Ngrok Tunnel (24/7)</div>
              <div style="font-size: 12px; color: var(--text-muted);">Public Secure Ingress</div>
            </div>
            <span class="service-port">Static URL</span>
          </div>
          <div class="card-meta">
            <div class="meta-row"><span>Status:</span><span>${s.ngrok_tunnel.info.running ? '🟢 ACTIVE' : '⚪ STOPPED'}</span></div>
            <div class="meta-row"><span>Forwards To:</span><span>http://localhost:8000</span></div>
            <div class="meta-row"><span>Public:</span><span style="font-size: 11px;">${s.ngrok_tunnel.public_url}</span></div>
          </div>
          <div class="actions-row">
            ${s.ngrok_tunnel.info.running
              ? `<button class="btn-stop" onclick="serviceAction('ngrok_tunnel', 'stop')">Stop Ngrok</button>`
              : `<button class="btn-start" onclick="serviceAction('ngrok_tunnel', 'start')">Start Ngrok</button>`}
            <a href="http://127.0.0.1:4040" target="_blank" style="text-decoration: none;">
              <button class="btn-restart">Open Ngrok UI :4040</button>
            </a>
          </div>
        </div>
      `;
    }

    function renderPorts(data) {
      const roleMap = {
        8000: 'PROD Backend (Mainnet / Vercel)',
        8001: 'DEV Backend (Testnet / Local)',
        3000: 'Arc Gateway / Node Service',
        5173: 'Vite Frontend Dev',
        5432: 'Self-Hosted PostgreSQL',
        4040: 'Ngrok Inspection Web UI',
        7700: 'Control Center Dashboard'
      };

      const tbody = document.getElementById('ports-tbody');
      tbody.innerHTML = '';
      for (const [port, p] of Object.entries(data.ports)) {
        const tr = document.createElement('tr');
        const role = roleMap[port] || 'Custom Service';
        tr.innerHTML = `
          <td>:${port}</td>
          <td>${role}</td>
          <td>${p.running ? '<span style="color: var(--emerald); font-weight: 700;">● LISTEN</span>' : '<span style="color: var(--text-muted);">○ FREE</span>'}</td>
          <td>${p.name || '—'}</td>
          <td>${p.pid || '—'}</td>
          <td>${p.mem_mb ? p.mem_mb + ' MB' : '—'}</td>
          <td>${p.running && port != 7700 && port != 5432 ? `<button class="btn-kill" onclick="killPort(${port})">⚡ Kill Port</button>` : '—'}</td>
        `;
        tbody.appendChild(tr);
      }
    }

    async function serviceAction(serviceId, action) {
      logMsg(`Sending [${action.toUpperCase()}] to ${serviceId}...`);
      try {
        const res = await fetch(`/api/services/${serviceId}/${action}`, { method: 'POST' });
        const data = await res.json();
        logMsg(`Response: ${JSON.stringify(data)}`);
        await loadStatus();
      } catch (err) {
        logMsg(`Error executing action: ${err}`);
      }
    }

    async function toggleDevNetwork(mode) {
      logMsg(`Switching DEV network to ${mode.toUpperCase()}...`);
      try {
        const res = await fetch('/api/dev/switch-network', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode })
        });
        const data = await res.json();
        logMsg(`Dev network switched: ${JSON.stringify(data)}`);
        await loadStatus();
      } catch (err) {
        logMsg(`Error: ${err}`);
      }
    }

    async function killPort(port) {
      if (!confirm(`Are you sure you want to forcibly kill the process holding port ${port}?`)) return;
      logMsg(`Killing process holding port ${port}...`);
      try {
        const res = await fetch(`/api/ports/kill/${port}`, { method: 'POST' });
        const data = await res.json();
        logMsg(`Port ${port} result: ${JSON.stringify(data)}`);
        await loadStatus();
      } catch (err) {
        logMsg(`Error: ${err}`);
      }
    }

    async function freeAllPorts() {
      if (!confirm("Are you sure you want to kill and free all standard ports (:8000, :8001, :3000, :5173)?")) return;
      logMsg("Initiating batch free for all standard ports...");
      try {
        const res = await fetch('/api/actions/free-all-ports', { method: 'POST' });
        const data = await res.json();
        logMsg(`Free All Ports result: ${JSON.stringify(data)}`);
        await loadStatus();
      } catch (err) {
        logMsg(`Error: ${err}`);
      }
    }

    async function inspectCustomPort() {
      const port = document.getElementById('inspect-port-input').value;
      if (!port) return;
      try {
        const res = await fetch(`/api/ports/inspect/${port}`, { method: 'POST' });
        const data = await res.json();
        const box = document.getElementById('inspect-result');
        box.style.display = 'block';
        if (data.listening) {
          box.innerHTML = `<span style="color: var(--emerald);">Port :${port} is in use by PID ${data.pid} (${data.name})</span><br>Executable: ${data.exe || 'N/A'}<br>Memory: ${data.mem_mb} MB | Command: ${data.cmdline || 'N/A'}`;
        } else {
          box.innerHTML = `<span style="color: var(--primary);">Port :${port} is completely FREE!</span>`;
        }
      } catch (err) {
        logMsg(`Error inspecting port: ${err}`);
      }
    }

    async function killCustomPort() {
      const port = document.getElementById('inspect-port-input').value;
      if (!port) return;
      await killPort(port);
      await inspectCustomPort();
    }

    async function clearLogs() {
      await fetch('/api/logs/clear', { method: 'POST' });
      document.getElementById('log-terminal').textContent = 'Logs cleared.';
    }

    function logMsg(msg) {
      const term = document.getElementById('log-terminal');
      const ts = new Date().toLocaleTimeString();
      term.textContent += `\\n[${ts}] ${msg}`;
      term.scrollTop = term.scrollHeight;
    }

    loadStatus();
    setInterval(loadStatus, 2500);
  </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    return DASHBOARD_HTML

if __name__ == "__main__":
    print("[*] Starting QMA Control Center on http://localhost:7700 ...")
    uvicorn.run(app, host="127.0.0.1", port=7700, log_level="warning")

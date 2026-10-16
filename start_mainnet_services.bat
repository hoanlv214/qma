@echo off
cd /d "%~dp0"
title QMA - Complete Local Server Suite [MAINNET]
echo ======================================================================
echo          QMA - All-in-One Local Server (MAINNET MODE 24/7)
echo ======================================================================
echo.
echo Active Configuration:
echo   Network Mode:      MAINNET (Arc Mainnet 5042)
echo   PostgreSQL DB:     localhost:5432/qma_mainnet (Genesis Production)
echo.
echo Starting all local services:
echo   [1/4] FastAPI Backend   - http://localhost:8000 (MAINNET / qma_mainnet)
echo   [2/4] Arc Gateway       - http://localhost:3000 (MAINNET)
echo   [3/4] Agent Worker      - Autonomous Session Background Engine (MAINNET)
echo   [4/4] Ngrok Tunnel      - Exposing http://localhost:8000 via HTTPS
echo ======================================================================
echo.

cd /d "%~dp0"

:: Ensure explicit MAINNET environment defaults - strictly Self-Hosted PostgreSQL on Mainnet (Port 8000)
set QMA_NETWORK_MODE=mainnet
set VITE_NETWORK_MODE=mainnet
set QMA_STORAGE_BACKEND=postgres
set QMA_BACKEND_PORT=8000
set QMA_BACKEND_RELOAD=false
set QMA_RATE_LIMIT_INVOICE_PER_MIN=60
set QMA_API_URL=http://localhost:8000
set QMA_ARC_GATEWAY_URL=http://localhost:3000
set QMA_ARC_GATEWAY_INTERNAL_SECRET=123a

:: 1. Launch FastAPI Backend for MAINNET (Port 8000, Mainnet / qma_mainnet, No Reload)
echo [1/4] Starting FastAPI Backend on port 8000 (MAINNET / qma_mainnet)...
start "QMA [MAINNET :8000] FastAPI Backend" cmd /k "set QMA_NETWORK_MODE=mainnet&& .venv\Scripts\python.exe scripts\run_backend_local.py --port=8000 --no-reload"

:: 2. Launch Arc Gateway (MAINNET)
echo [2/4] Starting Arc Gateway on port 3000 (MAINNET)...
start "QMA [MAINNET :3000] Arc Gateway" cmd /k "set QMA_NETWORK_MODE=mainnet&& cd arc_gateway && bun start"

:: 3. Launch Agent Worker (MAINNET Mode)
echo [3/4] Starting Agent Worker (MAINNET)...
start "QMA [MAINNET Worker] Agent Worker" cmd /k "set QMA_NETWORK_MODE=mainnet&& set QMA_API_URL=http://localhost:8000&& set QMA_ARC_GATEWAY_URL=http://localhost:3000&& set QMA_ARC_GATEWAY_INTERNAL_SECRET=123a&& cd agents && npm run start:worker"

:: Wait 3 seconds for local ports to open
timeout /t 3 /nobreak >nul

:: 4. Launch Static Ngrok Tunnel
echo [4/4] Starting Ngrok Tunnel with Static Domain...
echo.
echo ======================================================================
echo Ngrok Static URL: https://driveway-expansive-onyx.ngrok-free.dev
echo Exposing http://localhost:8000 (MAINNET / qma_mainnet) to Vercel 24/7
echo ======================================================================
echo.
ngrok http 8000 --url https://driveway-expansive-onyx.ngrok-free.dev

pause

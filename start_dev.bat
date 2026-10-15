@echo off
cd /d "%~dp0"
title QMA - Local DEV Environment (:8001 / :5173)
echo ======================================================================
echo          QMA - Local Development Environment (DEV Only)
echo ======================================================================
echo.
echo Starting DEV local services:
echo   [1/2] FastAPI Backend (DEV) - http://localhost:8001 (Auto-Reload ON)
echo   [2/2] Vite Frontend Dev    - http://localhost:5173 (Proxies to :8001)
echo.
echo NOTE: Port 8000 is reserved for PROD (Ngrok / Vercel).
echo DEV will never interfere with PROD or cause 502 on Vercel.
echo ======================================================================
echo.

cd /d "%~dp0"

:: DEV Environment Defaults
set QMA_NETWORK_MODE=testnet
set QMA_STORAGE_BACKEND=postgres
set QMA_BACKEND_PORT=8001
set QMA_BACKEND_RELOAD=true
set QMA_RATE_LIMIT_INVOICE_PER_MIN=120
set QMA_API_URL=http://localhost:8001
set VITE_BACKEND_URL=http://localhost:8001

:: 1. Launch FastAPI Backend on DEV Port 8001
echo [1/2] Starting DEV FastAPI Backend on port 8001 (Auto-Reload ON)...
start "QMA [DEV :8001] Backend" cmd /k ".venv\Scripts\python.exe scripts\run_backend_local.py --port=8001 --reload"

:: 2. Launch Vite Frontend Dev on port 5173
echo [2/2] Starting Vite Frontend Dev server (Proxying to :8001)...
start "QMA [DEV :5173] Frontend" cmd /k "cd frontend && set VITE_BACKEND_URL=http://localhost:8001&& npm run dev"

echo.
echo DEV services launched successfully!
echo - DEV Backend:  http://localhost:8001
echo - DEV Frontend: http://localhost:5173
echo - Swagger Docs: http://localhost:8001/docs
echo.
pause

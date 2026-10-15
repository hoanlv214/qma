@echo off
cd /d "%~dp0"
title QMA Control Center (:7700)
echo ======================================================================
echo             QMA Multi-Environment Control Center Dashboard
echo ======================================================================
echo.
echo Launching Control Center Orchestrator on http://localhost:7700 ...
echo.
echo   * Manages PROD (:8000, Mainnet 24/7) and DEV (:8001, Testnet/Mainnet)
echo   * Monitors Ports (:8000, :8001, :3000, :5173, :7700, :5432)
echo   * One-click Kill Port + Clean Collisions
echo   * Live Network Switching + Service Lifecycle Control
echo ======================================================================
echo.

:: Open Browser after a short delay in background
start "" http://localhost:7700

:: Prefer project .venv python where all dependencies are installed
set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" scripts\dev_control_center.py

pause

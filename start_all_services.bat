@echo off
cd /d "%~dp0"
title QMA - Multi-Network Local Server Suite

if /i "%1"=="testnet" goto RUN_TESTNET
if /i "%1"=="mainnet" goto RUN_MAINNET

echo ======================================================================
echo          QMA - All-in-One Multi-Network Local Server Suite
echo ======================================================================
echo.
echo Please select target network environment:
echo.
echo   [1] TESTNET (Arc Testnet 5042002 ^| Database: qma - 1,745 Events)
echo   [2] MAINNET (Arc Mainnet 5042    ^| Database: qma_mainnet - Genesis)
echo.
echo ======================================================================
set /p CHOICE="Enter choice [1 or 2] (Default: 1 - Testnet): "

if "%CHOICE%"=="2" goto RUN_MAINNET
goto RUN_TESTNET

:RUN_TESTNET
call start_testnet_services.bat
exit /b

:RUN_MAINNET
call start_mainnet_services.bat
exit /b

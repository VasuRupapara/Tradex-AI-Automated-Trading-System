@echo off
title Tradex AI Engine
color 0A

echo ==============================================
echo       Tradex AI Startup Sequence
echo ==============================================
echo.

echo [System] Launching Tradex AI Flutter Dashboard...
start cmd /k "title Tradex AI Dashboard && cd frontend && set PATH=%PATH%;C:\src\flutter\bin && flutter run -d windows"

echo [System] Dashboard launched in new window!
echo.
echo ==============================================
echo       Tradex AI Engine - Auto-Restart
echo ==============================================
echo.

:loop
echo [System] Starting Python Engine...
python start_trading.py
echo.
echo [System] Engine stopped or rebooting...
echo [System] Restarting in 2 seconds (Press Ctrl+C to stop completely)...
timeout /t 2 /nobreak >nul
goto loop

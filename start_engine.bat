@echo off
title Tradex AI Engine
color 0A
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

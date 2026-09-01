@echo off
title H.A.T.S - Real-Time Intraday Trading Engine
echo =====================================================================
echo   H.A.T.S QUANTITATIVE ENGINE - REAL-TIME INTRADAY TRADING DAEMON
echo   Interval: 15-Minute Candles (9:30 AM - 4:00 PM US Eastern Time)
echo =====================================================================
echo.

python -m src.main --interval 15m --continuous
pause

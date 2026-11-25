@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
set FUYIBA_LOG=logs/bot.log
title 弗一把 bot
echo Starting fuyiba bot. Press Ctrl+C to stop.
echo Log file: logs/bot.log
echo.
python bot.py
echo.
echo Bot exited. Press any key to close.
pause >nul

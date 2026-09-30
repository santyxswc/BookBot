@echo off
title Telegram Book Bot Launcher
chcp 65001 > nul
echo.
echo ===================================================
echo   Iniciando Telegram Book Downloader Bot...
echo ===================================================
echo.
cd /d "%~dp0"
.venv\Scripts\python.exe main.py
if errorlevel 1 (
    echo.
    echo ---------------------------------------------------
    echo Ocurrio un error al ejecutar el bot.
    echo ---------------------------------------------------
    pause
)

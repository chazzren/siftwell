@echo off
rem Double-click to start Siftwell (the first time it also sets itself up) and open it in your browser.
title Siftwell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\launcher.ps1"
if errorlevel 1 (
    echo.
    echo Press any key to close this window.
    pause >nul
    exit /b 1
)

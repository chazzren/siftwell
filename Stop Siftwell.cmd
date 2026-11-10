@echo off
rem Double-click to stop the Siftwell started from this folder.
title Stop Siftwell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\launcher.ps1" -Stop
if errorlevel 1 (
    echo.
    echo Press any key to close this window.
    pause >nul
    exit /b 1
)

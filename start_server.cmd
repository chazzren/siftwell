@echo off
rem Runs Siftwell in this window (close the window to stop it). Normally "Start Siftwell" is used instead.
rem Uses the Python runtime "Start Siftwell" set up (outside this folder), else an older install's .venv.
cd /d "%~dp0"
set PYTHONUTF8=1
set "RT=%LOCALAPPDATA%\Siftwell\runtime"
if defined SIFTWELL_RUNTIME set "RT=%SIFTWELL_RUNTIME%"
set "PYTHONPYCACHEPREFIX=%RT%\pycache"
set "PY=%RT%\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=.venv\Scripts\python.exe"
"%PY%" -X utf8 server.py
pause

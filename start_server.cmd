@echo off
rem Runs the job board in this window (close the window to stop it). Normally it starts on its own at sign-in.
cd /d "%~dp0"
set PYTHONUTF8=1
".venv\Scripts\python.exe" -X utf8 server.py
pause

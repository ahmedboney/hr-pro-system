@echo off
chcp 65001 >nul
title HR Pro System - Demo Mode
set DEMO_MODE=1
set SESSION_COOKIE_SECURE=0
where pythonw >nul 2>nul
if errorlevel 1 (
  set PY="%ProgramFiles%\Python311\pythonw.exe"
) else (
  set PY=pythonw
)
start "" %PY% "%~dp0run_server.py"
echo وضع التجربة يعمل على http://127.0.0.1:8080  (demo / demo1234)
timeout /t 3 >nul
start "" http://127.0.0.1:8080
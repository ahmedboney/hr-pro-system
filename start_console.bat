@echo off
chcp 65001 >nul
title HR Pro System - وضع المطور (يعرض السجل)
where python >nul 2>nul
if errorlevel 1 (
  set PY="%ProgramFiles%\Python311\python.exe"
) else (
  set PY=python
)
%PY% "%~dp0run_server.py"
pause
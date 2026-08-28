@echo off
chcp 65001 >nul
title HR Pro System - التشغيل الصامت
where pythonw >nul 2>nul
if errorlevel 1 (
  echo [-] pythonw غير موجود في الـ PATH - جارٍ البحث عن Python 311...
  set PY= "%ProgramFiles%\Python311\pythonw.exe"
) else (
  set PY=pythonw
)
start "" %PY% "%~dp0run_server.py"
echo تم تشغيل النظام بصمت على http://127.0.0.1:8080
timeout /t 3 >nul
start "" http://127.0.0.1:8080
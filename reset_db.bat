@echo off
chcp 65001 >nul
title HR Pro System - إعادة تهيئة قاعدة البيانات
set PY=python
if exist "%~dp0hr_system.db" (
  copy /Y "%~dp0hr_system.db" "%~dp0hr_system.bak.db" >nul
  del "%~dp0hr_system.db"
)
%PY% "%~dp0init_db.py"
echo.
echo [√] قاعدة البيانات أعيد إنشاؤها (النسخة القديمة محفوظة باسم hr_system.bak.db)
pause
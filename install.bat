@echo off
chcp 65001 >nul
title HR Pro System - تثبيت (مرة واحدة)
set PY=python
%PY% -m venv "%~dp0.venv"
call "%~dp0.venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r "%~dp0requirements.txt"
python "%~dp0init_db.py"
echo.
echo [√] تم التثبيت بنجاح! شغّـل start_silent.bat من الآن فصاعداً.
pause
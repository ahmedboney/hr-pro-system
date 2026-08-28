@echo off
chcp 65001 >nul
title HR Pro System - الجهاز الرئيسي على الشبكة
echo ============================================================
echo  HR Pro - تشغيل واجهة الشبكة (الجهاز الرئيسي)
echo  ستخدمه الأجهزة القريبة والشبكة الداخلية
echo ============================================================
echo.

where pythonw >nul 2>nul
if errorlevel 1 (
  set PY="%ProgramFiles%\Python311\pythonw.exe"
) else (
  set PY=pythonw
)

start "" %PY% "%~dp0run_server.py"

echo [+] يتم التشغيل... انتظر لحظات
timeout /t 4 >nul

echo.
echo [>] روابط الدخول:
echo     - من هذا الجهاز:      http://127.0.0.1:8080
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  echo     - من أجهزة الشبكة:   http://%%a:8080
)

echo.
echo [+] السماح من جدار الحماية (ينفذ بصلاحيات مدير)
netsh advfirewall firewall add rule name="HR Pro 8080" dir=in action=allow protocol=TCP localport=8080 >nul 2>nul

echo.
echo  الاستخدام: من أي جهاز آخر على نفس راوتر المنزل/الشبكة
echo  افتح المتصفح على الرابط أعلاه (http://عنوان-الجهاز:8080)
echo.
if not "%1"=="--nopause" pause
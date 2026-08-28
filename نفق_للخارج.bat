@echo off
chcp 65001 >nul
title HR Pro - نفق Cloudflare (عرض عام / فروع بعيدة)
echo ============================================================
echo  توصية أمان هامة:
echo  NEVER نقطة النفق إلى النسخة الحقيقية (8080) - فيها دخول تلقائي
echo  وبيناتك الفعلية. هذا السكربت يعرض نسخة DEMO معزولة فقط.
echo  للفروع الداخلية استخدم الشبكة المحلية أو VPN (راجع نوتة_ربط_الاجهزة.md)
echo ============================================================
echo.
set DEMO_MODE=1
set PORT=8090
set HOST=127.0.0.1
set HR_DB_PATH=%TEMP%\hr_demo_public.db
where pythonw >nul 2>nul
if errorlevel 1 (
  set PY="%ProgramFiles%\Python311\pythonw.exe"
) else (
  set PY=pythonw
)
start "" %PY% "%~dp0run_server.py"
timeout /t 5 >nul

where cloudflared >nul 2>nul
if errorlevel 1 (
  echo [x] ضع cloudflared.exe بجانب هذا السكربت أولا.
  echo     https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
  pause
  exit /b 1
)
echo.
echo  >>>> انسخ الرابط أدناه وشاركه (demo / demo1234)
echo.
cloudflared tunnel --url http://127.0.0.1:8090
pause
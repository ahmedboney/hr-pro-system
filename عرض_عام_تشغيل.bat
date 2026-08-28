@echo off
chcp 65001 >nul
title HR Pro - عرض عام دائم للنظام
echo ============================================================
echo  HR Pro - عرض تجريبي عام للناس (من أي مكان في العالم)
echo  يفهم: نفق يرتبط بجهازك - يبقى الرابط شغالاً ما دام جهازك
echo  يعمل وهذه النافذة مفتوحة. لإبقاء العرض دائماً حتى مع
echo  إغلاق جهازك استخدم دليل_الاستضافة.md (نشر سحابي على Render).
echo ============================================================
echo.

REM 1) تشغيل نسخة DEMO معزولة (بيانات تجريبية فقط - آمنة للعرض)
set DEMO_MODE=1
set PORT=8090
set HOST=127.0.0.1
set HR_DB_PATH=%TEMP%\hr_demo_public.db
echo [+] تشغيل نسخة العرض التجريبي على المنفذ 8090 ...
where pythonw >nul 2>nul
if errorlevel 1 (
  set PY="%ProgramFiles%\Python311\pythonw.exe"
) else (
  set PY=pythonw
)
start "" %PY% "%~dp0run_server.py"
timeout /t 5 >nul

REM 2) التشغيل محلياً في المتصفح للتحقق
start "" http://127.0.0.1:8090/login

REM 3) فتح النفق العام
echo [+] إنشاء الرابط العام عبر Cloudflare (انتظر لحظات)...
where cloudflared >nul 2>nul
if errorlevel 1 (
  echo [x] لا يوجد cloudflared بجانب النظام. نزّله من:
  echo     https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
  echo     ضع الملف cloudflared.exe بجانب هذا السكربت ثم أعد التشغيل.
  pause
  exit /b 1
)
echo.
echo  >>>> انسخ الرابط الذي يظهر أدناه (https://...trycloudflare.com)
echo  >>>> وشاركه مع الناس: حساب الدخول  demo / demo1234
echo.
cloudflared tunnel --url http://127.0.0.1:8090

echo.
echo  انتبه: بغلق هذه النافذة أو إغلاق الجهاز يغلق الرابط.
pause
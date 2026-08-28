@echo off
chcp 65001 >nul
title HR Pro - نفق Cloudflare (إتاحة النظام من الإنترنت)
echo ============================================================
echo  HR Pro - فتح النظام لخارج الشبكة (مناطق بعيدة)
echo  تحويل الجهاز الرئيسي إلى عنوان عام ثابت مثل:
echo      https://hr-far3.trycloudflare.com
echo  تستخدمه فروعك البعيدة وأجهزة البصمة من أي مكان.
echo ============================================================
echo.
echo [1] إن لم يوجد cloudflared سيُحاول تثبيته الآن...
where cloudflared >nul 2>nul
if errorlevel 1 (
  echo     - حمّل cloudflared (إصدار ويندوز) من:
  echo       https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
  echo     - ضع الملف cloudflared.exe بجانب هذا السكربت، ثم أعد تشغيله.
  echo.
  pause
  exit /b 1
)

echo [2] تشغيل النظام محلياً (إن لم يكن يعمل)...
where pythonw >nul 2>nul
set PY=pythonw
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8080 ^| findstr LISTENING') do set FOUND=%%p
if not defined FOUND start "" %PY% "%~dp0run_server.py"
timeout /t 4 >nul

echo [3] إنشاء النفق (سيب النافذة مفتوحة — بمجرد إغلاقها يغلق الرابط)...
echo.
cloudflared tunnel --url http://127.0.0.1:8080

echo.
echo  انسخ الرابط https://...trycloudflare.com وشاركه مع فروعك.
echo  ملاحظة: الرابط مؤقت ويُعاد إنشاؤه في كل مرة؛ للرابط الدائم والنشر
echo  الاحترافي استخدم دليل_الاستضافة.md (Render مجاني).
pause
import os
import secrets
import sys

# عند التحزيم في exe: كل الملفات (قاعدة البيانات، النسخ...) بجانب ملف التشغيل
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# مسار قاعدة البيانات: يمكن تغييره لتحزيم الـ exe أو للعزل/الاختبار
_DB_PATH = os.environ.get('HR_DB_PATH') or os.path.join(BASE_DIR, 'hr_system.db')


def _load_secret_key():
    """مفتاح سري ثابت مخزّن في ملف حتى تستمر الجلسات بعد إعادة التشغيل"""
    key_file = os.path.join(BASE_DIR, 'secret.key')
    try:
        if os.path.exists(key_file):
            with open(key_file, 'r', encoding='utf-8') as f:
                key = f.read().strip()
                if key:
                    return key
        key = secrets.token_hex(32)
        with open(key_file, 'w', encoding='utf-8') as f:
            f.write(key)
        return key
    except Exception:
        return os.environ.get('SECRET_KEY', secrets.token_hex(24))


class Config:
    SECRET_KEY = _load_secret_key()
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{_DB_PATH}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DB_FILENAME = os.path.basename(_DB_PATH)

    DEMO_MODE = os.environ.get('DEMO_MODE', '0') == '1'

    # ===== Security =====
    SESSION_COOKIE_HTTPONLY = True          # منع قراءة الكوكيز بالجافاسكربت
    SESSION_COOKIE_SAMESITE = 'Lax'         # حماية CSRF إضافية
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'  # HTTPS فقط (للاستضافة)
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024   # حد حجم الملفات المرفوعة 16MB

    # ===== Company Settings =====
    COMPANY_NAME = "شركتي"
    CURRENCY = "ج.م"

    # ===== Attendance Settings =====
    WORK_START_HOUR = 8
    WORK_END_HOUR = 17
    LATE_TOLERANCE_MINUTES = 15
    OVERTIME_RATE = 1.5

    # ===== Leave Settings =====
    ANNUAL_LEAVE_DAYS = 21
    SICK_LEAVE_DAYS = 15

    # ===== Payroll Settings =====
    SOCIAL_INSURANCE_RATE = 0.11
    TAX_BRACKET = 0.0

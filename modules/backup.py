"""النسخ الاحتياطي لقاعدة البيانات (يدوي + تلقائي)"""
import os
import shutil
from datetime import datetime

from config import BASE_DIR, Config

# بجانب ملف التشغيل دائماً (حتى في وضع الـ exe)
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')
KEEP_LAST = 30  # نحتفظ بآخر 30 نسخة


def _ensure_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)


def create_backup(notes="نسخة احتياطية"):
    """إنشاء نسخة احتياطية من قاعدة البيانات، يعيد مسار الملف"""
    _ensure_dir()
    db_path = Config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"hr_backup_{ts}.db"
    dest = os.path.join(BACKUP_DIR, filename)
    if os.path.exists(db_path):
        shutil.copy2(db_path, dest)
        with open(os.path.join(BACKUP_DIR, 'backup.log'), 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {filename} | {notes}\n")
    _cleanup()
    return dest, filename


def list_backups():
    """قائمة النسخ الاحتياطية مرتبة من الأحدث للأقدم"""
    _ensure_dir()
    items = []
    for name in os.listdir(BACKUP_DIR):
        if name.endswith('.db'):
            path = os.path.join(BACKUP_DIR, name)
            size = os.path.getsize(path)
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            items.append({
                'filename': name,
                'size': size,
                'date': mtime.strftime('%Y-%m-%d'),
                'time': mtime.strftime('%H:%M:%S'),
                'path': path,
            })
    items.sort(key=lambda x: x['date'] + x['time'], reverse=True)
    return items


def restore_backup(filename):
    """استعادة قاعدة البيانات من نسخة احتياطية"""
    src = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(src):
        raise FileNotFoundError("النسخة الاحتياطية غير موجودة")
    db_path = Config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')
    # نسخة أمان من الحالية قبل الاستعادة
    now = datetime.now().strftime('%Y%m%d_%H%M%S')
    shutil.copy2(db_path, os.path.join(BACKUP_DIR, f"pre_restore_{now}.db"))
    shutil.copy2(src, db_path)
    return True


def delete_backup(filename):
    path = os.path.join(BACKUP_DIR, filename)
    if os.path.exists(path) and filename.endswith('.db'):
        os.remove(path)


def _cleanup():
    """حذف النسخ الأقدم من الحد المسموح"""
    items = list_backups()
    for item in items[KEEP_LAST:]:
        try:
            os.remove(item['path'])
        except OSError:
            pass
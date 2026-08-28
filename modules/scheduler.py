"""مهام خلفية تلقائية (نسخ احتياطي يومي + حساب الغياب نهاية اليوم)"""
import time
from datetime import date, datetime
import threading


def now_hhmm():
    return datetime.now().strftime('%H:%M')


def _demo_mode():
    from config import Config
    return bool(getattr(Config, 'DEMO_MODE', False))


def run_backup_task():
    if _demo_mode():
        return
    from app import app
    from modules import backup
    with app.app_context():
        try:
            backup.create_backup(notes="نسخة احتياطية تلقائية يومية")
            print(f"[backup] تلقائي {now_hhmm()}", flush=True)
        except Exception as e:
            print(f"[backup] خطأ: {e}", flush=True)


def run_absence_task():
    if _demo_mode():
        return
    from app import app
    with app.app_context():
        try:
            from models import (db, Employee, Attendance, LeaveRequest, Setting)
            from datetime import date
            today = date.today()

            marker = Setting.get('absence_run_date')
            if marker == today.isoformat():
                return

            on_leave_ids = [
                r.employee_id for r in LeaveRequest.query.filter(
                    LeaveRequest.status == 'approved',
                    LeaveRequest.start_date <= today,
                    LeaveRequest.end_date >= today
                ).all()
            ]
            present_ids = [
                r.employee_id for r in Attendance.query.filter(
                    Attendance.date == today
                ).all()
            ]
            marked = 0
            for emp in Employee.query.filter_by(status='active').all():
                if emp.id in present_ids or emp.id in on_leave_ids:
                    continue
                db.session.add(Attendance(
                    employee_id=emp.id,
                    date=today,
                    status='absent',
                    notes='غياب متاح تلقائياً نهاية اليوم',
                ))
                marked += 1
            db.session.commit()
            Setting.set('absence_run_date', today.isoformat())
            print(f"[absence] تم تسجيل غياب {marked} موظف", flush=True)
        except Exception as e:
            print(f"[absence] خطأ: {e}", flush=True)


def run_demo_reset_task():
    """إعادة ضبط بيانات الديمو العامة كل يوم (تُحافظ على نظافة الاستضافة)"""
    if not _demo_mode():
        return
    from app import app
    from init_db import reset_demo_data
    with app.app_context():
        try:
            reset_demo_data()
        except Exception as e:
            print(f"[demo] خطأ: {e}", flush=True)


def background_loop():
    """حلقة خلفية تجري مرة كل دقيقة، تنفذ المهام عند مواعيدها"""
    last_backup_day = None
    last_absence_day = None
    last_demo_reset_day = None
    while True:
        try:
            from models import Setting
            hh = now_hhmm()
            today_str = date.today().isoformat()

            # نسخ احتياطي تلقائي يومياً الساعة 02:00
            if hh == '02:00' and last_backup_day != today_str:
                run_backup_task()
                last_backup_day = today_str

            # إعادة ضبط الديمو العام يومياً الساعة 03:00
            if hh == '03:00' and last_demo_reset_day != today_str:
                run_demo_reset_task()
                last_demo_reset_day = today_str

            # حساب الغياب تلقائياً بعد نهاية الدوام (الساعة 23:30)
            if hh == '23:30' and last_absence_day != today_str:
                run_absence_task()
                last_absence_day = today_str
        except Exception as e:
            print(f"[scheduler] خطأ عام: {e}", flush=True)
        time.sleep(58)


def start_scheduler():
    """تشغيل المهام الخلفية (لا تمنع إقلاع التطبيق)"""
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    return t
"""التنبيهات الذكية التي تظهر في لوحة التحكم"""
from datetime import date


def get_notifications():
    """يقيم الحالة العامة للنظام ويعيد قائمة تنبيهات ذكية"""
    from models import (
        db, Employee, Attendance, LeaveRequest, LeaveBalance,
        Loan, PayrollPeriod, PayrollRecord, Setting
    )
    today = date.today()
    notifications = []

    # 1) قرب نفاد رصيد الإجازات
    low_balances = LeaveBalance.query.filter(
        LeaveBalance.year == today.year,
        LeaveBalance.remaining_days <= 3,
        LeaveBalance.remaining_days > 0,
    ).all()
    seen = set()
    for b in low_balances[:12]:
        if b.employee_id in seen:
            continue
        seen.add(b.employee_id)
        emp = b.employee
        if emp:
            notifications.append({
                'level': 'warning',
                'icon': 'far fa-calendar-alt',
                'title': 'رصيد إجازة على وشك النفاد',
                'text': f"{emp.full_name} تبقت أيام إجازة قليلة ({b.remaining_days} يوم).",
                'link': '/leaves/balances',
            })

    # 2) غياب متكرر في الشهر الحالي
    first_day = today.replace(day=1)
    repeated = (
        db.session.query(Attendance.employee_id, db.func.count(Attendance.id))
        .filter(Attendance.status == 'absent', Attendance.date >= first_day)
        .group_by(Attendance.employee_id)
        .having(db.func.count(Attendance.id) > 3)
        .all()
    )
    for emp_id, count in repeated[:10]:
        emp = Employee.query.get(emp_id)
        if emp and emp.status == 'active':
            notifications.append({
                'level': 'danger',
                'icon': 'fas fa-user-times',
                'title': 'غياب متكرر',
                'text': f"{emp.full_name} بلغت أيام غيابه {count} يوماً هذا الشهر.",
                'link': '/attendance/report',
            })

    # 3) موظفون غير مسجلين بالبصمة
    no_fp = Employee.query.filter(
        Employee.fingerprint_id.is_(None),
        Employee.status == 'active',
    ).count()
    if no_fp:
        notifications.append({
            'level': 'info',
            'icon': 'fas fa-fingerprint',
            'title': 'موظفون بدون بصمة',
            'text': f"يوجد {no_fp} موظف نشط غير مسجل على أجهزة البصمة.",
            'link': '/fingerprint',
        })

    # 4) طلبات إجازة بانتظار الموافقة
    pending_leaves = LeaveRequest.query.filter_by(status='pending').count()
    if pending_leaves:
        notifications.append({
            'level': 'info',
            'icon': 'fas fa-envelope-open-text',
            'title': 'طلبات إجازة معلقة',
            'text': f"يوجد {pending_leaves} طلب إجازة بانتظار المراجعة.",
            'link': '/leaves',
        })

    # 5) سلف متأخرة (نشطة لأكثر من 3 أشهر)
    from sqlalchemy import func
    cutoff = None
    try:
        from models import Loan
        old_loans = Loan.query.filter(
            Loan.status == 'active',
            Loan.remaining_amount > 0,
            Loan.created_at < func.date('now', '-3 months'),
        ).count()
        if old_loans:
            notifications.append({
                'level': 'warning',
                'icon': 'fas fa-hand-holding-usd',
                'title': 'سلف مستحقة',
                'text': f"يوجد {old_loans} سلفة/قرض مستمر لأكثر من 3 شهور.",
                'link': '/loans',
            })
    except Exception:
        pass

    # 6) فترة الرواتب الحالية لم تحتسب
    active_period = PayrollPeriod.query.filter_by(status='active').first()
    if active_period:
        processed = PayrollRecord.query.filter_by(period_id=active_period.id).count()
        if processed == 0:
            notifications.append({
                'level': 'warning',
                'icon': 'fas fa-calculator',
                'title': 'فترة رواتب غير محسوبة',
                'text': f"فترة {active_period.name} لم يتم احتساب رواتبها بعد.",
                'link': f'/payroll/{active_period.id}',
            })

    return notifications[:12]
import os
from datetime import date, timedelta
from app import db, app
from models import (
    User, Department, Position, Employee, LeaveType, DeductionType,
    BonusType, Setting, FingerprintDevice, AllowanceType, PayrollPeriod,
    LeaveBalance, Attendance, LeaveRequest, PayrollRecord, LoanPayment,
    Bonus, Loan, OvertimeRequest
)

def create_database():
    db.create_all()
    print("[+] Database tables created.")

def seed_default_data():
    """أدخل البيانات الافتراضية (idempotent)"""
    from config import Config
    is_demo = bool(getattr(Config, 'DEMO_MODE', False))

    # في وضع الديمو لا تُنشأ حسابات admin إطلاقاً (حساب تجريبي واحد فقط بصلاحية محدودة)
    if not is_demo:
        # Create default admin user
        if User.query.count() == 0:
            admin = User(
                username='admin',
                full_name='مدير النظام',
                role='admin',
                is_active=True
            )
            admin.set_password('admin123')
            db.session.add(admin)

            hr = User(
                username='hr',
                full_name='مدير الموارد البشرية',
                role='hr',
                is_active=True
            )
            hr.set_password('hr123')
            db.session.add(hr)
            print("[+] Default users created (admin/admin123, hr/hr123)")
    else:
        if not User.query.filter_by(username='demo').first():
            demo = User(username='demo', full_name='حساب تجريبي', role='hr', is_active=True)
            demo.set_password('demo1234')
            db.session.add(demo)
            print("[+] Demo account created (demo/demo1234)")

    # Create default departments
    if Department.query.count() == 0:
        departments = [
            {'name': 'الإدارة العليا', 'description': 'الإدارة العليا للشركة'},
            {'name': 'الموارد البشرية', 'description': 'إدارة شؤون العاملين'},
            {'name': 'المالية والمحاسبة', 'description': 'الشؤون المالية'},
            {'name': 'تكنولوجيا المعلومات', 'description': 'الدعم الفني والنظم'},
            {'name': 'المبيعات والتسويق', 'description': 'المبيعات وتسويق المنتجات'},
            {'name': 'الإنتاج', 'description': 'أقسام الإنتاج والتصنيع'},
            {'name': 'المشتريات والمخازن', 'description': 'المشتريات وإدارة المخازن'},
        ]
        for d in departments:
            db.session.add(Department(**d))
        print("[+] Default departments created")

    # Create default positions
    if Position.query.count() == 0:
        positions = [
            {'title': 'مدير عام'},
            {'title': 'مدير قسم'},
            {'title': 'أخصائي موارد بشرية'},
            {'title': 'محاسب'},
            {'title': 'مبرمج'},
            {'title': 'مندوب مبيعات'},
            {'title': 'عامل إنتاج'},
            {'title': 'أمين مخازن'},
            {'title': 'خدمة عملاء'},
            {'title': 'سكرتير'},
        ]
        for p in positions:
            db.session.add(Position(**p))
        print("[+] Default positions created")

    # Create default leave types
    if LeaveType.query.count() == 0:
        leave_types = [
            {'name': 'إجازة سنوية', 'paid': True, 'max_days_per_year': 21, 'color': '#27ae60'},
            {'name': 'إجازة مرضية', 'paid': True, 'max_days_per_year': 30, 'color': '#e74c3c'},
            {'name': 'إجازة طارئة', 'paid': False, 'max_days_per_year': 3, 'color': '#f39c12'},
            {'name': 'إجازة بدون أجر', 'paid': False, 'max_days_per_year': 30, 'color': '#7f8c8d'},
            {'name': 'إجازة أمومة', 'paid': True, 'max_days_per_year': 90, 'color': '#e84393'},
            {'name': 'إجازة ضرورية', 'paid': False, 'max_days_per_year': 0, 'color': '#34495e'},
            {'name': 'إجازة عارضة', 'paid': True, 'max_days_per_year': 7, 'color': '#2980b9'},
        ]
        for lt in leave_types:
            db.session.add(LeaveType(**lt))
        print("[+] Default leave types created")

    # Create deduction types
    if DeductionType.query.count() == 0:
        deduction_types = [
            {'name': 'خصم تأخير'},
            {'name': 'خصم غياب بدون إذن'},
            {'name': 'خصم جزائي'},
            {'name': 'تأمينات اجتماعية'},
            {'name': 'ضريبة كسب عمل'},
            {'name': 'خصم قرض'},
            {'name': 'خصم سلفة'},
        ]
        for d in deduction_types:
            db.session.add(DeductionType(**d))
        print("[+] Default deduction types created")

    # Create bonus types
    if BonusType.query.count() == 0:
        bonus_types = [
            {'name': 'مكافأة أداء'},
            {'name': 'مكافأة سنوية'},
            {'name': 'عمولة مبيعات'},
            {'name': 'علاوة دورية'},
            {'name': 'هدية مناسبة'},
        ]
        for b in bonus_types:
            db.session.add(BonusType(**b))
        print("[+] Default bonus types created")

    # Create allowance types
    if AllowanceType.query.count() == 0:
        allowance_types = [
            {'name': 'بدل سكن'},
            {'name': 'بدل انتقال'},
            {'name': 'بدل وجبات'},
            {'name': 'بدل هاتف'},
        ]
        for a in allowance_types:
            db.session.add(AllowanceType(**a))
        print("[+] Default allowance types created")

    # Create default settings
    defaults = {
        'company_name': 'شركتي المتميزة',
        'company_name_en': 'My Company',
        'company_address': '',
        'company_phone': '',
        'company_email': '',
        'tax_number': '',
        'currency': 'ج.م',
        'work_start': '08:00',
        'work_end': '17:00',
        'late_tolerance': '15',
        'saturday_off': 'yes',
        'friday_off': 'yes',
        'annual_leave_days': '21',
        'sick_leave_days': '15',
        'social_insurance_rate': '11',
        'overtime_rate': '1.5',
        'sign_fin_role': 'محاسب',
        'sign_fin_name': 'أحمد عبدالله',
        'sign_hr_role': 'مدير الموارد البشرية',
        'sign_hr_name': '',
    }
    for k, v in defaults.items():
        if not Setting.query.filter_by(key=k).first():
            db.session.add(Setting(key=k, value=v))
    print("[+] Default settings created")

    # Create default fingerprint device
    if FingerprintDevice.query.count() == 0:
        db.session.add(FingerprintDevice(
            name='جهاز البصمة الرئيسي',
            device_ip='192.168.1.200',
            model='ZK-Teco uFace 800',
            location='المدخل الرئيسي',
            device_type='zkteco',
            status='active'
        ))
        print("[+] Default fingerprint device created")

    # Create empty current period
    from calendar import monthrange
    today = date.today()
    period_name = f"{today.year}-{today.month:02d}"
    if not PayrollPeriod.query.filter_by(name=period_name).first():
        db.session.add(PayrollPeriod(
            name=period_name,
            period_month=today.month,
            period_year=today.year,
            start_date=date(today.year, today.month, 1),
            end_date=date(today.year, today.month, monthrange(today.year, today.month)[1]),
            status='active'
        ))
        print(f"[+] Current payroll period {period_name} created")

    try:
        db.session.commit()
        print("[+] All default data seeded successfully.")
    except Exception:
        db.session.rollback()
        print("[·] Data already exists, skipping seed.")


# Add a sample employee for testing
def add_sample_employee():
    from datetime import date
    if Employee.query.count() == 0:
        dept = Department.query.filter_by(name='تكنولوجيا المعلومات').first()
        pos = Position.query.filter_by(title='مبرمج').first()
        emp = Employee(
            emp_id='EMP001',
            fingerprint_id='1001',
            first_name='أحمد',
            last_name='محمد',
            national_id='29501010101234',
            birth_date=date(1995, 1, 1),
            gender='ذكر',
            marital_status='أعزب',
            phone='01000000000',
            address='القاهرة، مصر',
            email='ahmed@company.com',
            department_id=dept.id if dept else None,
            position_id=pos.id if pos else None,
            hire_date=date(2020, 1, 1),
            employment_type='full_time',
            status='active',
            base_salary=5000,
            housing_allowance=1000,
            transport_allowance=500,
            food_allowance=300,
            phone_allowance=200,
        )
        db.session.add(emp)
        db.session.commit()
        # Create leave balances for sample employee
        current_year = date.today().year
        for lt in LeaveType.query.all():
            if lt.max_days_per_year and lt.max_days_per_year > 0:
                lv = LeaveBalance(
                    employee_id=emp.id,
                    leave_type_id=lt.id,
                    year=current_year,
                    entitled_days=lt.max_days_per_year,
                    used_days=0,
                    remaining_days=lt.max_days_per_year
                )
                db.session.add(lv)
        db.session.commit()
        print(f"[+] Sample employee created: {emp.full_name}")


# بيانات تجريبية غنية لوضع الديمو (تُظهر على الاستضافة العامة فقط)
def seed_demo_data():
    """أدخل بيانات تجريبية واقعية حتى يرى الزائر النظام بكامل قوته"""
    from config import Config
    if not getattr(Config, 'DEMO_MODE', False):
        return
    try:
        if Setting.get('demo_data') == 'off':
            return
        if Setting.get('demo_seeded') == date.today().isoformat():
            return
        dept_by_name = {d.name: d.id for d in Department.query.all()}
        pos_by_title = {p.title: p.id for p in Position.query.all()}
        specs = [
            ('EMP002', '2002', 'سارة', 'خالد', 'الموارد البشرية', 'أخصائي موارد بشرية', 4500, 400, 200, 100, 'أنثى'),
            ('EMP003', '3003', 'محمد', 'حسن', 'تكنولوجيا المعلومات', 'مبرمج', 6500, 800, 400, 200, 'ذكر'),
            ('EMP004', '4004', 'منى', 'إبراهيم', 'المالية والمحاسبة', 'محاسب', 5500, 600, 300, 150, 'أنثى'),
        ]
        today = date.today()
        for emp_id, fp, first, last, dept, posi, base, housing, transport, food, gender in specs:
            emp = Employee(
                emp_id=emp_id, fingerprint_id=fp, first_name=first, last_name=last,
                gender=gender, marital_status='متزوج' if gender == 'ذكر' else 'أعزب',
                phone='0100' + str(hash(fp))[-7:],
                address='القاهرة، مصر', email=f'{first}@demo.com',
                department_id=dept_by_name.get(dept), position_id=pos_by_title.get(posi),
                hire_date=date(today.year - 3, 3, 1), employment_type='full_time',
                status='active', base_salary=base, housing_allowance=housing,
                transport_allowance=transport, food_allowance=food, phone_allowance=100,
            )
            db.session.add(emp)
        db.session.commit()

        # أرصدة إجازات للموظفين الجدد
        for emp in Employee.query.all():
            if LeaveBalance.query.filter_by(employee_id=emp.id).first():
                continue
            for lt in LeaveType.query.filter(LeaveType.max_days_per_year > 0).all():
                db.session.add(LeaveBalance(
                    employee_id=emp.id, leave_type_id=lt.id, year=today.year,
                    entitled_days=lt.max_days_per_year, used_days=0,
                    remaining_days=lt.max_days_per_year,
                ))
        db.session.commit()

        # حضور واقعي لأيام الشهر الحالي
        from datetime import timedelta
        for emp in Employee.query.all():
            offset = emp.id % 4
            for day in range(1, today.day + 1):
                d = date(today.year, today.month, day)
                if d > today:
                    break
                if d.weekday() in (4, 5):  # الجمعة والسبت إجازة
                    continue
                if (emp.id + day) % 7 == 0:
                    db.session.add(Attendance(employee_id=emp.id, date=d, status='absent',
                                              notes='بيانات تجريبية'))
                elif (emp.id + day) % 5 == 0:
                    db.session.add(Attendance(employee_id=emp.id, date=d, status='late',
                                              check_in_time=__import__('datetime').time(9, 20 + offset)))
                else:
                    db.session.add(Attendance(employee_id=emp.id, date=d, status='present',
                                              check_in_time=__import__('datetime').time(8, 55),
                                              check_out_time=__import__('datetime').time(17, 5)))
        db.session.commit()

        # طلب إجازة موافَق عليه + طلب معلق
        emp2 = Employee.query.filter_by(emp_id='EMP002').first()
        lt = LeaveType.query.filter_by(name='إجازة سنوية').first()
        if emp2 and lt and not LeaveRequest.query.first():
            db.session.add(LeaveRequest(
                employee_id=emp2.id, leave_type_id=lt.id,
                start_date=date(today.year, today.month, 1),
                end_date=date(today.year, today.month, 3),
                status='approved', reason='إجازة سنوية (بيانات تجريبية)',
                review_notes='موافقة تجريبية',
            ))
            next_month = today.month + 1 if today.month < 12 else 1
            next_year = today.year if today.month < 12 else today.year + 1
            db.session.add(LeaveRequest(
                employee_id=emp2.id, leave_type_id=lt.id,
                start_date=date(next_year, next_month, 10),
                end_date=date(next_year, next_month, 14),
                status='pending', reason='طلب تجريبي',
            ))
        db.session.commit()

        # احتساب رواتب الفترة الحالية (إن وجدت فترة نشطة)
        period = PayrollPeriod.query.filter_by(status='active').first()
        if period and not PayrollRecord.query.filter_by(period_id=period.id).first():
            from modules.payroll import PayrollCalculator
            PayrollCalculator.process_period(period)
        Setting.set('demo_seeded', date.today().isoformat())
        print("[+] Demo data seeded (بيانات تجريبية)")
    except Exception as e:
        print(f"[demo seed] {e}")


def reset_demo_data():
    """مسح البيانات التشغيلية وتهيئتها من جديد — للاستضافة العامة"""
    from config import Config
    if not getattr(Config, 'DEMO_MODE', False):
        return
    try:
        db.session.query(Attendance).delete()
        db.session.query(LeaveRequest).delete()
        db.session.query(LeaveBalance).delete()
        db.session.query(PayrollRecord).delete()
        db.session.query(LoanPayment).delete()
        db.session.query(OvertimeRequest).delete()
        db.session.query(Bonus).delete()
        db.session.query(Loan).delete()
        db.session.query(PayrollPeriod).delete()
        Setting.set('demo_seeded', '')
        db.session.commit()
        seed_default_data()
        seed_demo_data()
        print("[demo] تمت إعادة ضبط البيانات التجريبية")
    except Exception as e:
        db.session.rollback()
        print(f"[demo reset] {e}")


def wipe_all_data():
    """مسح جميع بيانات النظام والبدء من جديد (واجهة «إعادة ضبط النظام»).
    يعمل في كل الأوضاع (الديمو والعادي): يمسح الموظفين والحضور والإجازات والرواتب
    والسلف والمكافآت والتأمينات، ويعيد تهيئة البيانات الافتراضية (الأقسام والوظائف
    وأنواع الإجازات والإعدادات وفترة الرواتب الحالية) مع الإبقاء على حسابات المستخدمين.
    بعد المسح يتوقف إدخال البيانات التجريبية تلقائياً لإبقاء الداتا نظيفة للتسجيل من جديد."""
    try:
        # 1) فك ارتباط مديري الأقسام أولاً (يُشيرون للموظفين قبل حذفهم)
        for dept in Department.query.all():
            dept.manager_id = None
        db.session.flush()
        # 2) حذف السجلات التابعة ثم الجداول الرئيسية (ترتيب تصاعدي حسب التبعية)
        db.session.query(Attendance).delete()
        db.session.query(LeaveRequest).delete()
        db.session.query(LeaveBalance).delete()
        db.session.query(PayrollRecord).delete()
        db.session.query(LoanPayment).delete()
        db.session.query(OvertimeRequest).delete()
        db.session.query(Bonus).delete()
        db.session.query(Loan).delete()
        db.session.query(PayrollPeriod).delete()
        db.session.query(Employee).delete()
        # 3) التصنيفات والإعدادات (التي سيعيدها الافتراضي لاحقاً)
        db.session.query(Department).delete()
        db.session.query(Position).delete()
        db.session.query(LeaveType).delete()
        db.session.query(DeductionType).delete()
        db.session.query(BonusType).delete()
        db.session.query(AllowanceType).delete()
        db.session.query(FingerprintDevice).delete()
        db.session.query(Setting).delete()
        db.session.commit()
        # 4) تهيئة البيانات الافتراضية من جديد (أقسام، وظائف، أنواع إجازات، إعدادات، فترة رواتب)
        seed_default_data()
        # 5) منع إرجاع البيانات التجريبية تلقائياً بعد المسح (تظل الداتا نظيفة)
        Setting.set('demo_data', 'off')
        Setting.set('demo_seeded', date.today().isoformat())
        print("[+] Wipe completed: system cleared and ready for fresh data entry")
        return True
    except Exception as e:
        db.session.rollback()
        print(f"[wipe] {e}")
        return False


if __name__ == '__main__':
    with app.app_context():
        create_database()
        seed_default_data()
        add_sample_employee()
    print("\n[√] Database initialized successfully!")
    print("    Users:")
    print("    - admin / admin123 (مدير النظام)")
    print("    - hr / hr123 (مدير الموارد البشرية)")
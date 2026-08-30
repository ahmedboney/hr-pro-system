from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """مستخدمي النظام (مدير النظام، مدير HR، موظف)"""
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='employee')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Department(db.Model):
    """أقسام الشركة"""
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('employees.id'))
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employees = db.relationship('Employee', backref='department', lazy='dynamic', foreign_keys='Employee.department_id')
    manager = db.relationship('Employee', foreign_keys=[manager_id])


class Position(db.Model):
    """الوظائف/المسميات الوظيفية"""
    __tablename__ = 'positions'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employees = db.relationship('Employee', backref='position', lazy='dynamic')


class Shift(db.Model):
    """نظام الورديات — مواعيد عمل بديلة عن المواعيد الموحدة"""
    __tablename__ = 'shifts'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    start_time = db.Column(db.Time, nullable=False, default=lambda: datetime.strptime('08:00', '%H:%M').time())
    end_time = db.Column(db.Time, nullable=False, default=lambda: datetime.strptime('17:00', '%H:%M').time())
    late_tolerance = db.Column(db.Integer, default=15)
    grace_minutes_out = db.Column(db.Integer, default=30)
    allowance_percent = db.Column(db.Float, default=0, nullable=False)
    description = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employees = db.relationship('Employee', back_populates='shift_obj', lazy='dynamic', foreign_keys='Employee.shift_id')
    attendances = db.relationship('Attendance', back_populates='shift_obj', lazy='dynamic', foreign_keys='Attendance.shift_id')

    @property
    def hours_label(self):
        return f"{self.start_time.strftime('%I:%M %p')} - {self.end_time.strftime('%I:%M %p')}"


class Employee(db.Model):
    """الموظفين"""
    __tablename__ = 'employees'
    id = db.Column(db.Integer, primary_key=True)
    emp_id = db.Column(db.String(20), unique=True, nullable=False)
    fingerprint_id = db.Column(db.String(30), unique=True, nullable=True)
    shift_id = db.Column(db.Integer, db.ForeignKey('shifts.id'))

    shift_obj = db.relationship('Shift', back_populates='employees', foreign_keys=[shift_id])
    
    # Personal Info
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    national_id = db.Column(db.String(20), unique=True, nullable=True)
    birth_date = db.Column(db.Date)
    gender = db.Column(db.String(10))
    marital_status = db.Column(db.String(20))
    religion = db.Column(db.String(20))
    
    # Contact
    phone = db.Column(db.String(20))
    address = db.Column(db.String(200))
    email = db.Column(db.String(100))
    emergency_contact = db.Column(db.String(100))
    emergency_phone = db.Column(db.String(20))
    
    # Employment
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    position_id = db.Column(db.Integer, db.ForeignKey('positions.id'))
    hire_date = db.Column(db.Date, default=date.today)
    employment_type = db.Column(db.String(20), default='full_time')  # full_time, part_time, contract
    status = db.Column(db.String(20), default='active')  # active, on_leave, terminated
    
    # Financial
    base_salary = db.Column(db.Numeric(12, 2), default=0)
    housing_allowance = db.Column(db.Numeric(12, 2), default=0)
    transport_allowance = db.Column(db.Numeric(12, 2), default=0)
    food_allowance = db.Column(db.Numeric(12, 2), default=0)
    phone_allowance = db.Column(db.Numeric(12, 2), default=0)
    other_allowances = db.Column(db.Numeric(12, 2), default=0)
    bank_account = db.Column(db.String(30))
    
    # System
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def total_salary(self):
        return float(self.base_salary) + float(self.housing_allowance) + \
               float(self.transport_allowance) + float(self.food_allowance) + \
               float(self.phone_allowance) + float(self.other_allowances)

    @property
    def daily_rate(self):
        return round(self.total_salary / 30, 2) if self.total_salary else 0

    @property
    def hourly_rate(self):
        return round(self.daily_rate / 8, 2) if self.daily_rate else 0

    @property
    def attendance_records(self):
        return Attendance.query.filter_by(employee_id=self.id).order_by(Attendance.date.desc())

    def __repr__(self):
        return f'<Employee {self.emp_id}: {self.full_name}>'


class FingerprintDevice(db.Model):
    """أجهزة البصمة"""
    __tablename__ = 'fingerprint_devices'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    device_ip = db.Column(db.String(50))
    model = db.Column(db.String(100))
    location = db.Column(db.String(200))
    serial_number = db.Column(db.String(100))
    device_type = db.Column(db.String(20), default='zkteco')  # zkteco, biometrica, etc
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Attendance(db.Model):
    """سجلات الحضور والانصراف"""
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    check_in_time = db.Column(db.Time)
    check_out_time = db.Column(db.Time)
    overtime_hours = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='present')  # present, absent, late, leave, holiday
    late_minutes = db.Column(db.Integer, default=0)
    early_leave_minutes = db.Column(db.Integer, default=0)
    shift_id = db.Column(db.Integer, db.ForeignKey('shifts.id'))
    device_id = db.Column(db.Integer, db.ForeignKey('fingerprint_devices.id'))

    shift_obj = db.relationship('Shift', back_populates='attendances', foreign_keys=[shift_id])
    notes = db.Column(db.String(200))

    employee = db.relationship('Employee', backref='all_attendance')

    __table_args__ = (db.UniqueConstraint('employee_id', 'date', name='unique_attendance_per_day'),)

    @property
    def worked_hours(self):
        if self.check_in_time and self.check_out_time:
            in_min = self.check_in_time.hour * 60 + self.check_in_time.minute
            out_min = self.check_out_time.hour * 60 + self.check_out_time.minute
            if out_min < in_min:
                out_min += 24 * 60
            return round((out_min - in_min) / 60, 2)
        return 0


class LeaveType(db.Model):
    """أنواع الإجازات"""
    __tablename__ = 'leave_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    paid = db.Column(db.Boolean, default=True)
    max_days_per_year = db.Column(db.Integer)
    max_consecutive_days = db.Column(db.Integer)
    description = db.Column(db.Text)
    color = db.Column(db.String(20), default='#3498db')


class LeaveRequest(db.Model):
    """طلبات الإجازات"""
    __tablename__ = 'leave_requests'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_types.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected, cancelled
    hours = db.Column(db.Float, nullable=True)  # إجازة جزئية بالساعات (يوم العمل القياسي = 8 ساعات)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_at = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    employee = db.relationship('Employee', backref='leave_requests')
    leave_type = db.relationship('LeaveType')

    @property
    def days_count(self):
        return (self.end_date - self.start_date).days + 1

    @property
    def leave_days(self):
        """قيمة الإجازة بأيام العمل القياسية: يوم = 8 ساعات بغض النظر عن مدة الوردية.
        إن حُدّدت ساعات جزئية تُحسب كأجزاء يوم، وإلا فتُحسب الأيام التقويمية كاملة."""
        if self.hours:
            return round(float(self.hours) / 8.0, 2)
        return self.days_count

    @property
    def is_partial(self):
        return bool(self.hours)


class LeaveBalance(db.Model):
    """أرصدة الإجازات"""
    __tablename__ = 'leave_balances'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_types.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    entitled_days = db.Column(db.Integer, default=0)
    used_days = db.Column(db.Integer, default=0)
    remaining_days = db.Column(db.Integer, default=0)

    employee = db.relationship('Employee', backref='leave_balances')
    leave_type = db.relationship('LeaveType')

    __table_args__ = (db.UniqueConstraint('employee_id', 'leave_type_id', 'year', name='unique_balance'),)


class AllowanceType(db.Model):
    """أنواع البدلات"""
    __tablename__ = 'allowance_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)


class DeductionType(db.Model):
    """أنواع الخصومات"""
    __tablename__ = 'deduction_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)


class PayrollPeriod(db.Model):
    """فترات الرواتب"""
    __tablename__ = 'payroll_periods'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)  # e.g. "2024-01"
    period_month = db.Column(db.Integer, nullable=False)
    period_year = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(20), default='active')  # active, processed, closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime)


class PayrollRecord(db.Model):
    """سجلات الرواتب الفردية"""
    __tablename__ = 'payroll_records'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    period_id = db.Column(db.Integer, db.ForeignKey('payroll_periods.id'), nullable=False)
    
    # Income Components
    base_salary = db.Column(db.Float, default=0)
    housing_allowance = db.Column(db.Float, default=0)
    transport_allowance = db.Column(db.Float, default=0)
    food_allowance = db.Column(db.Float, default=0)
    phone_allowance = db.Column(db.Float, default=0)
    other_allowances = db.Column(db.Float, default=0)
    shift_allowance = db.Column(db.Float, default=0)
    overtime_amount = db.Column(db.Float, default=0)
    bonus_amount = db.Column(db.Float, default=0)
    
    # Deductions
    absent_days = db.Column(db.Integer, default=0)
    late_minutes_total = db.Column(db.Integer, default=0)
    absent_deduction = db.Column(db.Float, default=0)
    late_deduction = db.Column(db.Float, default=0)
    social_insurance = db.Column(db.Float, default=0)
    tax_amount = db.Column(db.Float, default=0)
    loan_deduction = db.Column(db.Float, default=0)
    other_deductions = db.Column(db.Float, default=0)
    
    # Unpaid leave
    unpaid_leave_days = db.Column(db.Integer, default=0)
    unpaid_leave_deduction = db.Column(db.Float, default=0)
    
    # Totals
    gross_salary = db.Column(db.Float, default=0)
    total_deductions = db.Column(db.Float, default=0)
    net_salary = db.Column(db.Float, default=0)
    
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, paid
    paid_date = db.Column(db.Date)
    
    employee = db.relationship('Employee', backref='payroll_records')
    period = db.relationship('PayrollPeriod')

    __table_args__ = (db.UniqueConstraint('employee_id', 'period_id', name='unique_employee_period'),)


class Loan(db.Model):
    """سلف وقروض الموظفين"""
    __tablename__ = 'loans'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    loan_type = db.Column(db.String(50), default='savings')  # savings (سلفة), loan (قرض)
    amount = db.Column(db.Float, nullable=False)
    installment_count = db.Column(db.Integer, default=1)
    installment_amount = db.Column(db.Float)
    remaining_amount = db.Column(db.Float)
    start_date = db.Column(db.Date, default=date.today)
    status = db.Column(db.String(20), default='active')  # active, paid, cancelled
    reason = db.Column(db.Text)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    employee = db.relationship('Employee', backref='loans')


class LoanPayment(db.Model):
    """أقساط القروض المدفوعة"""
    __tablename__ = 'loan_payments'
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loans.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_date = db.Column(db.Date, default=date.today)
    period_id = db.Column(db.Integer, db.ForeignKey('payroll_periods.id'))
    notes = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    loan = db.relationship('Loan')
    period = db.relationship('PayrollPeriod')


class BonusType(db.Model):
    """أنواع المكافآت والحوافز"""
    __tablename__ = 'bonus_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)


class Bonus(db.Model):
    """مكافآت وحوافز الموظفين"""
    __tablename__ = 'bonuses'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    bonus_type_id = db.Column(db.Integer, db.ForeignKey('bonus_types.id'))
    amount = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, default=date.today)
    reason = db.Column(db.Text)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    employee = db.relationship('Employee', backref='bonuses')
    bonus_type = db.relationship('BonusType')


class Setting(db.Model):
    """إعدادات النظام"""
    __tablename__ = 'settings'
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(500))
    description = db.Column(db.String(200))

    @staticmethod
    def get(key, default=None):
        setting = Setting.query.filter_by(key=key).first()
        return setting.value if setting else default

    @staticmethod
    def set(key, value):
        setting = Setting.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = Setting(key=key, value=value)
            db.session.add(setting)
        db.session.commit()


class OvertimeRequest(db.Model):
    """طلبات العمل الإضافي"""
    __tablename__ = 'overtime_requests'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    hours = db.Column(db.Float)
    rate_multiplier = db.Column(db.Float, default=1.5)
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    employee = db.relationship('Employee', backref='overtime_requests')

    @property
    def amount(self):
        if self.hours:
            return round(self.hours * self.employee.hourly_rate * self.rate_multiplier, 2)
        return 0


class AuditLog(db.Model):
    """سجل النشاط: توثيق كل إجراء مهم (من فعل ماذا ومتى)"""
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    user_role = db.Column(db.String(20), nullable=False, default='')
    action = db.Column(db.String(120), nullable=False)
    details = db.Column(db.String(400), default='')
    ip = db.Column(db.String(45), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
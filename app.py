import os
import csv
import io
import hmac
from datetime import date, datetime, timedelta
from functools import wraps
from time import time as _now
from collections import defaultdict

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    jsonify, session, send_file, Response
)
from werkzeug.utils import secure_filename

from config import Config
from models import (
    db, User, Department, Position, Employee, FingerprintDevice, Attendance,
    LeaveType, LeaveRequest, LeaveBalance, DeductionType, BonusType, Bonus,
    PayrollPeriod, PayrollRecord, Loan, LoanPayment, Setting, OvertimeRequest,
    AuditLog, Shift
)
from modules.fingerprint import FingerprintManager, SimulatorDevice
from modules.payroll import PayrollCalculator
from modules.reports import ReportGenerator
from modules import excel_export
from modules import pdf_export
from modules import backup as backup_module
from modules.notifications import get_notifications
from modules import scheduler


app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)


# ==================== Helper Functions ====================

DEMO_MODE = bool(getattr(Config, 'DEMO_MODE', False))

# ===== الصلاحيات: admin كامل | hr موارد بشرية | account شؤون مالية | viewer عرض فقط =====
VALID_ROLES = {
    'admin': 'مدير النظام',
    'hr': 'موارد بشرية',
    'account': 'محاسب / شؤون مالية',
    'viewer': 'مشاهدة فقط',
}
ROLE_LEVEL = {'admin': 100, 'hr': 60, 'account': 50, 'viewer': 0}


def auto_login():
    """تسجيل دخول تلقائي (بدون صفحة دخول) بصلاحيات مدير النظام.
    لا يعمل في وضع DEMO_MODE حيث يُطلب تسجيل دخول حقيقي.
    كما لا يعمل مباشرة بعد «تسجيل الخروج» حتى يتمكن المستخدم من الدخول ببياناته.
    الأمان: الدخول التلقائي يكون فقط من نفس الجهاز (localhost) ما لم تُفعَّل
    AUTO_LOGIN=all (كل الشبكة) أو AUTO_LOGIN=lan (كل الأجهزة الداخلية) في المتغيرات."""
    if DEMO_MODE:
        return
    if session.get('_just_logged_out'):
        return
    if session.get('user_id'):
        return
    mode = os.environ.get('AUTO_LOGIN', 'local').strip().lower()
    if mode in ('1', 'true', 'all'):
        pass
    else:
        ip = request.remote_addr or ''
        if mode == 'lan':
            if ip in ('127.0.0.1', '::1'):
                return
        elif ip not in ('127.0.0.1', '::1'):
            return
    user = User.query.filter_by(role='admin').first() or User.query.first()
    if user:
        session['user_id'] = user.id
        session['username'] = user.username
        session['role'] = user.role


def _ensure_auth(role=None):
    """تأمين الوصول للصفحات: في الوضع العادي دخول تلقائي، وفي الديمو تحقق من الجلسة والصلاحية."""
    if not DEMO_MODE:
        auto_login()
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return None
    uid = session.get('user_id')
    user = User.query.get(uid) if uid else None
    if not user or not user.is_active:
        session.clear()
        return redirect(url_for('login'))
    if role and user.role != role:
        flash('غير مصرح لك بالوصول إلى هذه الصفحة', 'danger')
        return redirect(url_for('dashboard'))
    return None


def login_required(f):
    """حماية الصفحة بشرط تسجيل الدخول"""
    @wraps(f)
    def decorated(*args, **kwargs):
        res = _ensure_auth()
        if res is not None:
            return res
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """حماية الصفحة بشرط صلاحية المدير فقط"""
    @wraps(f)
    def decorated(*args, **kwargs):
        res = _ensure_auth('admin')
        if res is not None:
            return res
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    auto_login()
    user_id = session.get('user_id')
    return User.query.get(user_id) if user_id else None


def log_action(action, details=''):
    """توثيق إجراء في سجل النشاط (لا يُفشِل العملية أبداً عند أي خطأ)"""
    try:
        from flask import request as _req
        user = get_current_user()
        entry = AuditLog(
            username=(user.username if user else '—'),
            user_role=(user.role if user else '—'),
            action=str(action)[:120],
            details=str(details)[:400],
            ip=(_req.remote_addr or '')[:45],
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


@app.context_processor
def inject_user():
    return {
        'current_user': get_current_user(),
        'today': date.today(),
        'demo_mode': DEMO_MODE,
    }


# ==================== Security: CSRF + API ====================

CSRF_EXEMPT_ENDPOINTS = {'api_fingerprint_punch'}

# حدود المحاولات لكل عنوان IP (حماية من التخمين والاختراق)
_login_attempts = defaultdict(list)
_api_attempts = defaultdict(list)


def _prune(store, ip, window):
    now = _now()
    store[ip] = [t for t in store[ip] if now - t < window]


def rate_limited(store, ip, limit, window):
    _prune(store, ip, window)
    if len(store[ip]) >= limit:
        return True
    store[ip].append(_now())
    return False


@app.context_processor
def inject_csrf():
    return {'csrf_token': csrf_token}


def csrf_token():
    """توليد رمز CSRF خاص بالجلسة للوقاية من هجمات النماذج"""
    from secrets import token_hex
    if '_csrf_token' not in session:
        session['_csrf_token'] = token_hex(16)
    return session['_csrf_token']


@app.before_request
def verify_csrf():
    if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
        if request.endpoint in CSRF_EXEMPT_ENDPOINTS:
            return None
        token = request.headers.get('X-CSRFToken') or request.form.get('_csrf_token')
        expected = session.get('_csrf_token', '')
        if not token or not expected or not hmac.compare_digest(str(token), str(expected)):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'رمز CSRF غير صالح أو مفقود'}), 403
            flash('انتهت صلاحية النموذج، حاول مرة أخرى', 'danger')
            return redirect(request.referrer or url_for('dashboard'))
    return None


@app.before_request
def enforce_viewer_readonly():
    """حساب «مشاهدة فقط» لا يستطيع تعديل أو حذف أي شيء (قراءة فقط شاملة)"""
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    if request.path.startswith(('/login', '/logout')):
        return None
    uid = session.get('user_id')
    user = User.query.get(uid) if uid else None
    if user and user.role == 'viewer':
        if request.path.startswith('/api/'):
            return jsonify({'error': 'حساب العرض فقط، التعديل غير مسموح'}), 403
        flash('حسابك للعرض فقط — لا يمكنك تنفيذ تعديلات', 'danger')
        return redirect(request.referrer or url_for('dashboard'))
    return None


_ACCOUNT_BLOCKED_PREFIXES = (
    '/employees', '/departments', '/positions',
    '/attendance', '/leaves', '/fingerprint', '/settings',
)


@app.before_request
def enforce_account_scope():
    """دور «محاسب/شؤون مالية» يقرأ كل شيء لكن لا يعدّل الموظفين/الحضور/الإجازات/الإعدادات"""
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    if request.path.startswith(('/login', '/logout')):
        return None
    uid = session.get('user_id')
    user = User.query.get(uid) if uid else None
    if user and user.role == 'account':
        for prefix in _ACCOUNT_BLOCKED_PREFIXES:
            if request.path.startswith(prefix):
                flash('حساب المحاسب لا يملك صلاحية تنفيذ هذا التعديل', 'danger')
                return redirect(request.referrer or url_for('dashboard'))
    return None


@app.after_request
def security_headers(resp):
    """رؤوس أمان تُرسل مع كل استجابة (حماية XSS/Clickjacking/MIME)"""
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    resp.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    resp.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    resp.headers['Content-Security-Policy'] = csp
    return resp


DEMO_ACCOUNT_READY = False


def ensure_demo_account():
    """في وضع الديمو: حساب تجريبي واحد فقط (لا يوجد أي حساب admin)"""
    global DEMO_ACCOUNT_READY
    if not DEMO_MODE or DEMO_ACCOUNT_READY:
        return
    DEMO_ACCOUNT_READY = True
    if User.query.filter_by(username='demo').first():
        return
    user = User(username='demo', full_name='حساب تجريبي', role='hr', is_active=True)
    user.set_password('demo1234')
    db.session.add(user)
    db.session.commit()


def get_api_key():
    """مفتاح API (يولّد تلقائياً ويظهر في صفحة الإعدادات)"""
    from secrets import token_hex
    key = Setting.get('api_key')
    if not key:
        key = 'HR-' + token_hex(12).upper()
        Setting.set('api_key', key)
    return key


def fmt_date(d):
    return d.strftime('%Y-%m-%d') if d else ''


def fmt_money(amount):
    return f"{float(amount):,.2f}"


app.jinja_env.globals['fmt_date'] = fmt_date
app.jinja_env.globals['fmt_money'] = fmt_money


def get_company_name():
    return Setting.get('company_name', 'شركتي')


def get_amount_words(amount):
    """Convert number to Arabic words (simple version)"""
    amount = float(amount or 0)
    whole = int(amount)
    fractions = int(round((amount - whole) * 100))
    
    ones = ['', 'واحد', 'اثنان', 'ثلاثة', 'أربعة', 'خمسة', 'ستة', 'سبعة', 'ثمانية', 'تسعة',
            'عشرة', 'أحد عشر', 'اثنا عشر', 'ثلاثة عشر', 'أربعة عشر', 'خمسة عشر', 'ستة عشر',
            'سبعة عشر', 'ثمانية عشر', 'تسعة عشر']
    tens = ['', '', 'عشرون', 'ثلاثون', 'أربعون', 'خمسون', 'ستون', 'سبعون', 'ثمانون', 'تسعون']
    hundreds = ['', 'مائة', 'مائتان', 'ثلاثمائة', 'أربعمائة', 'خمسمائة', 'ستمائة', 'سبعمائة', 'ثمانمائة', 'تسعمائة']
    
    def three_digits(n):
        words = []
        h = n // 100
        if h:
            words.append(hundreds[h])
        n = n % 100
        if n < 20 and n > 0:
            words.append(ones[n])
        elif n >= 20:
            words.append(tens[n // 10])
            if n % 10:
                words.append('و' + ones[n % 10])
        return ' '.join(words)
    
    def thousands(n):
        if n == 0:
            return ''
        k = n // 1000
        rest = three_digits(n % 1000)
        if k:
            word = ' ألف' if k == 1 else ' ألفًا'
            if rest:
                return three_digits(k) + word + ' و' + rest
            return three_digits(k) + word
        return rest
    
    words = thousands(whole) if whole else 'صفر'
    result = f"{words} جنيهًا مصريًا"
    if fractions:
        frac_words = three_digits(fractions)
        result += f" و{frac_words} قرشًا"
    return result


app.jinja_env.globals['get_company_name'] = get_company_name
app.jinja_env.globals['get_amount_words'] = get_amount_words
app.jinja_env.globals['setting'] = lambda key, default=None: Setting.get(key, default)


# ==================== Authentication ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if not DEMO_MODE:
        if not session.get('_just_logged_out'):
            auto_login()
            if session.get('user_id'):
                return redirect(url_for('dashboard'))
        if request.method == 'POST':
            return _do_login()
        return render_template('login.html', demo_credentials=False)

    ensure_demo_account()
    if request.method == 'POST':
        return _do_login()
    return render_template('login.html', demo_credentials=True)


def _do_login():
    """معالجة نموذج تسجيل الدخول (بيانات المستخدم الصحيحة أو الرسالة المناسبة)"""
    ip = request.remote_addr or '0.0.0.0'
    if rate_limited(_login_attempts, ip, 8, 600):
        flash('محاولات دخول كثيرة. انتظر 10 دقائق ثم حاول مرة أخرى.', 'danger')
        return redirect(url_for('login'))
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    user = User.query.filter_by(username=username).first()
    if user and user.is_active and user.check_password(password):
        session.clear()
        session['user_id'] = user.id
        session['username'] = user.username
        session['role'] = user.role
        session['_csrf_token'] = csrf_token()
        _login_attempts.pop(ip, None)
        log_action('تسجيل دخول', f"الدخول بواسطة {username}")
        return redirect(url_for('dashboard'))
    if user and not user.is_active:
        flash('هذا الحساب موقوف', 'danger')
    else:
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    return redirect(url_for('login'))


@app.route('/logout')
def logout():
    session.clear()
    session['_just_logged_out'] = True
    return redirect(url_for('login'))


# ==================== Dashboard ====================

@app.route('/')
@login_required
def dashboard():
    today = date.today()
    current_month = today.month
    current_year = today.year

    stats = {
        'total_employees': Employee.query.filter_by(status='active').count(),
        'total_departments': Department.query.count(),
        'present_today': Attendance.query.filter_by(
            date=today, status='present'
        ).count() + Attendance.query.filter_by(date=today, status='late').count(),
        'absent_today': 0,
        'on_leave_today': LeaveRequest.query.filter(
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= today,
            LeaveRequest.end_date >= today
        ).count(),
        'pending_leaves': LeaveRequest.query.filter_by(status='pending').count(),
        'active_loans': Loan.query.filter_by(status='active').count(),
        'total_payroll_m': None,
        'late_today': Attendance.query.filter_by(date=today, status='late').count(),
    }

    # Absent = active employees not present and not on leave
    all_active = Employee.query.filter_by(status='active').count()
    present = stats['present_today']
    stats['absent_today'] = max(0, all_active - present - stats['on_leave_today'])

    # This month payroll
    period = PayrollPeriod.query.filter_by(
        period_month=current_month, period_year=current_year
    ).first()
    if period:
        records = PayrollRecord.query.filter_by(period_id=period.id).all()
        stats['total_payroll_m'] = round(sum(r.net_salary for r in records), 2)

    # Recent attendance
    recent_attendance = Attendance.query.filter_by(date=today).order_by(
        Attendance.check_in_time.desc()
    ).limit(8).all()

    # Pending leave requests
    pending_requests = LeaveRequest.query.filter_by(status='pending').order_by(
        LeaveRequest.created_at.desc()
    ).limit(5).all()

    # Department distribution
    departments = Department.query.all()
    dept_stats = [
        {
            'name': d.name,
            'count': d.employees.filter_by(status='active').count()
        } for d in departments if d.employees.filter_by(status='active').count() > 0
    ]

    # Recent payroll (last period)
    last_period = PayrollPeriod.query.filter_by(status='processed').order_by(
        PayrollPeriod.id.desc()
    ).first()
    if last_period:
        last_period.record_count = PayrollRecord.query.filter_by(
            period_id=last_period.id
        ).count()

    return render_template(
        'dashboard.html',
        stats=stats,
        recent_attendance=recent_attendance,
        pending_requests=pending_requests,
        dept_stats=dept_stats,
        last_period=last_period,
        today=today,
        notifications=get_notifications(),
        api_url=f"{request.host_url.rstrip('/')}/api/fingerprint/punch",
    )


# ==================== Employees ====================

@app.route('/employees')
@login_required
def employees_list():
    q = request.args.get('q', '').strip()
    dept_id = request.args.get('dept', '')
    status = request.args.get('status', '')

    query = Employee.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Employee.emp_id.like(like),
                Employee.first_name.like(like),
                Employee.last_name.like(like),
                Employee.fingerprint_id.like(like),
                Employee.phone.like(like),
            )
        )
    if dept_id:
        query = query.filter_by(department_id=int(dept_id))
    if status:
        query = query.filter_by(status=status)

    employees = query.order_by(Employee.emp_id).all()
    departments = Department.query.all()
    return render_template(
        'employees/list.html',
        employees=employees,
        departments=departments,
        q=q,
        dept_id=dept_id,
        status=status,
    )


@app.route('/employees/new', methods=['GET', 'POST'])
@login_required
def employee_new():
    departments = Department.query.all()
    positions = Position.query.all()
    shifts = Shift.query.filter_by(is_active=True).all()
    if request.method == 'POST':
        try:
            emp = Employee()
            emp.emp_id = request.form['emp_id'].strip()
            emp.fingerprint_id = request.form.get('fingerprint_id', '').strip() or None
            emp.first_name = request.form['first_name'].strip()
            emp.last_name = request.form['last_name'].strip()
            emp.shift_id = int(request.form['shift_id']) if request.form.get('shift_id') else None
            emp.national_id = request.form.get('national_id', '').strip() or None
            emp.birth_date = parse_date(request.form.get('birth_date'))
            emp.gender = request.form.get('gender')
            emp.marital_status = request.form.get('marital_status')
            emp.phone = request.form.get('phone', '').strip()
            emp.address = request.form.get('address', '').strip()
            emp.email = request.form.get('email', '').strip()
            emp.emergency_contact = request.form.get('emergency_contact', '').strip()
            emp.emergency_phone = request.form.get('emergency_phone', '').strip()
            emp.department_id = int(request.form['department_id']) if request.form.get('department_id') else None
            emp.position_id = int(request.form['position_id']) if request.form.get('position_id') else None
            emp.hire_date = parse_date(request.form.get('hire_date')) or date.today()
            emp.employment_type = request.form.get('employment_type', 'full_time')
            emp.status = request.form.get('status', 'active')
            emp.base_salary = parse_float(request.form.get('base_salary'))
            emp.housing_allowance = parse_float(request.form.get('housing_allowance'))
            emp.transport_allowance = parse_float(request.form.get('transport_allowance'))
            emp.food_allowance = parse_float(request.form.get('food_allowance'))
            emp.phone_allowance = parse_float(request.form.get('phone_allowance'))
            emp.other_allowances = parse_float(request.form.get('other_allowances'))
            emp.bank_account = request.form.get('bank_account', '').strip()

            # Validate uniqueness
            if Employee.query.filter_by(emp_id=emp.emp_id).first():
                flash('رقم الموظف موجود بالفعل', 'danger')
                return render_template('employees/form.html', employee=emp, departments=departments, positions=positions, shifts=shifts, is_edit=False)
            if emp.fingerprint_id and Employee.query.filter_by(fingerprint_id=emp.fingerprint_id).first():
                flash('رقم البصمة موجود بالفعل', 'danger')
                return render_template('employees/form.html', employee=emp, departments=departments, positions=positions, shifts=shifts, is_edit=False)

            db.session.add(emp)
            db.session.flush()

            # Create leave balances for current year
            current_year = date.today().year
            for lt in LeaveType.query.all():
                if lt.max_days_per_year and lt.max_days_per_year > 0:
                    db.session.add(LeaveBalance(
                        employee_id=emp.id,
                        leave_type_id=lt.id,
                        year=current_year,
                        entitled_days=lt.max_days_per_year,
                        used_days=0,
                        remaining_days=lt.max_days_per_year
                    ))

            db.session.commit()
            from init_db import mark_system_configured
            mark_system_configured()
            log_action('إضافة موظف', f"{emp.full_name} — {emp.emp_id}")
            flash(f"تم إضافة الموظف {emp.full_name} بنجاح", 'success')
            return redirect(url_for('employee_view', emp_id=emp.id))
        except Exception as e:
            db.session.rollback()
            flash(f"خطأ أثناء الحفظ: {str(e)}", 'danger')

    return render_template('employees/form.html', employee=None, departments=departments, positions=positions, shifts=shifts, is_edit=False)


@app.route('/employees/<int:emp_id>')
@login_required
def employee_view(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    current_year = date.today().year
    balances = LeaveBalance.query.filter_by(employee_id=emp.id, year=current_year).all()
    leave_requests = LeaveRequest.query.filter_by(employee_id=emp.id).order_by(LeaveRequest.created_at.desc()).limit(5).all()
    recent_attendance = Attendance.query.filter_by(employee_id=emp.id).order_by(Attendance.date.desc()).limit(10).all()
    loans = Loan.query.filter_by(employee_id=emp.id).all()
    bonuses = Bonus.query.filter_by(employee_id=emp.id).order_by(Bonus.date.desc()).limit(5).all()
    payroll_records = PayrollRecord.query.filter_by(employee_id=emp.id).order_by(PayrollRecord.id.desc()).limit(6).all()

    # Summary
    attendance_stats = emp.attendance_records
    total_present = Attendance.query.filter_by(employee_id=emp.id, status='present').count()
    total_late = Attendance.query.filter_by(employee_id=emp.id, status='late').count()

    return render_template(
        'employees/view.html',
        emp=emp,
        balances=balances,
        leave_requests=leave_requests,
        recent_attendance=recent_attendance,
        loans=loans,
        bonuses=bonuses,
        payroll_records=payroll_records,
        total_present=total_present,
        total_late=total_late,
    )


@app.route('/employees/<int:emp_id>/edit', methods=['GET', 'POST'])
@login_required
def employee_edit(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    departments = Department.query.all()
    positions = Position.query.all()
    shifts = Shift.query.filter_by(is_active=True).all()
    if request.method == 'POST':
        try:
            emp.emp_id = request.form['emp_id'].strip()
            emp.fingerprint_id = request.form.get('fingerprint_id', '').strip() or None
            emp.first_name = request.form['first_name'].strip()
            emp.last_name = request.form['last_name'].strip()
            emp.shift_id = int(request.form['shift_id']) if request.form.get('shift_id') else None
            emp.national_id = request.form.get('national_id', '').strip() or None
            emp.birth_date = parse_date(request.form.get('birth_date'))
            emp.gender = request.form.get('gender')
            emp.marital_status = request.form.get('marital_status')
            emp.phone = request.form.get('phone', '').strip()
            emp.address = request.form.get('address', '').strip()
            emp.email = request.form.get('email', '').strip()
            emp.emergency_contact = request.form.get('emergency_contact', '').strip()
            emp.emergency_phone = request.form.get('emergency_phone', '').strip()
            emp.department_id = int(request.form['department_id']) if request.form.get('department_id') else None
            emp.position_id = int(request.form['position_id']) if request.form.get('position_id') else None
            emp.hire_date = parse_date(request.form.get('hire_date')) or date.today()
            emp.employment_type = request.form.get('employment_type', 'full_time')
            emp.status = request.form.get('status', 'active')
            emp.base_salary = parse_float(request.form.get('base_salary'))
            emp.housing_allowance = parse_float(request.form.get('housing_allowance'))
            emp.transport_allowance = parse_float(request.form.get('transport_allowance'))
            emp.food_allowance = parse_float(request.form.get('food_allowance'))
            emp.phone_allowance = parse_float(request.form.get('phone_allowance'))
            emp.other_allowances = parse_float(request.form.get('other_allowances'))
            emp.bank_account = request.form.get('bank_account', '').strip()

            # Check uniqueness excluding self
            dup = Employee.query.filter(
                Employee.emp_id == emp.emp_id,
                Employee.id != emp.id
            ).first()
            if dup:
                flash('رقم الموظف مستخدم من قبل موظف آخر', 'danger')
                return render_template('employees/form.html', employee=emp, departments=departments, positions=positions, shifts=shifts, is_edit=True)
            if emp.fingerprint_id:
                dup_fp = Employee.query.filter(
                    Employee.fingerprint_id == emp.fingerprint_id,
                    Employee.id != emp.id
                ).first()
                if dup_fp:
                    flash('رقم البصمة مستخدم من قبل موظف آخر', 'danger')
                    return render_template('employees/form.html', employee=emp, departments=departments, positions=positions, shifts=shifts, is_edit=True)

            db.session.commit()
            log_action('تعديل موظف', f"{emp.full_name} — {emp.emp_id}")
            flash(f"تم تحديث بيانات {emp.full_name} بنجاح", 'success')
            return redirect(url_for('employee_view', emp_id=emp.id))
        except Exception as e:
            db.session.rollback()
            flash(f"خطأ أثناء الحفظ: {str(e)}", 'danger')

    return render_template('employees/form.html', employee=emp, departments=departments, positions=positions, shifts=shifts, is_edit=True)


@app.route('/employees/<int:emp_id>/delete', methods=['POST'])
@login_required
def employee_delete(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    name = emp.full_name
    emp.status = 'terminated'
    db.session.commit()
    log_action('إنهاء خدمة موظف', f"{name} — {emp.emp_id}")
    flash(f"تم أنهاء خدمة الموظف {name}", 'info')
    return redirect(url_for('employees_list'))


# ==================== Fingerprint & Devices ====================

@app.route('/fingerprint')
@login_required
def fingerprint_index():
    devices = FingerprintDevice.query.all()
    employees_with_fp = Employee.query.filter(Employee.fingerprint_id.isnot(None)).all()
    employees_without_fp = Employee.query.filter(Employee.fingerprint_id.is_(None)).count()
    
    enrolled_count = Employee.query.filter(Employee.fingerprint_id.isnot(None)).count()
    return render_template(
        'fingerprint/devices.html',
        devices=devices,
        employees_with_fp=employees_with_fp,
        employees_without_fp=employees_without_fp,
        enrolled_count=enrolled_count,
        total_employees=Employee.query.count(),
    )


@app.route('/fingerprint/add', methods=['GET', 'POST'])
@login_required
def fingerprint_add():
    if request.method == 'POST':
        device = FingerprintDevice()
        device.name = request.form.get('name', '').strip()
        device.device_ip = request.form.get('device_ip', '').strip()
        device.model = request.form.get('model', '').strip()
        device.location = request.form.get('location', '').strip()
        device.device_type = request.form.get('device_type', 'simulator')
        device.status = request.form.get('status', 'active')
        
        if not device.name:
            flash('اسم الجهاز مطلوب', 'warning')
        else:
            db.session.add(device)
            db.session.commit()
            flash('تم إضافة الجهاز بنجاح', 'success')
            return redirect(url_for('fingerprint_index'))
    return render_template('fingerprint/devices.html', add_mode=True)


@app.route('/fingerprint/<int:device_id>/edit', methods=['POST'])
@login_required
def fingerprint_edit(device_id):
    device = FingerprintDevice.query.get_or_404(device_id)
    device.name = request.form.get('name', device.name).strip()
    device.device_ip = request.form.get('device_ip', device.device_ip).strip()
    device.model = request.form.get('model', device.model).strip()
    device.location = request.form.get('location', device.location).strip()
    device.device_type = request.form.get('device_type', device.device_type)
    device.status = request.form.get('status', device.status)
    db.session.commit()
    flash('تم تحديث الجهاز بنجاح', 'success')
    return redirect(url_for('fingerprint_index'))


@app.route('/fingerprint/<int:device_id>/delete', methods=['POST'])
@login_required
def fingerprint_delete(device_id):
    device = FingerprintDevice.query.get_or_404(device_id)
    db.session.delete(device)
    db.session.commit()
    flash('تم حذف الجهاز', 'info')
    return redirect(url_for('fingerprint_index'))


@app.route('/fingerprint/<int:device_id>/sync')
@login_required
def fingerprint_sync(device_id):
    device = FingerprintDevice.query.get_or_404(device_id)
    result = FingerprintManager.sync_attendance(device)
    flash(
        f"تمت المزامنة: {result['synced']} تسجيل، تخطي {result['skipped']}",
        'success' if not result['errors'] else 'warning'
    )
    for err in result['errors']:
        flash(err, 'danger')
    return redirect(url_for('attendance_list'))


@app.route('/fingerprint/simulate', methods=['GET', 'POST'])
@login_required
def fingerprint_simulate():
    """محاكاة بصمة لتجربة بدون جهاز حقيقي"""
    employees = Employee.query.filter(Employee.fingerprint_id.isnot(None)).all()
    if request.method == 'POST':
        fp_id = request.form.get('fingerprint_id', '').strip()
        mode = request.form.get('mode', 'auto')
        emp = Employee.query.filter_by(fingerprint_id=fp_id).first()
        if not emp:
            flash('رقم بصمة غير مسجل لأي موظف', 'danger')
        else:
            result = FingerprintManager.test_simulator_punch(fp_id, {'mode': mode})
            # Directly record if simulator
            device = FingerprintDevice.query.filter_by(device_type='simulator').first()
            if device:
                FingerprintManager.sync_attendance(device)
            flash(f"تم تسجيل بصمة {emp.full_name}: {result['message']}", 'success')
            return redirect(url_for('attendance_list'))
    return render_template('fingerprint/simulate.html', employees=employees)


# ==================== Attendance ====================

@app.route('/attendance')
@login_required
def attendance_list():
    today = date.today()
    sel_date = request.args.get('date', today.strftime('%Y-%m-%d'))
    try:
        att_date = datetime.strptime(sel_date, '%Y-%m-%d').date()
    except:
        att_date = today

    dept_id = request.args.get('dept', '')
    status_filter = request.args.get('status', '')

    query = Attendance.query.join(Employee).filter(Attendance.date == att_date)
    if dept_id:
        query = query.filter(Employee.department_id == int(dept_id))
    if status_filter:
        query = query.filter(Attendance.status == status_filter)

    records = query.order_by(Attendance.check_in_time).all()

    # All active employees for manual entry
    employees = Employee.query.filter_by(status='active').all()
    departments = Department.query.all()

    present = Attendance.query.filter_by(date=att_date, status='present').count()
    late = Attendance.query.filter_by(date=att_date, status='late').count()
    total_active = Employee.query.filter_by(status='active').count()
    on_leave = LeaveRequest.query.filter(
        LeaveRequest.status == 'approved',
        LeaveRequest.start_date <= att_date,
        LeaveRequest.end_date >= att_date
    ).count()
    absent = max(0, total_active - present - late - on_leave)

    return render_template(
        'attendance/list.html',
        records=records,
        employees=employees,
        departments=departments,
        att_date=att_date,
        sel_date=sel_date,
        dept_id=dept_id,
        status_filter=status_filter,
        present=present,
        late=late,
        absent=absent,
        on_leave=on_leave,
        total_active=total_active,
        today_now=datetime.now().strftime('%H:%M'),
    )


@app.route('/attendance/manual', methods=['POST'])
@login_required
def attendance_manual():
    emp_id = request.form.get('employee_id')
    action = request.form.get('action')  # 'check_in' or 'check_out'
    att_date = parse_date(request.form.get('date'))
    time_str = request.form.get('time')

    emp = Employee.query.get_or_404(int(emp_id))
    
    if not time_str:
        time_str = datetime.now().strftime('%H:%M')
    try:
        t = datetime.strptime(time_str, '%H:%M').time()
    except:
        t = datetime.now().time()

    existing = Attendance.query.filter_by(employee_id=emp.id, date=att_date).first()

    # تحديث تصنيف الوردية عند التسجيل اليدوي (نفس الوردية الحالية للموظف)
    if emp.shift_id:
        if existing:
            existing.shift_id = emp.shift_id
        attach_shift = emp.shift_id
    else:
        attach_shift = None

    # حساب التأخير حسب وردية الموظف عند تسجيل الحضور يدوياً
    if action == 'check_in':
        new_late = 0
        new_status = 'present'
        try:
            ws, we, tol, g = FingerprintManager._shift_times(emp)
            sh, sm = map(int, ws.split(':'))
            start_dt = datetime(att_date.year, att_date.month, att_date.day, sh, sm)
            late_min = (datetime.combine(att_date, t) - start_dt).total_seconds() / 60
            if late_min > tol:
                new_status = 'late'
                new_late = int(round(late_min))
        except Exception:
            pass

        if not existing:
            existing = Attendance(
                employee_id=emp.id,
                date=att_date,
                check_in_time=t,
                status=new_status,
                late_minutes=new_late,
                shift_id=attach_shift,
            )
            db.session.add(existing)
        else:
            existing.check_in_time = t
            existing.status = new_status
            existing.late_minutes = new_late
            existing.shift_id = attach_shift
    elif action == 'check_out':
        if not existing:
            existing = Attendance(
                employee_id=emp.id,
                date=att_date,
                check_out_time=t,
                status='present',
                shift_id=attach_shift,
            )
            db.session.add(existing)
        else:
            existing.check_out_time = t
            existing.shift_id = attach_shift

    db.session.commit()
    flash(f"تم تسجيل {action} للموظف {emp.full_name}", 'success')
    return redirect(url_for('attendance_list', date=fmt_date(att_date)))


@app.route('/attendance/<int:att_id>/update', methods=['POST'])
@login_required
def attendance_update(att_id):
    att = Attendance.query.get_or_404(att_id)
    emp = att.employee
    att.status = request.form.get('status', att.status)
    att.notes = request.form.get('notes', '')

    # تحديث تصنيف الوردية لكل تعديل يدوي (يتبع الوردية الحالية للموظف)
    if emp and emp.shift_id:
        att.shift_id = emp.shift_id

    if request.form.get('check_in'):
        att.check_in_time = datetime.strptime(request.form['check_in'], '%H:%M').time()
        # إعادة احتساب التأخير حسب وردية الموظف
        try:
            ws, _we, tol, _g = FingerprintManager._shift_times(emp)
            sh, sm = map(int, ws.split(':'))
            start_dt = datetime(att.date.year, att.date.month, att.date.day, sh, sm)
            late_min = (datetime.combine(att.date, att.check_in_time) - start_dt).total_seconds() / 60
            att.late_minutes = int(round(late_min)) if late_min > tol else 0
            if late_min > tol:
                att.status = 'late'
        except Exception:
            pass
    if request.form.get('check_out'):
        att.check_out_time = datetime.strptime(request.form['check_out'], '%H:%M').time()
    db.session.commit()
    flash('تم تحديث السجل', 'success')
    return redirect(url_for('attendance_list', date=fmt_date(att.date)))


@app.route('/attendance/import', methods=['GET', 'POST'])
@login_required
def attendance_import():
    """استيراد الحضور من ملف CSV (تصدير جهاز بصمة)"""
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename:
            flash('يرجى اختيار ملف', 'warning')
            return redirect(request.url)
        if not file.filename.lower().endswith('.csv'):
            flash('يُسمح فقط بملفات CSV (تصدير جهاز البصمة)', 'danger')
            return redirect(request.url)
        
        import_punch_format = request.form.get('format', 'zkteco')
        try:
            stream = io.StringIO(file.read().decode('utf-8-sig'))
            reader = csv.reader(stream)
            synced = 0
            skipped = 0
            for row in reader:
                if not row or len(row) < 2:
                    continue
                # ZKTeco format first 2 are sometimes the header
                if row[0] in ('USERID', '用户ID'):
                    continue
                
                fp_id = None
                ts = None
                if import_punch_format == 'zkteco':
                    # USERID, VERIFYTIME, ...
                    if len(row) >= 2:
                        fp_id = row[0].strip()
                        ts = row[1].strip()
                elif import_punch_format == 'simplified':
                    # user_id, timestamp
                    fp_id = row[0].strip()
                    ts = row[1].strip()

                if not fp_id or not ts:
                    skipped += 1
                    continue
                emp = Employee.query.filter_by(fingerprint_id=str(fp_id)).first()
                if not emp:
                    skipped += 1
                    continue
                try:
                    dt = datetime.strptime(ts[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                except:
                    try:
                        dt = datetime.fromisoformat(ts[:19])
                    except:
                        skipped += 1
                        continue
                
                punch_type = FingerprintManager._determine_punch_type(emp, dt)
                result = FingerprintManager._record_punch(emp, dt, None, punch_type)
                if result != 'skipped':
                    synced += 1
                else:
                    skipped += 1
            flash(f"تم استيراد {synced} سجل، تخطي {skipped}", 'success')
            return redirect(url_for('attendance_list'))
        except Exception as e:
            flash(f"خطأ في الاستيراد: {str(e)}", 'danger')
    return render_template('attendance/import.html')


@app.route('/attendance/report')
@login_required
def attendance_report():
    today = date.today()
    month = request.args.get('month', today.month, type=int)
    year = request.args.get('year', today.year, type=int)
    summary = ReportGenerator.monthly_attendance_summary(month, year)
    return render_template('attendance/report.html', summary=summary, month=month, year=year)


@app.route('/attendance/export')
@login_required
def attendance_export():
    """تصدير تقرير الحضور CSV"""
    month = request.args.get('month', date.today().month, type=int)
    year = request.args.get('year', date.today().year, type=int)
    summary = ReportGenerator.monthly_attendance_summary(month, year)
    
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['رقم الموظف', 'الاسم', 'القسم', 'أيام الحضور', 'أيام التأخير', 'أيام الغياب', 'ساعات إضافية', 'نسبة الحضور'])
    for item in summary:
        emp = item['employee']
        writer.writerow([
            emp.emp_id, emp.full_name,
            emp.department.name if emp.department else '-',
            item['present_days'], item['late_days'], item['absent_days'],
            item['overtime_hours'], f"{item['attendance_rate']}%"
        ])
    
    filename = f"attendance_{year}_{month}.csv"
    return Response(
        buf.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# ==================== Excel Exports ====================

XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def send_xlsx(data, filename):
    return send_file(
        io.BytesIO(data),
        mimetype=XLSX_MIME,
        as_attachment=True,
        download_name=filename
    )


@app.route('/export/employees')
@login_required
def export_employees_xlsx():
    employees = Employee.query.order_by(Employee.emp_id).all()
    data = excel_export.export_employees(employees)
    return send_xlsx(data, f"تقرير_الموظفين_{date.today().strftime('%Y-%m-%d')}.xlsx")


@app.route('/export/attendance')
@login_required
def export_attendance_xlsx():
    month = request.args.get('month', date.today().month, type=int)
    year = request.args.get('year', date.today().year, type=int)
    summary = ReportGenerator.monthly_attendance_summary(month, year)
    data = excel_export.export_attendance(month, year, summary)
    return send_xlsx(data, f"تقرير_الحضور_{year}_{month:02d}.xlsx")


@app.route('/export/payroll/<int:period_id>')
@login_required
def export_payroll_xlsx(period_id):
    period = PayrollPeriod.query.get_or_404(period_id)
    records = PayrollRecord.query.filter_by(period_id=period_id).order_by(
        PayrollRecord.net_salary.desc()
    ).all()
    data = excel_export.export_payroll(period, records)
    return send_xlsx(data, f"كشف_رواتب_{period.name}.xlsx")


@app.route('/export/leaves')
@login_required
def export_leaves_xlsx():
    year = request.args.get('year', date.today().year, type=int)
    employees = Employee.query.filter_by(status='active').all()
    leave_types = LeaveType.query.all()
    balances_data = []
    for emp in employees:
        emp_balances = LeaveBalance.query.filter_by(employee_id=emp.id, year=year).all()
        balances_data.append({'employee': emp, 'balances': emp_balances})
    data = excel_export.export_leave_balances(year, balances_data, leave_types)
    return send_xlsx(data, f"أرصدة_الإجازات_{year}.xlsx")


@app.route('/export/loans')
@login_required
def export_loans_xlsx():
    loans = Loan.query.order_by(Loan.created_at.desc()).all()
    data = excel_export.export_loans(loans)
    return send_xlsx(data, f"السلف_والقروض_{date.today().strftime('%Y-%m-%d')}.xlsx")


@app.route('/export/payslip/<int:record_id>')
@login_required
def export_payslip_xlsx(record_id):
    record = PayrollRecord.query.get_or_404(record_id)
    data = excel_export.export_payslip(record)
    return send_xlsx(data, f"كشف_راتب_{record.employee.full_name.replace(' ', '_')}_{record.period.name}.xlsx")


# ==================== PDF Exports ====================

PDF_MIME = 'application/pdf'


def send_pdf(data, filename):
    return send_file(
        io.BytesIO(data),
        mimetype=PDF_MIME,
        as_attachment=True,
        download_name=filename
    )


@app.route('/export/pdf/payslip/<int:record_id>')
@login_required
def export_payslip_pdf(record_id):
    record = PayrollRecord.query.get_or_404(record_id)
    data = pdf_export.pdf_payslip(record)
    filename = f"كشف_راتب_{record.employee.full_name.replace(' ', '_')}_{record.period.name}.pdf"
    return send_pdf(data, filename)


@app.route('/export/pdf/payroll/<int:period_id>')
@login_required
def export_payroll_pdf(period_id):
    period = PayrollPeriod.query.get_or_404(period_id)
    records = PayrollRecord.query.filter_by(period_id=period_id).order_by(
        PayrollRecord.net_salary.desc()
    ).all()
    data = pdf_export.pdf_payroll(period, records)
    return send_pdf(data, f"كشف_رواتب_{period.name}.pdf")


@app.route('/export/pdf/attendance')
@login_required
def export_attendance_pdf():
    month = request.args.get('month', date.today().month, type=int)
    year = request.args.get('year', date.today().year, type=int)
    summary = ReportGenerator.monthly_attendance_summary(month, year)
    data = pdf_export.pdf_attendance(month, year, summary)
    return send_pdf(data, f"تقرير_الحضور_{year}_{month:02d}.pdf")


@app.route('/export/pdf/shifts-attendance')
@login_required
def export_shift_attendance_pdf():
    """تقرير الحضور الشهري مصنفاً حسب الورديات PDF"""
    month = request.args.get('month', date.today().month, type=int)
    year = request.args.get('year', date.today().year, type=int)
    if not (1 <= month <= 12):
        month = date.today().month
    data = pdf_export.pdf_shift_attendance(month, year)
    return send_pdf(data, f"تقرير_الورديات_{year}_{month:02d}.pdf")


@app.route('/export/pdf/shifts-schedule')
@login_required
def export_shift_schedule_pdf():
    """جدول توزيع الموظفين على الورديات PDF"""
    data = pdf_export.pdf_shift_schedule()
    return send_pdf(data, "جدول_الورديات.pdf")


@app.route('/export/pdf/monthly')
@login_required
def export_monthly_pdf():
    """التقرير الشهري الموحّد PDF (رواتب + حضور + إجازات + مكافآت + سلف)"""
    month = request.args.get('month', date.today().month, type=int)
    year = request.args.get('year', date.today().year, type=int)
    if not (1 <= month <= 12):
        month = date.today().month
    data = pdf_export.pdf_monthly_report(month, year)
    return send_pdf(data, f"التقرير_الشهري_{year}_{month:02d}.pdf")


@app.route('/export/pdf/insurance/<int:period_id>')
@login_required
def export_insurance_pdf(period_id):
    period = PayrollPeriod.query.get_or_404(period_id)
    records = PayrollRecord.query.filter_by(period_id=period_id).all()
    data = pdf_export.pdf_insurance_tax(period, records)
    return send_pdf(data, f"تأمينات_وضـرائب_{period.name}.pdf")


# ==================== Certificates (Print + PDF) ====================

@app.route('/certificates/leave/<int:req_id>')
@login_required
def certificate_leave(req_id):
    """شهادة إجازة رسمية - عرض للطباعة أو PDF"""
    req = LeaveRequest.query.get_or_404(req_id)

    def save_pdf():
        data = pdf_export.pdf_leave_certificate(req)
        return send_pdf(data, f"شهادة_إجازة_{req.employee.full_name.replace(' ', '_')}.pdf")

    if request.args.get('pdf'):
        return save_pdf()

    signed = request.args.get('signed')
    return render_template('certificates/leave_print.html', req=req, signed=signed)


@app.route('/certificates/experience/<int:emp_id>')
@login_required
def certificate_experience(emp_id):
    """شهادة خبرة رسمية - عرض للطباعة أو PDF"""
    emp = Employee.query.get_or_404(emp_id)

    def save_pdf():
        data = pdf_export.pdf_experience_certificate(emp)
        return send_pdf(data, f"شهادة_خبرة_{emp.full_name.replace(' ', '_')}.pdf")

    if request.args.get('pdf'):
        return save_pdf()

    signed = request.args.get('signed')
    return render_template('certificates/experience_print.html', emp=emp, signed=signed)


@app.route('/certificates/appreciation/issue/<int:emp_id>', methods=['GET', 'POST'])
@login_required
def appreciation_issue(emp_id):
    """صفحة إصدار شهادة تقدير"""
    emp = Employee.query.get_or_404(emp_id)
    if request.method == 'POST':
        reason = (request.form.get('reason') or '').strip()
        date_str = (request.form.get('issue_date') or '').strip()
        issued_on = None
        if date_str:
            try:
                issued_on = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                issued_on = None
        if request.form.get('direct_pdf'):
            data = pdf_export.pdf_appreciation_certificate(emp, reason, issued_on)
            return send_pdf(data, f"شهادة_تقدير_{emp.full_name.replace(' ', '_')}.pdf")
        args = {'emp_id': emp_id}
        if reason:
            args['reason'] = reason
        if date_str:
            args['date'] = date_str
        return redirect(url_for('certificate_appreciation', **args))
    return render_template('certificates/appreciation_issue.html', emp=emp)


@app.route('/certificates/appreciation/<int:emp_id>')
@login_required
def certificate_appreciation(emp_id):
    """شهادة تقدير رسمية - عرض للطباعة أو PDF"""
    emp = Employee.query.get_or_404(emp_id)
    reason = request.args.get('reason', '')
    date_str = request.args.get('date') or ''
    issued_on = None
    if date_str:
        try:
            issued_on = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            issued_on = None

    def save_pdf():
        data = pdf_export.pdf_appreciation_certificate(emp, reason, issued_on)
        return send_pdf(data, f"شهادة_تقدير_{emp.full_name.replace(' ', '_')}.pdf")

    if request.args.get('pdf'):
        return save_pdf()

    return render_template('certificates/appreciation_print.html', emp=emp,
                           reason=reason, issued_on=issued_on)


# ==================== Insurance & Tax Report ====================

@app.route('/reports/insurance')
@login_required
def insurance_report():
    today = date.today()
    period_id = request.args.get('period_id', type=int)
    periods = PayrollPeriod.query.order_by(PayrollPeriod.id.desc()).all()
    if not period_id and periods:
        period_id = periods[0].id
    period = PayrollPeriod.query.get(period_id) if period_id else None
    records = []
    totals = {}
    if period:
        records = PayrollRecord.query.filter_by(period_id=period.id).all()
        total_salary = sum(r.base_salary + r.housing_allowance + r.transport_allowance + r.food_allowance for r in records)
        total_insur = sum(r.social_insurance for r in records)
        total_tax = sum(r.tax_amount for r in records)
        totals = {
            'salary': total_salary,
            'insur': total_insur,
            'tax': total_tax,
        }
    return render_template(
        'reports/insurance.html',
        period=period, periods=periods, records=records, totals=totals,
    )


@app.route('/export/insurance')
@login_required
def export_insurance_xlsx():
    period_id = request.args.get('period_id', type=int)
    period = PayrollPeriod.query.get_or_404(period_id)
    records = PayrollRecord.query.filter_by(period_id=period.id).all()
    data = excel_export.export_insurance_tax(period, records)
    return send_xlsx(data, f"تأمينات_وضـرائب_{period.name}.xlsx")


# ==================== Auto-Absence ====================

@app.route('/attendance/mark-absent', methods=['POST'])
@login_required
def attendance_mark_absent():
    """تسجيل غياب تلقائي نهاية اليوم لكل نشط بدون حضور وبدون إجازة"""
    from modules.scheduler import run_absence_task
    run_absence_task()
    flash('تم حساب الغياب التلقائي لليوم الحالي', 'success')
    return redirect(request.form.get('next') or url_for('attendance_list'))


# ==================== Backup ====================

@app.route('/backup')
@admin_required
def backup_index():
    backups = backup_module.list_backups()
    last_backup = backups[0] if backups else None
    db_size = None
    db_path = Config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')
    if os.path.exists(db_path):
        db_size = os.path.getsize(db_path)
    return render_template('backup/index.html', backups=backups, last_backup=last_backup, db_size=db_size)


@app.route('/backup/create', methods=['POST'])
@admin_required
def backup_create():
    notes = request.form.get('notes', '').strip() or 'نسخة يدوية'
    dest, filename = backup_module.create_backup(notes=notes)
    log_action('نسخ احتياطي', f"إنشاء {filename}")
    flash(f"تم إنشاء النسخة الاحتياطية {filename}", 'success')
    return redirect(url_for('backup_index'))


@app.route('/backup/download/<filename>')
@admin_required
def backup_download(filename):
    import shutil
    from werkzeug.utils import secure_filename
    safe = os.path.basename(filename)
    path = os.path.join(backup_module.BACKUP_DIR, safe)
    if not os.path.exists(path):
        flash('الملف غير موجود', 'danger')
        return redirect(url_for('backup_index'))
    return send_file(path, as_attachment=True, download_name=safe)


@app.route('/backup/delete/<filename>', methods=['POST'])
@admin_required
def backup_delete(filename):
    safe = os.path.basename(filename)
    backup_module.delete_backup(safe)
    flash('تم حذف النسخة الاحتياطية', 'info')
    return redirect(url_for('backup_index'))


@app.route('/backup/restore/<filename>', methods=['POST'])
@admin_required
def backup_restore(filename):
    safe = os.path.basename(filename)
    try:
        backup_module.restore_backup(safe)
        log_action('استعادة نسخة', f"استعادة {safe}")
        flash('تمت استعادة قاعدة البيانات من النسخة الاحتياطية', 'success')
    except Exception as e:
        flash(f"تعذرت الاستعادة: {str(e)}", 'danger')
    return redirect(url_for('backup_index'))


# ==================== إعادة ضبط النظام (مسح كل البيانات) ====================

@app.route('/system/wipe', methods=['POST'])
@login_required
def system_wipe():
    """مسح جميع بيانات النظام والبدء من جديد (تصفير الداتا والتسجيل من جديد).
    متاح لأدمن النظام دائماً، ولحساب العرض التجريبي (demo) في وضع DEMO_MODE.
    يتطلب كتابة كلمة التأكيد «امسح» + كلمة المرور الحالية لمنع المسح بالخطأ."""
    if not (DEMO_MODE or (get_current_user() and get_current_user().role == 'admin')):
        flash('غير مصرح لك بتنفيذ هذا الإجراء', 'danger')
        return redirect(url_for('dashboard'))
    confirm_word = request.form.get('confirm_text', '').strip()
    password = request.form.get('password', '')
    user = get_current_user()
    if confirm_word != 'امسح' or not user or not user.check_password(password):
        flash('لم يتم تنفيذ المسح: تأكد من كلمة التأكيد «امسح» وكلمة المرور', 'danger')
        return redirect(url_for('dashboard'))
    from init_db import wipe_all_data
    ok = wipe_all_data()
    if ok:
        log_action('مسح البيانات', 'إعادة ضبط النظام: مسح جميع البيانات والبدء من جديد')
        flash('تم مسح جميع بيانات النظام وإعادة تهيئته من جديد — يمكنك البدء بالتسجيل', 'success')
    else:
        flash('حدث خطأ أثناء المسح، لم تُمسح البيانات', 'danger')
    return redirect(url_for('dashboard'))


# ==================== سجل النشاط (Audit Log) ====================

@app.route('/audit')
@login_required
def audit_log():
    action = request.args.get('action', '')
    keyword = request.args.get('q', '').strip()
    days = request.args.get('days', 30, type=int)
    query = AuditLog.query
    if action:
        query = query.filter(AuditLog.action == action)
    if keyword:
        query = query.filter(db.or_(
            AuditLog.details.contains(keyword),
            AuditLog.username.contains(keyword),
        ))
    since = datetime.now() - timedelta(days=max(1, min(365, days)))
    query = query.filter(AuditLog.created_at >= since).order_by(AuditLog.created_at.desc())
    logs = query.limit(500).all()
    actions = [r[0] for r in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]
    return render_template('audit.html', logs=logs, actions=actions,
                           action=action, keyword=keyword, days=days)


# ==================== Leaves ====================

@app.route('/leaves')
@login_required
def leaves_list():
    status = request.args.get('status', '')
    year = request.args.get('year', date.today().year, type=int)

    query = LeaveRequest.query
    if status:
        query = query.filter_by(status=status)
    query = query.filter(
        db.extract('year', LeaveRequest.created_at) == year
    )

    requests = query.order_by(LeaveRequest.created_at.desc()).all()
    return render_template('leaves/list.html', requests=requests, status=status, year=year)


@app.route('/leaves/request', methods=['GET', 'POST'])
@login_required
def leave_request():
    leave_types = LeaveType.query.all()
    employees = Employee.query.filter_by(status='active').all()
    
    if request.method == 'POST':
        emp_id = int(request.form.get('employee_id'))
        leave_type_id = int(request.form.get('leave_type_id'))
        start = parse_date(request.form.get('start_date'))
        end = parse_date(request.form.get('end_date'))
        reason = request.form.get('reason', '')
        hours_raw = request.form.get('hours', '').strip()
        hours = None
        if hours_raw:
            try:
                hours = float(hours_raw)
            except (TypeError, ValueError):
                hours = None

        # إجازة جزئية بساعات: اليوم الواحد = 8 ساعات قياسية
        if hours is not None:
            if hours <= 0 or hours > 16:
                hours = None
            else:
                end = start  # الإجازة الجزئية ليوم واحد فقط

        if not start or not end:
            flash('تاريخ البداية والنهاية مطلوب', 'danger')
        elif end < start:
            flash('تاريخ النهاية يجب أن يكون بعد تاريخ البداية', 'danger')
        else:
            # Check balance
            from calendar import monthrange
            if hours is not None:
                days = round(hours / 8.0, 2)
            else:
                days = (end - start).days + 1
            leave_type = LeaveType.query.get(leave_type_id)
            emp = Employee.query.get(emp_id)
            
            if leave_type.max_days_per_year and leave_type.max_days_per_year > 0:
                balance = LeaveBalance.query.filter_by(
                    employee_id=emp_id, leave_type_id=leave_type_id,
                    year=start.year
                ).first()
                if balance and days > balance.remaining_days:
                    flash(
                        f"الأرصدة غير كافية: المتبقي {balance.remaining_days} يوم، المطلوب {days} يوم",
                        'danger'
                    )
                    return render_template('leaves/request.html', leave_types=leave_types, employees=employees)

            req = LeaveRequest(
                employee_id=emp_id,
                leave_type_id=leave_type_id,
                start_date=start,
                end_date=end,
                hours=hours,
                reason=reason,
                status='pending'
            )
            db.session.add(req)
            db.session.commit()
            flash(f"تم تقديم طلب إجازة للموظف {emp.full_name}", 'success')
            return redirect(url_for('leaves_list'))
    
    return render_template('leaves/request.html', leave_types=leave_types, employees=employees)


@app.route('/leaves/<int:req_id>/action', methods=['POST'])
@login_required
def leave_action(req_id):
    req = LeaveRequest.query.get_or_404(req_id)
    action = request.form.get('action')  # approve, reject, cancel
    notes = request.form.get('notes', '')
    user = get_current_user()

    if action == 'approve':
        req.status = 'approved'
        req.reviewed_by = user.id
        req.reviewed_at = datetime.now()
        req.review_notes = notes
        # Deduct from balance
        balance = LeaveBalance.query.filter_by(
            employee_id=req.employee_id,
            leave_type_id=req.leave_type_id,
            year=req.start_date.year
        ).first()
        if balance:
            days = req.leave_days
            balance.used_days = min(balance.entitled_days, round(balance.used_days + days, 2))
            balance.remaining_days = max(0, round(balance.entitled_days - balance.used_days, 2))
        flash('تمت الموافقة على الإجازة', 'success')
    elif action == 'reject':
        req.status = 'rejected'
        req.reviewed_by = user.id
        req.reviewed_at = datetime.now()
        req.review_notes = notes
        flash('تم رفض الإجازة', 'warning')
    elif action == 'cancel':
        req.status = 'cancelled'
        flash('تم إلغاء الطلب', 'info')

    db.session.commit()
    log_action('إجازة: ' + req.status, f"موظف {req.employee.full_name} — {req.leave_type.name} ({req.days_count} يوم)" if req.employee else '')
    return redirect(url_for('leaves_list'))


@app.route('/leaves/balances')
@login_required
def leaves_balances():
    year = request.args.get('year', date.today().year, type=int)
    employees = Employee.query.filter_by(status='active').all()
    leave_types = LeaveType.query.all()
    
    balances_data = []
    for emp in employees:
        emp_balances = LeaveBalance.query.filter_by(employee_id=emp.id, year=year).all()
        balances_data.append({'employee': emp, 'balances': emp_balances})
    
    return render_template(
        'leaves/balances.html',
        balances_data=balances_data,
        leave_types=leave_types,
        year=year,
    )


# ==================== Payroll ====================

@app.route('/payroll')
@login_required
def payroll_index():
    today = date.today()
    periods = PayrollPeriod.query.order_by(PayrollPeriod.id.desc()).all()
    
    # Ensure current period exists
    period_name = f"{today.year}-{today.month:02d}"
    current_period = PayrollPeriod.query.filter_by(name=period_name).first()
    if not current_period:
        from calendar import monthrange
        current_period = PayrollPeriod(
            name=period_name,
            period_month=today.month,
            period_year=today.year,
            start_date=date(today.year, today.month, 1),
            end_date=date(today.year, today.month, monthrange(today.year, today.month)[1]),
            status='active'
        )
        db.session.add(current_period)
        db.session.commit()
        periods.insert(0, current_period)

    return render_template('payroll/index.html', periods=periods, current_period=current_period, today=today)


@app.route('/payroll/<int:period_id>')
@login_required
def payroll_details(period_id):
    period = PayrollPeriod.query.get_or_404(period_id)
    records = PayrollRecord.query.filter_by(period_id=period_id).order_by(PayrollRecord.net_salary.desc()).all()
    employees = Employee.query.filter_by(status='active').all()
    return render_template('payroll/details.html', period=period, records=records, employees=employees)


@app.route('/payroll/<int:period_id>/process', methods=['POST'])
@login_required
def payroll_process(period_id):
    period = PayrollPeriod.query.get_or_404(period_id)
    empl_ids = request.form.getlist('employee_ids') or [str(e.id) for e in Employee.query.filter_by(status='active').all()]
    
    records = []
    for eid in empl_ids:
        emp = Employee.query.get(int(eid))
        if emp:
            records.append(PayrollCalculator.process_employee(emp, period))
    
    period.status = 'processed'
    period.processed_at = datetime.now()
    db.session.commit()
    log_action('احتساب رواتب', f"فترة {period.name} — {len(records)} موظف")
    flash(f"تم احتساب رواتب {len(records)} موظفاً بنجاح", 'success')
    return redirect(url_for('payroll_details', period_id=period_id))


@app.route('/payroll/<int:period_id>/record/<int:record_id>', methods=['POST'])
@login_required
def payroll_record_update(period_id, record_id):
    record = PayrollRecord.query.get_or_404(record_id)
    record.other_deductions = parse_float(request.form.get('other_deductions', 0))
    record.notes = request.form.get('notes', '')
    # Recompute totals
    record.gross_salary = round(
        record.base_salary + record.housing_allowance + record.transport_allowance +
        record.food_allowance + record.phone_allowance + record.other_allowances +
        record.shift_allowance + record.overtime_amount + record.bonus_amount, 2
    )
    record.total_deductions = round(
        record.absent_deduction + record.late_deduction + record.social_insurance +
        record.tax_amount + record.loan_deduction + record.other_deductions +
        record.unpaid_leave_deduction, 2
    )
    record.net_salary = round(record.gross_salary - record.total_deductions, 2)
    db.session.commit()
    flash('تم تحديث الراتب', 'success')
    return redirect(url_for('payroll_details', period_id=period_id))


@app.route('/payroll/<int:period_id>/mark-paid', methods=['POST'])
@login_required
def payroll_mark_paid(period_id):
    record_ids = request.form.getlist('record_ids')
    if record_ids:
        records = PayrollRecord.query.filter(PayrollRecord.id.in_([int(i) for i in record_ids])).all()
        for r in records:
            r.status = 'paid'
            r.paid_date = date.today()
            # Record loan payments
            loan = Loan.query.filter_by(employee_id=r.employee_id, status='active').first()
            if loan and r.loan_deduction > 0:
                db.session.add(LoanPayment(
                    loan_id=loan.id,
                    amount=r.loan_deduction,
                    payment_date=date.today(),
                    period_id=period_id
                ))
                loan.remaining_amount = max(0, loan.remaining_amount - r.loan_deduction)
                if loan.remaining_amount == 0:
                    loan.status = 'paid'
        period = PayrollPeriod.query.get_or_404(period_id)
        period.status = 'closed'
        db.session.commit()
        flash(f"تم صرف رواتب {len(records)} موظف", 'success')
    return redirect(url_for('payroll_details', period_id=period_id))


@app.route('/payroll/payslip/<int:record_id>')
@login_required
def payslip_view(record_id):
    record = PayrollRecord.query.get_or_404(record_id)
    return render_template('payroll/payslip.html', record=record)


@app.route('/reports')
@login_required
def reports_index():
    today = date.today()
    # Department headcount report
    dept_report = ReportGenerator.department_headcount()
    # Leave usage
    leave_report = ReportGenerator.leave_usage_report()
    # Loans
    loans = ReportGenerator.loans_summary()
    # Payroll (latest processed)
    latest_period = PayrollPeriod.query.filter_by(status='processed').order_by(PayrollPeriod.id.desc()).first()
    payroll_report = ReportGenerator.payroll_report(latest_period) if latest_period else None
    
    return render_template(
        'reports/index.html',
        dept_report=dept_report,
        leave_report=leave_report,
        loans=loans,
        payroll_report=payroll_report,
        latest_period=latest_period,
    )


# ==================== Usage Guide ====================

@app.route('/guide')
def guide():
    """دليل الاستخدام الكامل للنظام (متاح للعموم في الديمو)"""
    return render_template('guide.html')


# ==================== Loans ====================

@app.route('/loans')
@login_required
def loans_list():
    loans = Loan.query.order_by(Loan.created_at.desc()).all()
    employees = Employee.query.filter_by(status='active').all()
    return render_template('loans/list.html', loans=loans, employees=employees)


@app.route('/loans/new', methods=['POST'])
@login_required
def loan_new():
    emp_id = int(request.form.get('employee_id'))
    amount = parse_float(request.form.get('amount'))
    installments = int(request.form.get('installment_count', 1))
    reason = request.form.get('reason', '')

    if not amount or amount <= 0:
        flash('المبلغ غير صحيح', 'danger')
        return redirect(url_for('loans_list'))

    installment_amount = round(amount / installments, 2) if installments > 0 else amount
    loan = Loan(
        employee_id=emp_id,
        amount=amount,
        installment_count=installments,
        installment_amount=installment_amount,
        remaining_amount=amount,
        reason=reason,
        status='active',
        approved_by=get_current_user().id
    )
    db.session.add(loan)
    db.session.commit()
    emp = Employee.query.get(emp_id)
    flash(f"تم تسجيل {loan.loan_type} للموظف {emp.full_name} بقيمة {amount:,.2f}", 'success')
    return redirect(url_for('loans_list'))


@app.route('/loans/<int:loan_id>/action', methods=['POST'])
@login_required
def loan_action(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    action = request.form.get('action')
    if action == 'cancel':
        loan.status = 'cancelled'
        flash('تم إلغاء السلفة/القرض', 'info')
    elif action == 'pay':
        amount = parse_float(request.form.get('amount', 0))
        if amount > 0 and amount <= loan.remaining_amount:
            db.session.add(LoanPayment(loan_id=loan.id, amount=amount, payment_date=date.today()))
            loan.remaining_amount = round(loan.remaining_amount - amount, 2)
            if loan.remaining_amount == 0:
                loan.status = 'paid'
            flash('تم تسجيل الدفعة', 'success')
        else:
            flash('المبلغ غير صحيح', 'danger')
    db.session.commit()
    log_action('سلفة/قرض: ' + action, f"موظف {loan.employee.full_name} — {loan.amount:,.2f}")
    return redirect(url_for('loans_list'))


# ==================== Bonuses ====================

@app.route('/bonuses')
@login_required
def bonuses_list():
    bonuses = Bonus.query.order_by(Bonus.date.desc()).all()
    bonus_types = BonusType.query.all()
    employees = Employee.query.filter_by(status='active').all()
    return render_template('bonuses/list.html', bonuses=bonuses, bonus_types=bonus_types, employees=employees)


@app.route('/bonuses/new', methods=['POST'])
@login_required
def bonus_new():
    emp_id = int(request.form.get('employee_id'))
    amount = parse_float(request.form.get('amount'))
    reason = request.form.get('reason', '')
    bonus_type_id = int(request.form.get('bonus_type_id')) if request.form.get('bonus_type_id') else None

    if not amount or amount <= 0:
        flash('المبلغ غير صحيح', 'danger')
        return redirect(url_for('bonuses_list'))

    bonus = Bonus(
        employee_id=emp_id,
        bonus_type_id=bonus_type_id,
        amount=amount,
        reason=reason,
        approved_by=get_current_user().id
    )
    db.session.add(bonus)
    db.session.commit()
    emp = Employee.query.get(emp_id)
    flash(f"تم تسجيل مكافأة للموظف {emp.full_name} بقيمة {amount:,.2f}", 'success')
    return redirect(url_for('bonuses_list'))


@app.route('/bonuses/<int:bonus_id>/delete', methods=['POST'])
@login_required
def bonus_delete(bonus_id):
    bonus = Bonus.query.get_or_404(bonus_id)
    db.session.delete(bonus)
    db.session.commit()
    flash('تم حذف المكافأة', 'info')
    return redirect(url_for('bonuses_list'))


# ==================== Departments & Positions ====================

@app.route('/departments')
@login_required
def departments_list():
    departments = Department.query.all()
    return render_template('departments/list.html', departments=departments)


@app.route('/departments/new', methods=['POST'])
@login_required
def department_new():
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '')
    if name:
        if Department.query.filter_by(name=name).first():
            flash('القسم موجود بالفعل', 'warning')
        else:
            db.session.add(Department(name=name, description=description))
            db.session.commit()
            flash('تم إضافة القسم', 'success')
    return redirect(url_for('departments_list'))


@app.route('/departments/<int:dept_id>/edit', methods=['POST'])
@login_required
def department_edit(dept_id):
    dept = Department.query.get_or_404(dept_id)
    dept.name = request.form.get('name', dept.name).strip()
    dept.description = request.form.get('description', '')
    if request.form.get('manager_id'):
        dept.manager_id = int(request.form.get('manager_id'))
    db.session.commit()
    flash('تم تحديث القسم', 'success')
    return redirect(url_for('departments_list'))


@app.route('/departments/<int:dept_id>/delete', methods=['POST'])
@login_required
def department_delete(dept_id):
    dept = Department.query.get_or_404(dept_id)
    if dept.employees.count() > 0:
        flash('لا يمكن حذف قسم به موظفين', 'danger')
    else:
        db.session.delete(dept)
        db.session.commit()
        flash('تم حذف القسم', 'info')
    return redirect(url_for('departments_list'))


@app.route('/positions')
@login_required
def positions_list():
    positions = Position.query.all()
    return render_template('positions/list.html', positions=positions)


@app.route('/positions/new', methods=['POST'])
@login_required
def position_new():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '')
    if title:
        if Position.query.filter_by(title=title).first():
            flash('الوظيفة موجودة بالفعل', 'warning')
        else:
            db.session.add(Position(title=title, description=description))
            db.session.commit()
            flash('تم إضافة الوظيفة', 'success')
    return redirect(url_for('positions_list'))


@app.route('/positions/<int:pos_id>/delete', methods=['POST'])
@login_required
def position_delete(pos_id):
    pos = Position.query.get_or_404(pos_id)
    if pos.employees.count() > 0:
        flash('لا يمكن حذف وظيفة لدها موظفين', 'danger')
    else:
        db.session.delete(pos)
        db.session.commit()
        flash('تم حذف الوظيفة', 'info')
    return redirect(url_for('positions_list'))


# ==================== Users ====================

@app.route('/users')
@admin_required
def users_list():
    users = User.query.all()
    return render_template('users/list.html', users=users)


@app.route('/users/new', methods=['POST'])
@admin_required
def user_new():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', 'viewer')
    if role not in VALID_ROLES:
        role = 'viewer'

    if not username or not password:
        flash('اسم المستخدم وكلمة المرور مطلوبان', 'danger')
    elif User.query.filter_by(username=username).first():
        flash('اسم المستخدم موجود بالفعل', 'danger')
    else:
        user = User(username=username, full_name=full_name, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        log_action('إضافة مستخدم', f"{username} — {VALID_ROLES.get(role, role)}")
        flash(f'تم إنشاء المستخدم {username}', 'success')
    return redirect(url_for('users_list'))


@app.route('/users/<int:user_id>/toggle', methods=['POST'])
@admin_required
def user_toggle(user_id):
    user = User.query.get_or_404(user_id)
    if user.id != get_current_user().id:
        user.is_active = not user.is_active
        db.session.commit()
        flash('تم تغيير حالة المستخدم', 'info')
    return redirect(url_for('users_list'))


@app.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def user_delete(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == get_current_user().id:
        flash('لا يمكن حذف نفسك', 'danger')
    else:
        db.session.delete(user)
        db.session.commit()
        flash('تم حذف المستخدم', 'info')
    return redirect(url_for('users_list'))


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = get_current_user()
    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        current = request.form.get('current_password', '')
        if user.check_password(current):
            if new_password == confirm and len(new_password) >= 4:
                user.set_password(new_password)
                db.session.commit()
                flash('تم تغيير كلمة المرور', 'success')
            else:
                flash('كلمتا المرور غير متطابقتين أو قصيرة جداً', 'danger')
        else:
            flash('كلمة المرور الحالية غير صحيحة', 'danger')
    return render_template('profile.html', user=user)


# ==================== Settings ====================

@app.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings_index():
    if request.method == 'POST':
        from init_db import mark_system_configured
        for key in request.form:
            Setting.set(key, request.form[key])
        # بمجرد حفظ الإعدادات يعتبر النظام مُعداً — توقف البذور التجريبية عن إعادة التعيين
        mark_system_configured()
        flash('تم حفظ الإعدادات بنجاح', 'success')
        return redirect(url_for('settings_index'))
    return render_template('settings/index.html')


@app.route('/settings/api-key/regenerate', methods=['POST'])
@admin_required
def settings_regenerate_api_key():
    """تجديد مفتاح API (يلغي المفتاح القديم فوراً)"""
    from secrets import token_hex
    Setting.set('api_key', 'HR-' + token_hex(12).upper())
    flash('تم تجديد مفتاح API بنجاح - المفتاح القديم لم يعد صالحاً', 'success')
    return redirect(url_for('settings_index'))


# ==================== Shifts (نظام الورديات) ====================

def _parse_shift_time(v, fallback='08:00'):
    try:
        return datetime.strptime(v, '%H:%M').time()
    except Exception:
        return datetime.strptime(fallback, '%H:%M').time()


@app.route('/shifts')
@login_required
def shifts_list():
    shifts = Shift.query.order_by(Shift.start_time).all()
    employees = Employee.query.filter_by(status='active').order_by(Employee.emp_id).all()
    return render_template('shifts/index.html', shifts=shifts, employees=employees, today=date.today())


@app.route('/shifts/new', methods=['GET', 'POST'])
@admin_required
def shift_new():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            if not name:
                flash('اسم الوردية مطلوب', 'danger')
                return redirect(url_for('shifts_list'))
            if Shift.query.filter_by(name=name).first():
                flash('يوجد وردية بهذا الاسم بالفعل', 'danger')
                return redirect(url_for('shifts_list'))
            shift = Shift(
                name=name,
                start_time=_parse_shift_time(request.form.get('start_time', '08:00')),
                end_time=_parse_shift_time(request.form.get('end_time', '17:00')),
                late_tolerance=int(request.form.get('late_tolerance', 15) or 15),
                grace_minutes_out=int(request.form.get('grace_minutes_out', 30) or 30),
                allowance_percent=float(request.form.get('allowance_percent', 0) or 0),
                description=request.form.get('description', '').strip(),
                is_active=True,
            )
            db.session.add(shift)
            db.session.commit()
            log_action('إضافة وردية', f"{name}")
            flash(f"تمت إضافة وردية «{name}» بنجاح", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"خطأ أثناء الحفظ: {str(e)}", 'danger')
        return redirect(url_for('shifts_list'))
    return render_template('shifts/form.html', shift=None, is_edit=False)


@app.route('/shifts/<int:shift_id>/edit', methods=['GET', 'POST'])
@admin_required
def shift_edit(shift_id):
    shift = Shift.query.get_or_404(shift_id)
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            if not name:
                flash('اسم الوردية مطلوب', 'danger')
                return redirect(url_for('shift_edit', shift_id=shift.id))
            dup = Shift.query.filter(Shift.name == name, Shift.id != shift.id).first()
            if dup:
                flash('يوجد وردية بهذا الاسم بالفعل', 'danger')
                return redirect(url_for('shift_edit', shift_id=shift.id))
            shift.name = name
            shift.start_time = _parse_shift_time(request.form.get('start_time', '08:00'))
            shift.end_time = _parse_shift_time(request.form.get('end_time', '17:00'))
            shift.late_tolerance = int(request.form.get('late_tolerance', 15) or 15)
            shift.grace_minutes_out = int(request.form.get('grace_minutes_out', 30) or 30)
            shift.allowance_percent = float(request.form.get('allowance_percent', 0) or 0)
            shift.description = request.form.get('description', '').strip()
            shift.is_active = request.form.get('is_active') == 'on'
            db.session.commit()
            log_action('تعديل وردية', f"{shift.name}")
            flash(f"تم تحديث وردية «{shift.name}» بنجاح", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"خطأ أثناء الحفظ: {str(e)}", 'danger')
        return redirect(url_for('shifts_list'))
    return render_template('shifts/form.html', shift=shift, is_edit=True)


@app.route('/shifts/<int:shift_id>/assign', methods=['POST'])
@admin_required
def shift_bulk_assign(shift_id):
    """تعيين وردية لعدد كبير من الموظفين دفعة واحدة"""
    shift = Shift.query.get_or_404(shift_id)
    emp_ids = []
    for v in request.form.getlist('employee_ids'):
        try:
            emp_ids.append(int(v))
        except (TypeError, ValueError):
            continue
    cleared_any = request.form.get('clear_checked') == 'on'
    updated = 0
    try:
        if cleared_any:
            # إزالة الوردية من المحددين (يعودون للنظام الموحد)
            db.session.query(Employee).filter(
                Employee.id.in_(emp_ids), Employee.shift_id == shift.id
            ).update({'shift_id': None}, synchronize_session=False)
            updated += len(emp_ids)
            log_action('إلغاء تعيين وردية جماعي', f"{shift.name} — {len(emp_ids)} موظف")
            flash(f"تم عودة {len(emp_ids)} موظف إلى النظام الموحد وإلغاء وردية «{shift.name}»", 'info')
        else:
            db.session.query(Employee).filter(Employee.id.in_(emp_ids)).update(
                {'shift_id': shift.id}, synchronize_session=False)
            updated += len(emp_ids)
            log_action('تعيين وردية جماعي', f"{shift.name} — {len(emp_ids)} موظف")
            flash(f"تم تعيين وردية «{shift.name}» لـ {len(emp_ids)} موظف", 'success')
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f"خطأ أثناء التعيين: {str(e)}", 'danger')
    return redirect(url_for('shifts_list'))


@app.route('/shifts/<int:shift_id>/delete', methods=['POST'])
@admin_required
def shift_delete(shift_id):
    shift = Shift.query.get_or_404(shift_id)
    name = shift.name
    count = Employee.query.filter_by(shift_id=shift.id).count()
    try:
        # إلغاء تعيين الوردية من الموظفين والسجلات المرتبطة بها (يعودون للنظام الموحد)
        Employee.query.filter_by(shift_id=shift.id).update({'shift_id': None})
        Attendance.query.filter_by(shift_id=shift.id).update({'shift_id': None})
        db.session.delete(shift)
        db.session.commit()
        log_action('حذف وردية', f"{name}")
        flash(f"تم حذف وردية «{name}» — عاد الموظفون المرتبطون بها للنظام الموحد ({count})", 'info')
    except Exception as e:
        db.session.rollback()
        flash(f"تعذر الحذف (وردة مرتبطة بموظفين): {str(e)}", 'danger')
    return redirect(url_for('shifts_list'))


# ==================== API ====================

@app.route('/api/attendance/today')
@login_required
def api_attendance_today():
    today = date.today()
    records = Attendance.query.filter_by(date=today).all()
    return jsonify([
        {
            'id': r.id,
            'employee': r.employee.full_name,
            'emp_id': r.employee.emp_id,
            'check_in': r.check_in_time.strftime('%H:%M') if r.check_in_time else None,
            'check_out': r.check_out_time.strftime('%H:%M') if r.check_out_time else None,
            'status': r.status,
            'overtime': r.overtime_hours,
        } for r in records
    ])


@app.route('/api/fingerprint/punch', methods=['POST'])
def api_fingerprint_punch():
    """Webhook endpoint - يمكن لأجهزة البصمة الداعمة لها أن ترسل النقرة هنا
    يتطلب مفتاح API في الهيدر X-API-Key (يوجد في صفحة الإعدادات).

    Body: {"fingerprint_id": "1001", "timestamp": "2024-01-15 18:30:00"}
    Headers: X-API-Key: HR-XXXX...
    """
    data = request.get_json(silent=True) or {}

    # ===== حماية من إغراق الواجهة (حد أقصى للطلبات لكل جهاز) =====
    api_ip = request.remote_addr or '0.0.0.0'
    if rate_limited(_api_attempts, api_ip, 30, 60):
        return jsonify({'error': 'محاولات كثيرة، حاول لاحقاً'}), 429

    # ===== التحقق من مفتاح API (أمان ضد أي جهاز غير مصرح) =====
    sent_key = request.headers.get('X-API-Key') or data.get('api_key', '')
    if not sent_key or not hmac.compare_digest(str(sent_key), str(get_api_key())):
        return jsonify({'error': 'مفتاح API غير صالح'}), 401

    fp_id = str(data.get('fingerprint_id', '')).strip()
    ts = data.get('timestamp')

    if not fp_id:
        return jsonify({'error': 'fingerprint_id مطلوب'}), 400

    emp = Employee.query.filter_by(fingerprint_id=fp_id).first()
    if not emp:
        return jsonify({'error': 'لا يوجد موظف بهذا الرقم'}), 404

    device = FingerprintDevice.query.filter_by(status='active').first()
    device_id = device.id if device else None

    if ts:
        try:
            dt = datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
        except:
            try:
                dt = datetime.strptime(ts[:19], '%Y-%m-%dT%H:%M:%S')
            except:
                return jsonify({'error': 'تنسيق الوقت غير صحيح'}), 400
    else:
        dt = datetime.now()

    punch_type = FingerprintManager._determine_punch_type(emp, dt)
    result = FingerprintManager._record_punch(emp, dt, device_id, punch_type)

    return jsonify({
        'success': True,
        'employee': emp.full_name,
        'punch': punch_type,
        'timestamp': dt.strftime('%Y-%m-%d %H:%M:%S'),
        'result': result
    })


# ==================== Helpers ====================

def parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except:
        return None


def parse_float(s):
    if not s:
        return 0.0
    try:
        return float(str(s).replace(',', ''))
    except:
        return 0.0


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        from init_db import seed_default_data, add_sample_employee
        seed_default_data()
        add_sample_employee()
    scheduler.start_scheduler()
    app.run(debug=True, host='0.0.0.0', port=8080, use_reloader=False)
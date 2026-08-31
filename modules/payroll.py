from datetime import date, datetime, timedelta
from calendar import monthrange
from models import (
    db, Employee, Attendance, PayrollPeriod, PayrollRecord,
    Loan, LoanPayment, Bonus, LeaveRequest, LeaveBalance,
    LeaveType, Setting, OvertimeRequest
)


class PayrollCalculator:
    """حساب الرواتب والأجور"""

    @staticmethod
    def get_working_days(month, year):
        """Calculate working days in a month"""
        days_in_month = monthrange(year, month)[1]
        working_days = 0
        for day in range(1, days_in_month + 1):
            d = date(year, month, day)
            if d.weekday() < 5:  # Mon-Fri
                working_days += 1
        return working_days

    @staticmethod
    def calc_absences(employee_id, period):
        """Calculate absence days and late minutes for a period"""
        start = max(period.start_date, date(period.period_year, period.period_month, 1))
        end = min(period.end_date or date.today(), date(period.period_year, period.period_month, 28))
        
        absent_days = 0
        late_minutes = 0
        late_days = 0
        # official_holidays = 0

        # Get all attendance records in period
        records = Attendance.query.filter(
            Attendance.employee_id == employee_id,
            Attendance.date >= start,
            Attendance.date <= end
        ).all()

        attendance_dates = {r.date for r in records}

        # Check each working day
        day = start
        while day <= end:
            is_weekend = day.weekday() >= 5
            is_holiday = is_weekend  # Friday/Saturday
            
            if day in attendance_dates:
                rec = next(r for r in records if r.date == day)
                if rec.status == 'late':
                    late_minutes += rec.late_minutes or 0
                    late_days += 1
                # Skip if on approved paid leave handled elsewhere
            elif not is_holiday and not PayrollCalculator._is_on_approved_leave(employee_id, day, period):
                absent_days += 1
            day += timedelta(days=1)

        # Subtract days on approved paid leave from absences
        approved_leaves = LeaveRequest.query.filter(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= end,
            LeaveRequest.end_date >= start
        ).all()

        from models import LeaveType
        for lv in approved_leaves:
            ltype = LeaveType.query.get(lv.leave_type_id)
            if ltype and ltype.paid:
                # Count overlap working days
                overlap_start = max(start, lv.start_date)
                overlap_end = min(end, lv.end_date)
                d = overlap_start
                while d <= overlap_end:
                    if d.weekday() < 5 and d in [x for x in range_dates(overlap_start, overlap_end)]:
                        pass
                    d += timedelta(days=1)
                # Simpler: reduce absent days by working days in overlap
                leave_working_days = sum(1 for i in range((overlap_end - overlap_start).days + 1)
                                          if (overlap_start + timedelta(days=i)).weekday() < 5)
                absent_days = max(0, absent_days - leave_working_days)

        # unpaid leave
        unpaid_leave_days = 0
        for lv in approved_leaves:
            ltype = LeaveType.query.get(lv.leave_type_id)
            if ltype and not ltype.paid:
                overlap_start = max(start, lv.start_date)
                overlap_end = min(end, lv.end_date)
                unpaid_leave_days += sum(1 for i in range((overlap_end - overlap_start).days + 1)
                                          if (overlap_start + timedelta(days=i)).weekday() < 5)

        # Overtime hours
        ot_hours = 0
        for r in records:
            ot_hours += r.overtime_hours or 0

        return {
            'absent_days': absent_days,
            'late_minutes': late_minutes,
            'late_days': late_days,
            'unpaid_leave_days': unpaid_leave_days,
            'overtime_hours': ot_hours,
            'attendance_days': len(attendance_dates),
        }

    @staticmethod
    def _is_on_approved_leave(emp_id, day, period):
        return LeaveRequest.query.filter(
            LeaveRequest.employee_id == emp_id,
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= day,
            LeaveRequest.end_date >= day
        ).first() is not None

    @staticmethod
    def calc_loan_deduction(employee_id, period):
        """Get loan installment for this period"""
        active_loans = Loan.query.filter_by(
            employee_id=employee_id, status='active'
        ).all()
        total = 0
        for loan in active_loans:
            # Check if payment already made this period
            already_paid = LoanPayment.query.filter_by(
                loan_id=loan.id, period_id=period.id
            ).first()
            if not already_paid and loan.remaining_amount > 0:
                installment = min(loan.installment_amount or 0, loan.remaining_amount)
                total += installment
        return total

    @staticmethod
    def process_employee(employee, period, save=True):
        """Process payroll for a single employee"""
        
        # Absence/late calculations
        attendance = PayrollCalculator.calc_absences(employee.id, period)
        
        daily_rate = employee.daily_rate
        hourly_rate = employee.hourly_rate

        absent_deduction = round(attendance['absent_days'] * daily_rate, 2)
        late_deduction = round(attendance['late_minutes'] / 60 * hourly_rate, 2) if attendance['late_minutes'] > 15 else 0
        unpaid_leave_deduction = round(attendance['unpaid_leave_days'] * daily_rate, 2)
        overtime_amount = round(attendance['overtime_hours'] * hourly_rate * 1.5, 2)

        # العقوبة/المكافأة التلقائية بناءً على سجل الحضور
        # (تُحسب قبل استخدام auto_bonus في bonus_amount و auto_penalty في الخصومات)
        auto_penalty = 0.0
        auto_bonus = 0.0
        if str(Setting.get('auto_penalty_enabled', '')).strip() == 'on':
            try:
                threshold = int(Setting.get('auto_penalty_late_days', 3) or 3)
                per_penalty = float(Setting.get('auto_penalty_amount', 0) or 0)
                if threshold > 0 and per_penalty > 0 and attendance['late_days'] >= threshold:
                    auto_penalty = round(per_penalty, 2)
            except (ValueError, TypeError):
                pass
        if str(Setting.get('auto_bonus_enabled', '')).strip() == 'on':
            try:
                per_bonus = float(Setting.get('auto_bonus_amount', 0) or 0)
                if per_bonus > 0 and attendance['absent_days'] == 0 and attendance['late_days'] == 0 and attendance['attendance_days'] > 0:
                    auto_bonus = round(per_bonus, 2)
            except (ValueError, TypeError):
                pass

        # Bonuses
        bonuses = Bonus.query.filter(
            Bonus.employee_id == employee.id,
            Bonus.date >= period.start_date,
            Bonus.date <= (period.end_date or date.today())
        ).all()
        bonus_amount = round(sum(float(b.amount) for b in bonuses) + auto_bonus, 2)

        # Shift allowance (نسبة بدل الوردية الليلية/المميزة من إجمالي الراتب)
        shift_allowance = 0.0
        shift_name = None
        if employee.shift_id:
            from models import Shift as _Shift
            _s = _Shift.query.get(employee.shift_id)
            if _s and _s.allowance_percent:
                shift_allowance = round(employee.total_salary * float(_s.allowance_percent) / 100.0, 2)
                shift_name = _s.name
        if not shift_allowance:
            shift_allowance = round(float(Setting.get('night_shift_allowance_pct', 0) or 0) * employee.total_salary / 100.0, 2)

        # Loans
        loan_deduction = round(PayrollCalculator.calc_loan_deduction(employee.id, period), 2)

        # Social insurance (11% on total salary)
        social_insurance = round(employee.total_salary * 0.11, 2)

        # Tax (simple flat calculation - can be customized)
        tax_amount = 0

        # Gross salary (يشمل بدل الوردية الليلية)
        gross = round(employee.total_salary + shift_allowance + bonus_amount, 2)

        # Total deductions
        total_deductions = round(
            absent_deduction + late_deduction + unpaid_leave_deduction +
            social_insurance + tax_amount + loan_deduction + auto_penalty, 2
        )

        # Net
        net_salary = round(gross - total_deductions, 2)

        record = PayrollRecord.query.filter_by(
            employee_id=employee.id, period_id=period.id
        ).first()

        if not record:
            record = PayrollRecord(employee_id=employee.id, period_id=period.id)
            db.session.add(record)

        record.base_salary = float(employee.base_salary)
        record.housing_allowance = float(employee.housing_allowance)
        record.transport_allowance = float(employee.transport_allowance)
        record.food_allowance = float(employee.food_allowance)
        record.phone_allowance = float(employee.phone_allowance)
        record.other_allowances = float(employee.other_allowances)
        record.shift_allowance = shift_allowance
        record.overtime_amount = overtime_amount
        record.bonus_amount = bonus_amount
        record.absent_days = attendance['absent_days']
        record.late_minutes_total = attendance['late_minutes']
        record.absent_deduction = absent_deduction
        record.late_deduction = late_deduction
        record.social_insurance = social_insurance
        record.tax_amount = tax_amount
        record.loan_deduction = loan_deduction
        record.unpaid_leave_days = attendance['unpaid_leave_days']
        record.unpaid_leave_deduction = unpaid_leave_deduction
        # العقوبة التلقائية تُضاف لخصومات أخرى (تُعاد حسابها تلقائياً عند كل احتساب)
        if auto_penalty > 0:
            record.other_deductions = round(auto_penalty, 2)
        record.gross_salary = gross
        record.total_deductions = total_deductions
        record.net_salary = net_salary

        if save:
            db.session.commit()
        return record

    @staticmethod
    def process_period(period):
        """Process payroll for all active employees in period"""
        employees = Employee.query.filter_by(status='active').all()
        records = []
        for emp in employees:
            record = PayrollCalculator.process_employee(emp, period, save=False)
            records.append(record)
        db.session.commit()
        return records

    @staticmethod
    def generate_payslip(employee, period):
        """Generate textual payslip for employee"""
        record = PayrollRecord.query.filter_by(
            employee_id=employee.id, period_id=period.id
        ).first()
        return record


# Helper
def range_dates(start, end):
    """Generator for dates between start and end inclusive"""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
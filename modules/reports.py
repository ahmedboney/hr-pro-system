from datetime import date, datetime, timedelta
from models import (
    db, Employee, Department, Attendance, PayrollRecord, PayrollPeriod,
    LeaveRequest, Loan, Bonus, Setting, LeaveBalance
)


class ReportGenerator:
    """توليد التقارير المختلفة"""

    @staticmethod
    def monthly_attendance_summary(month=None, year=None):
        """تقرير حضور شهري لجميع الموظفين"""
        today = date.today()
        month = month or today.month
        year = year or today.year
        
        period_start = date(year, month, 1)
        period_end = date(year, month, monthrange_days(year, month))
        
        employees = Employee.query.filter_by(status='active').all()
        summary = []
        
        for emp in employees:
            records = Attendance.query.filter(
                Attendance.employee_id == emp.id,
                Attendance.date >= period_start,
                Attendance.date <= period_end
            ).all()
            
            present = 0
            late = 0
            absent_estimated = 0
            total_ot = 0.0
            
            for r in records:
                if r.status == 'late':
                    late += 1
                    present += 1
                elif r.status == 'present':
                    present += 1
                total_ot += r.overtime_hours or 0
            
            # Estimate working days
            working_days = 0
            for d in range(1, period_end.day + 1):
                dt = date(year, month, d)
                if dt.weekday() < 5:
                    working_days += 1
            
            summary.append({
                'employee': emp,
                'present_days': present,
                'late_days': late,
                'absent_days': max(0, working_days - present),
                'overtime_hours': round(total_ot, 2),
                'attendance_rate': round(present / working_days * 100, 1) if working_days else 0,
            })
        
        return summary

    @staticmethod
    def department_headcount():
        """تقرير عدد الموظفين حسب الأقسام"""
        departments = Department.query.all()
        result = []
        for dept in departments:
            total = dept.employees.filter_by(status='active').count()
            salary_total = sum(
                emp.total_salary for emp in dept.employees.filter_by(status='active').all()
            )
            result.append({
                'department': dept,
                'count': total,
                'salary_total': round(salary_total, 2),
                'avg_salary': round(salary_total / total, 2) if total else 0,
            })
        return result

    @staticmethod
    def leave_usage_report(year=None):
        """تقرير استهلاك الإجازات"""
        year = year or date.today().year
        employees = Employee.query.filter_by(status='active').all()
        result = []
        for emp in employees:
            balances = LeaveBalance.query.filter_by(
                employee_id=emp.id, year=year
            ).all()
            total_entitled = sum(b.entitled_days for b in balances)
            total_used = sum(b.used_days for b in balances)
            result.append({
                'employee': emp,
                'total_entitled': total_entitled,
                'total_used': total_used,
                'total_remaining': total_entitled - total_used,
                'balances': balances,
            })
        return result

    @staticmethod
    def payroll_report(period):
        """تقرير الرواتب لفترة محسوبة"""
        records = PayrollRecord.query.filter_by(period_id=period.id).all()
        total_gross = sum(r.gross_salary for r in records)
        total_deductions = sum(r.total_deductions for r in records)
        total_net = sum(r.net_salary for r in records)
        return {
            'records': records,
            'employee_count': len(records),
            'total_gross': round(total_gross, 2),
            'total_deductions': round(total_deductions, 2),
            'total_net': round(total_net, 2),
        }

    @staticmethod
    def loans_summary():
        """تقرير السلف والقروض"""
        active_loans = Loan.query.filter_by(status='active').all()
        total_outstanding = sum(loan.remaining_amount for loan in active_loans)
        return {
            'loans': active_loans,
            'count': len(active_loans),
            'total_outstanding': round(total_outstanding, 2),
        }


def monthrange_days(year, month):
    """Return last day of month"""
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day
"""تصدير تقارير PDF عربية احترافية (reportlab + عربيز)
يعتمد على arabic_reshaper و python-bidi لتشكيل النص العربي بشكل صحيح.
"""
import os
from datetime import date, datetime
from io import BytesIO
from config import BASE_DIR

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable
)

import arabic_reshaper
from bidi.algorithm import get_display

# ---------- خطوط تدعم العربية (بحث: الخط المرفق → ويندوز → لينكس/Noto) ----------
FONT_NAME = 'Arial'  # Arial يدعم الحروف العربية
_FONT_CANDIDATES = (
    os.path.join(BASE_DIR, 'fonts', 'arial.ttf'),
    r"C:\Windows\Fonts\arial.ttf",
    '/usr/share/fonts/truetype/msttcorefonts/Arial.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
)
_FONT_BOLD_CANDIDATES = (
    os.path.join(BASE_DIR, 'fonts', 'arialbd.ttf'),
    r"C:\Windows\Fonts\arialbd.ttf",
    '/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
)
FONT_PATH = next((p for p in _FONT_CANDIDATES if os.path.exists(p)), None)
FONT_BOLD_PATH = next((p for p in _FONT_BOLD_CANDIDATES if os.path.exists(p)), None)
FONT_PATH = FONT_PATH or FONT_BOLD_PATH
FONT_BOLD_PATH = FONT_BOLD_PATH or FONT_PATH
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

if FONT_PATH:
    pdfmetrics.registerFont(TTFont('Ar', FONT_PATH))
    pdfmetrics.registerFont(TTFont('ArBd', FONT_BOLD_PATH or FONT_PATH))
    pdfmetrics.registerFontFamily('Ar', normal='Ar', bold='ArBd')


COLOR_HEADER = colors.HexColor('#1E3A8A')
COLOR_STRIPE = colors.HexColor('#EFF6FF')
COLOR_TOTAL = colors.HexColor('#DBEAFE')
COLOR_GOLD = colors.HexColor('#FEF9C3')
COLOR_LINE = colors.HexColor('#94A3B8')


def ar(text):
    """تشكيل النص العربي للعرض الصحيح في PDF"""
    if text is None:
        text = ''
    text = str(text)
    # بدائل الطباعة في ويندوز العربية
    return get_display(arabic_reshaper.reshape(text))


def _tc(v):
    """نص جدول: أي قيمة → نص عربي منضبط (للأسماء/الأقسام/الوظائف في الصفوف)"""
    if v is None or str(v).strip() == '':
        v = '—'
    return ar(v)


MONTHS_AR = [
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
]


def _style(name, size=10, bold=False, color=colors.black, align=2, leading=None):
    kwargs = {
        'name': name,
        'fontName': 'ArBd' if bold else 'Ar',
        'fontSize': size,
        'textColor': color,
        'alignment': align,
        'spaceAfter': 2,
    }
    if leading:
        kwargs['leading'] = leading
    return ParagraphStyle(**kwargs)


_ALIGN_MAP = {0: 'LEFT', 1: 'CENTER', 2: 'RIGHT', 4: 'JUSTIFY'}


def _table(data, col_widths=None, aligns=None, header_bold=True, split_by_row=False):
    """جدول منسق بخلفية رأس كحلية وصفوف مخططة"""
    t = Table(data, colWidths=col_widths, repeatRows=1, splitByRow=split_by_row)
    style = [
        # أهم إصلاح: كل خلايا الجدول بخط Arial العربي افتراضياً
        # (فبدون ذلك تُطبع الخلايا بخط Helvetica الافتراضي ولا تظهر العربية)
        ('FONTNAME', (0, 0), (-1, -1), 'Ar'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.4, COLOR_LINE),
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'ArBd'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(('BACKGROUND', (0, i), (-1, i), COLOR_STRIPE))
    if aligns:
        for col, align in enumerate(aligns):
            style.append(('ALIGN', (col, 0), (col, -1), _ALIGN_MAP.get(align, 'CENTER')))
    t.setStyle(TableStyle(style))
    return t


def _signers():
    """التوقيعات المسجلة في الإعدادات (قابلة للتعديل من صفحة الإعدادات)"""
    from models import Setting
    fin_role = Setting.get('sign_fin_role', 'محاسب')
    fin_name = Setting.get('sign_fin_name', 'أحمد عبدالله')
    hr_role = Setting.get('sign_hr_role', 'مدير الموارد البشرية')
    hr_name = Setting.get('sign_hr_name', '')
    fin_full = f"{fin_role} / {fin_name}" if fin_name else fin_role
    hr_full = f"{hr_role} / {hr_name}" if hr_name else hr_role
    return fin_full, hr_full


def _footer(canvas, doc, company="", by_line=None):
    """ترويسة/تذييل + إطار فخم موحد (مطابق لتصميم الشهادات) لكل صفحات PDF"""
    if by_line is None:
        by_line = _signers()[0]
    canvas.saveState()
    w, h = A4
    gold = colors.HexColor('#C9A227')

    # علامة مائية (خلفية)
    canvas.setFont('ArBd', 56)
    canvas.setFillColor(colors.HexColor('#EFF2F9'))
    canvas.saveState()
    canvas.translate(w / 2, h / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, ar("نظام الموارد البشرية المتكامل"))
    canvas.restoreState()

    # إطار خارجي كحلي سميك
    canvas.setStrokeColor(COLOR_HEADER)
    canvas.setLineWidth(2.0)
    canvas.rect(9 * mm, 9 * mm, w - 18 * mm, h - 18 * mm)
    # إطار داخلي ذهبي رفيع
    canvas.setStrokeColor(gold)
    canvas.setLineWidth(0.9)
    canvas.rect(12 * mm, 12 * mm, w - 24 * mm, h - 24 * mm)
    # زوايا ذهبية
    canvas.setFillColor(gold)
    d = 2.0 * mm
    for cx, cy in ((12 * mm, 12 * mm), (w - 12 * mm, 12 * mm),
                   (12 * mm, h - 12 * mm), (w - 12 * mm, h - 12 * mm)):
        canvas.circle(cx, cy, d, stroke=0, fill=1)

    # ترويسة علوية
    canvas.setFont('ArBd', 12)
    canvas.setFillColor(COLOR_HEADER)
    canvas.drawCentredString(w / 2, h - 15 * mm, ar(company or "نظام الموارد البشرية المتكامل"))
    canvas.setStrokeColor(gold)
    canvas.setLineWidth(0.7)
    canvas.line(12 * mm, h - 17.5 * mm, w - 12 * mm, h - 17.5 * mm)

    # تذييل
    canvas.setStrokeColor(colors.HexColor('#CBD5E1'))
    canvas.setLineWidth(0.6)
    canvas.line(12 * mm, 17 * mm, w - 12 * mm, 17 * mm)
    canvas.setFont('Ar', 8)
    canvas.setFillColor(colors.HexColor('#475569'))
    canvas.drawCentredString(
        w / 2, 13.5 * mm,
        ar(f"إعداد البرنامج: نظام الموارد البشرية المتكامل - حقوق الملكية محفوظة © {date.today().year} - {by_line}")
    )
    canvas.setFont('Ar', 7)
    canvas.drawCentredString(w / 2, 10.5 * mm, ar("مستند آلي صادر من النظام - لا يحتاج لتوقيع بريدي"))
    canvas.restoreState()


def _base_doc(buf):
    return SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=22 * mm, bottomMargin=18 * mm,
        title="نظام الموارد البشرية المتكامل",
        author=_signers()[0],
    )


def _init_common(company, subtitle):
    from models import Setting
    company = Setting.get('company_name', company)
    currency = Setting.get('currency', 'ج.م')
    return company, currency


# ==================== كشف راتب فردي PDF ====================

def pdf_payslip(record):
    from models import Setting
    buf = BytesIO()
    company, currency = _init_common("شركتي", "كشف راتب")

    elements = []
    emp = record.employee

    # العنوان
    elements.append(Paragraph(ar(company), _style('t1', 18, True, COLOR_HEADER, 1)))
    elements.extend(_ornament_block(_GOLD))
    elements.append(Paragraph(ar("مفردات المرتب - كشف راتب شهري"), _style('t2', 14, True, colors.HexColor('#1E40AF'), 1)))
    elements.extend(_ornament_block(COLOR_HEADER))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        ar(f"فترة: {record.period.name}    |    تاريخ الإصدار: {ar_date(date.today())}"),
        _style('t3', 10, color=colors.HexColor('#475569'), align=1)
    ))
    elements.append(Spacer(1, 10))

    # بيانات الموظف
    emp_rows = [
        [ar("الموظف"), ar(emp.full_name), ar("الرقم الوظيفي"), ar(emp.emp_id)],
        [ar("القسم"), ar(emp.department.name if emp.department else "—"),
         ar("الوظيفة"), ar(emp.position.title if emp.position else "—")],
        [ar("الحالة"), ar("مدفوع" if record.status in ('paid', 'closed') else "غير مدفوع"),
         ar("الحساب البنكي"), ar(emp.bank_account or "—")],
    ]
    t = _table(emp_rows, col_widths=[30 * mm, 62 * mm, 30 * mm, 58 * mm],
               aligns=[1, 1, 1, 1])
    elements.append(t)
    elements.append(Spacer(1, 8))

    # الإضافات
    elements.append(Paragraph(ar("أولاً: بنود الاستحقاق"), _style('h1', 11, True, COLOR_HEADER)))
    earn = [
        [ar("البيان"), ar("المبلغ"), ar("البيان"), ar("المبلغ")],
        [ar("الراتب الأساسي"), f"{record.base_salary:,.2f}",
         ar("بدل سكن"), f"{record.housing_allowance:,.2f}"],
        [ar("بدل انتقال"), f"{record.transport_allowance:,.2f}",
         ar("بدل وجبات"), f"{record.food_allowance:,.2f}"],
        [ar("بدل هاتف"), f"{record.phone_allowance:,.2f}",
         ar("بدلات أخرى"), f"{record.other_allowances:,.2f}"],
        [ar("ساعات إضافية"), f"{record.overtime_amount:,.2f}",
         ar("مكافآت"), f"{record.bonus_amount:,.2f}"],
        [ar("إجمالي الاستحقاقات"), f"{record.gross_salary:,.2f}",
         ar("العملة"), ar(currency)],
    ]
    t = _table(earn, col_widths=[45 * mm, 36 * mm, 45 * mm, 36 * mm], aligns=[1, 2, 1, 2])
    t.setStyle(TableStyle([('BACKGROUND', (0, -1), (1, -1), COLOR_TOTAL),
                           ('FONTNAME', (0, -1), (1, -1), 'ArBd')]))
    elements.append(t)
    elements.append(Spacer(1, 10))

    # الخصومات
    elements.append(Paragraph(ar("ثانياً: الخصومات"), _style('h1', 11, True, COLOR_HEADER)))
    ded = [
        [ar("البيان"), ar("المبلغ"), ar("البيان"), ar("المبلغ")],
        [ar("خصم غياب"), f"{record.absent_deduction:,.2f}",
         ar("خصم تأخير"), f"{record.late_deduction:,.2f}"],
        [ar("إجازة بدون أجر"), f"{record.unpaid_leave_deduction:,.2f}",
         ar("تأمينات اجتماعية"), f"{record.social_insurance:,.2f}"],
        [ar("ضريبة كسب العمل"), f"{record.tax_amount:,.2f}",
         ar("أقساط السلف"), f"{record.loan_deduction:,.2f}"],
        [ar("خصومات أخرى"), f"{record.other_deductions:,.2f}",
         ar("إجمالي الخصومات"), f"{record.total_deductions:,.2f}"],
    ]
    t = _table(ded, col_widths=[45 * mm, 36 * mm, 45 * mm, 36 * mm], aligns=[1, 2, 1, 2])
    t.setStyle(TableStyle([('BACKGROUND', (2, -1), (3, -1), colors.HexColor('#FEE2E2')),
                           ('FONTNAME', (2, -1), (3, -1), 'ArBd')]))
    elements.append(t)
    elements.append(Spacer(1, 12))

    # الصافي
    net = [
        [ar("صافي الراتب المستحق"), ar(f"{record.net_salary:,.2f} {currency}")],
        [ar("فقيمة بالحروف"), ar(_amount_words(record.net_salary))],
    ]
    t = _table(net, col_widths=[58 * mm, 108 * mm], aligns=[1, 2])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (1, 0), COLOR_GOLD),
        ('FONTNAME', (0, 0), (1, 0), 'ArBd'),
        ('FONTSIZE', (0, 0), (1, 0), 12),
        ('BACKGROUND', (0, 1), (1, 1), colors.HexColor('#F1F5F9')),
        ('TEXTCOLOR', (0, 1), (1, 1), colors.HexColor('#166534')),
        ('FONTNAME', (0, 1), (1, 1), 'ArBd'),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 14))

    # التوقيعات
    fin_full, hr_full = _signers()
    sign = [
        [ar(hr_full), ar(fin_full)],
        ["", ""],
    ]
    t = _table(sign, col_widths=[83 * mm, 83 * mm], aligns=[1, 1])
    t.setStyle(TableStyle([('LINEABOVE', (0, 1), (0, 1), 0.6, COLOR_LINE),
                           ('LINEABOVE', (1, 1), (1, 1), 0.6, COLOR_LINE),
                           ('TOPPADDING', (0, 1), (-1, 1), 12)]))
    elements.append(t)

    doc = _base_doc(buf)
    doc.build(elements, onFirstPage=lambda c, d: _footer(c, d, company),
              onLaterPages=lambda c, d: _footer(c, d, company))
    return buf.getvalue()


# ==================== كشف رواتب فترة PDF ====================

def pdf_payroll(period, records):
    buf = BytesIO()
    company, currency = _init_common("شركتي", "كشف رواتب")

    elements = []
    elements.append(Paragraph(ar(company), _style('t1', 18, True, COLOR_HEADER, 1)))
    elements.extend(_ornament_block(_GOLD))
    elements.append(Paragraph(ar(f"كشف رواتب فترة {period.name}"), _style('t2', 14, True, colors.HexColor('#1E40AF'), 1)))
    elements.extend(_ornament_block(COLOR_HEADER))
    elements.append(Spacer(1, 6))

    head = [
        [ar("م"), ar("رقم"), ar("الاسم"), ar("الأساسي"), ar("البدلات"),
         ar("إضافي"), ar("الإجمالي"), ar("الخصومات"), ar("السلف"), ar("الصافي")],
    ]
    rows = []
    for i, rec in enumerate(records, start=1):
        emp = rec.employee
        allow = round(rec.housing_allowance + rec.transport_allowance +
                      rec.food_allowance + rec.phone_allowance + rec.other_allowances, 2)
        extra = round(rec.overtime_amount + rec.bonus_amount, 2)
        ded = round(rec.total_deductions - rec.loan_deduction, 2)
        rows.append([
            i, emp.emp_id, _tc(emp.full_name), f"{rec.base_salary:,.2f}",
            f"{allow:,.2f}", f"{extra:,.2f}",
            f"{rec.gross_salary:,.2f}", f"{ded:,.2f}",
            f"{rec.loan_deduction:,.2f}", f"{rec.net_salary:,.2f}",
        ])

    def money_row(label, values):
        return [ar(label)] + [f"{v:,.2f}" for v in values]

    rows.append(money_row("الإجمالي", [
        sum(r.base_salary for r in records),
        sum(round(r.housing_allowance + r.transport_allowance + r.food_allowance +
                  r.phone_allowance + r.other_allowances, 2) for r in records),
        sum(round(r.overtime_amount + r.bonus_amount, 2) for r in records),
        sum(r.gross_salary for r in records),
        sum(round(r.total_deductions - r.loan_deduction, 2) for r in records),
        sum(r.loan_deduction for r in records),
        sum(r.net_salary for r in records),
    ]))

    t = _table(head + rows, col_widths=[9 * mm, 15 * mm, 35 * mm, 16 * mm, 16 * mm,
                                         15 * mm, 18 * mm, 18 * mm, 16 * mm, 20 * mm],
               aligns=[1, 1, 1, 2, 2, 2, 2, 2, 2, 2], split_by_row=True)
    t.setStyle(TableStyle([('BACKGROUND', (0, -1), (-1, -1), COLOR_TOTAL),
                           ('FONTNAME', (0, -1), (-1, -1), 'ArBd'),
                           ('FONTSIZE', (0, 0), (-1, -1), 7.5)]))
    elements.append(t)

    extra_notes = Paragraph(
        ar(f"عدد الموظفين: {len(records)} موظف - إجمالي صافي الرواتب: {sum(r.net_salary for r in records):,.2f} {currency}"),
        _style('n', 9, True, colors.HexColor('#475569'), align=1))
    elements.append(Spacer(1, 6))
    elements.append(extra_notes)

    doc = _base_doc(buf)
    doc.build(elements, onFirstPage=lambda c, d: _footer(c, d, company),
              onLaterPages=lambda c, d: _footer(c, d, company))
    return buf.getvalue()


# ==================== تقرير الحضور PDF ====================

def pdf_attendance(month, year, summary):
    buf = BytesIO()
    company, currency = _init_common("شركتي", "تقرير الحضور")
    month_name = MONTHS_AR[month - 1] if 1 <= month <= 12 else str(month)

    elements = []
    elements.append(Paragraph(ar(company), _style('t1', 18, True, COLOR_HEADER, 1)))
    elements.extend(_ornament_block(_GOLD))
    elements.append(Paragraph(ar(f"تقرير الحضور والانصراف - شهر {month_name} {year}"),
                              _style('t2', 14, True, colors.HexColor('#1E40AF'), 1)))
    elements.extend(_ornament_block(COLOR_HEADER))
    elements.append(Spacer(1, 6))

    head = [[ar("م"), ar("رقم الموظف"), ar("الاسم"), ar("القسم"),
             ar("حضور"), ar("تأخير"), ar("غياب"), ar("ساعات إضافية"), ar("نسبة الحضور%")]]
    rows = []
    for i, item in enumerate(summary, start=1):
        emp = item['employee']
        rows.append([
            i, emp.emp_id, _tc(emp.full_name),
            _tc(emp.department.name if emp.department else '—'),
            item['present_days'], item['late_days'], item['absent_days'],
            item['overtime_hours'], item['attendance_rate'],
        ])
    rows.append([
        ar("الإجمالي"), "", "", "",
        sum(r[4] for r in rows), sum(r[5] for r in rows), sum(r[6] for r in rows),
        round(sum(r[7] for r in rows), 2), "",
    ])

    t = _table(head + rows, col_widths=[9 * mm, 17 * mm, 42 * mm, 28 * mm,
                                         14 * mm, 14 * mm, 14 * mm, 20 * mm, 20 * mm],
               aligns=[1, 1, 1, 1, 2, 2, 2, 2, 2], split_by_row=True)
    t.setStyle(TableStyle([('BACKGROUND', (0, -1), (-1, -1), COLOR_TOTAL),
                           ('FONTNAME', (0, -1), (-1, -1), 'ArBd'),
                           ('FONTSIZE', (0, 0), (-1, -1), 8)]))
    elements.append(t)

    doc = _base_doc(buf)
    doc.build(elements, onFirstPage=lambda c, d: _footer(c, d, company),
              onLaterPages=lambda c, d: _footer(c, d, company))
    return buf.getvalue()


# ==================== تقرير التأمينات والضرائب PDF ====================

def pdf_insurance_tax(period, records):
    buf = BytesIO()
    company, currency = _init_common("شركتي", "كشف التأمينات والضرائب")

    elements = []
    elements.append(Paragraph(ar(company), _style('t1', 18, True, COLOR_HEADER, 1)))
    elements.extend(_ornament_block(_GOLD))
    elements.append(Paragraph(ar(f"كشف التأمينات الاجتماعية وضريبة كسب العمل - فترة {period.name}"),
                              _style('t2', 13, True, colors.HexColor('#1E40AF'), 1)))
    elements.extend(_ornament_block(COLOR_HEADER))
    elements.append(Spacer(1, 6))

    head = [[ar("م"), ar("رقم"), ar("الاسم"), ar("المرتب التأميني"),
             ar("تأمينات (خصم)"), ar("صافي استقطاع التأمين"), ar("ضريبة كسب العمل")]]
    rows = []
    for i, rec in enumerate(records, start=1):
        emp = rec.employee
        rows.append([
            i, emp.emp_id, _tc(emp.full_name),
            f"{rec.base_salary + rec.housing_allowance:,.2f}",
            f"{rec.social_insurance:,.2f}",
            f"{rec.social_insurance:,.2f}",
            f"{rec.tax_amount:,.2f}",
        ])
    rows.append([
        ar("الإجمالي"), "", "",
        f"{sum(rec.base_salary + rec.housing_allowance for rec in records):,.2f}",
        f"{sum(rec.social_insurance for rec in records):,.2f}",
        f"{sum(rec.social_insurance for rec in records):,.2f}",
        f"{sum(rec.tax_amount for rec in records):,.2f}",
    ])

    t = _table(head + rows, col_widths=[8 * mm, 14 * mm, 36 * mm, 31 * mm,
                                         27 * mm, 31 * mm, 31 * mm],
               aligns=[1, 1, 1, 2, 2, 2, 2], split_by_row=True)
    t.setStyle(TableStyle([('BACKGROUND', (0, -1), (-1, -1), COLOR_TOTAL),
                           ('FONTNAME', (0, -1), (-1, -1), 'ArBd'),
                           ('FONTSIZE', (0, 0), (-1, -1), 8)]))
    elements.append(t)

    elements.append(Spacer(1, 8))
    elements.append(Paragraph(
        ar("تُحتسب التأمينات الاجتماعية بنسبة وارد من إعدادات النظام، وضريبة كسب العمل وفق الشرائح الضريبية المعمول بها. يُرجع هذا الكشف مع الإقرارات الشهرية."),
        _style('n', 8, color=colors.HexColor('#475569'), align=1)
    ))

    doc = _base_doc(buf)
    doc.build(elements, onFirstPage=lambda c, d: _footer(c, d, company),
              onLaterPages=lambda c, d: _footer(c, d, company))
    return buf.getvalue()


# ==================== شهادة إجازة PDF ====================

def pdf_leave_certificate(leave):
    from models import Setting
    buf = BytesIO()
    company, currency = _init_common("شركتي", "شهادة إجازة")
    emp = leave.employee

    elements = []
    # إطار زخرفي
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(ar(company), _style('t1', 16, True, COLOR_HEADER, 1)))
    elements.extend(_ornament_block(_GOLD))
    elements.append(Paragraph(ar("يفيد بأن"), _style('t2', 10, color=colors.HexColor('#475569'), align=1)))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(ar(emp.full_name), _style('name', 22, True, colors.HexColor('#1E3A8A'), align=1)))
    elements.append(Spacer(1, 4))
    body = [
        Paragraph(ar(
            f"الرقم الوظيفي: {emp.emp_id} - القسم: {emp.department.name if emp.department else '—'} - "
            f"الوظيفة: {emp.position.title if emp.position else '—'}"
        ), _style('b1', 10, align=1)),
        Spacer(1, 8),
        Paragraph(ar(
            f"قد مُنح إجازة {leave.leave_type.name} اعتباراً من {ar_date(leave.start_date)} "
            f"وحتى {ar_date(leave.end_date)} لمدة {leave.days_count} يوم"
        ), _style('b2', 12, True, align=1)),
        Spacer(1, 6),
        Paragraph(ar(
            f"وذلك بناءً على طلب الموظف المقدم بتاريخ {ar_date(leave.created_at.date() if leave.created_at else leave.start_date)} "
            f"وتحسب هذه الإجازة ضمن رصيد إجازاته المستحقة."
        ), _style('b3', 10, align=1)),
        Spacer(1, 12),
        Paragraph(ar(f"تحرراً في: {ar_date(date.today())}"), _style('b4', 10, align=1)),
    ]
    elements.extend(body)

    # إطار حول فقرة الشهادة
    body_table = Table([[Paragraph(
        ar(f"الرقم الوظيفي: {emp.emp_id} - القسم: {emp.department.name if emp.department else '—'} - الوظيفة: {emp.position.title if emp.position else '—'}"),
        _style('b1', 10, align=1)
    )], [Paragraph(
        ar(f"قد مُنح إجازة {leave.leave_type.name} اعتباراً من {ar_date(leave.start_date)} وحتى {ar_date(leave.end_date)} لمدة {leave.days_count} يوم"),
        _style('b2', 12, True, align=1)
    )], [Paragraph(
        ar(f"وذلك بناءً على طلب الموظف المقدم بتاريخ {ar_date(leave.created_at.date() if leave.created_at else leave.start_date)} وتُحتسب ضمن رصيد إجازاته المستحقة."),
        _style('b3', 10, align=1)
    )]], colWidths=[150 * mm])
    body_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#1E3A8A')),
        ('INNERGRID', (0, 0), (-1, -1), 0.2, colors.HexColor('#CBD5E1')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
    ]))
    elements = elements[:4] + [body_table]
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(ar(f"تحريراً في: {ar_date(date.today())}"),
                              _style('b4', 10, align=1)))
    elements.append(Spacer(1, 18))

    # التوقيعات
    fin_full, hr_full = _signers()
    sign = [
        [ar(hr_full), ar(fin_full)],
        ["", ""],
    ]
    t = _table(sign, col_widths=[83 * mm, 83 * mm], aligns=[1, 1])
    t.setStyle(TableStyle([('LINEABOVE', (0, 1), (0, 1), 0.6, COLOR_LINE),
                           ('LINEABOVE', (1, 1), (1, 1), 0.6, COLOR_LINE),
                           ('TOPPADDING', (0, 1), (-1, 1), 12)]))
    elements.append(t)

    doc = _base_doc(buf)
    doc.build(elements, onFirstPage=lambda c, d: _footer(c, d, company),
              onLaterPages=lambda c, d: _footer(c, d, company))
    return buf.getvalue()


# ==================== شهادات رسمية فاخرة ====================

def _cert_painter(company, watermark):
    """رسام صفحات الشهادات: إطار مزدوج كحلي/ذهبي + علامة مائية + ترويسة داخلية"""
    def draw(canvas, doc):
        w, h = A4
        canvas.saveState()
        gold = colors.HexColor('#C9A227')
        # إطار خارجي كحلي سميك
        canvas.setStrokeColor(COLOR_HEADER)
        canvas.setLineWidth(2.0)
        canvas.rect(9 * mm, 9 * mm, w - 18 * mm, h - 18 * mm)
        # إطار داخلي ذهبي رفيع
        canvas.setStrokeColor(gold)
        canvas.setLineWidth(0.9)
        canvas.rect(12.5 * mm, 12.5 * mm, w - 25 * mm, h - 25 * mm)
        # زوايا ذهبية
        canvas.setFillColor(gold)
        d = 2.2 * mm
        for cx, cy in ((12.5 * mm, 12.5 * mm), (w - 12.5 * mm, 12.5 * mm),
                       (12.5 * mm, h - 12.5 * mm), (w - 12.5 * mm, h - 12.5 * mm)):
            canvas.circle(cx, cy, d, stroke=0, fill=1)
        # علامة مائية
        canvas.setFont('ArBd', 64)
        canvas.setFillColor(colors.HexColor('#EDF1F8'))
        canvas.saveState()
        canvas.translate(w / 2, h / 2)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, ar(watermark))
        canvas.restoreState()
        # ترويسة داخلية سفلى
        canvas.setFont('Ar', 8)
        canvas.setFillColor(colors.HexColor('#94A3B8'))
        canvas.drawCentredString(w / 2, 16 * mm, ar(f"{company} - {watermark} - {date.today().year}"))
        canvas.restoreState()
    return draw


def _ornament_block(color):
    """زخرفة سطرية: خط رفيع + نقاط مزخرفة + خط رفيع"""
    g = color
    return [
        HRFlowable(width='62%', thickness=1.0, color=g, hAlign='CENTER', spaceBefore=2, spaceAfter=0),
        Paragraph(ar("◆ ◆ ◆"), _style('orn', 9, color=g, align=1)),
        HRFlowable(width='62%', thickness=1.0, color=g, hAlign='CENTER', spaceAfter=2),
    ]


_GOLD = colors.HexColor('#B08D2F')
_GOLD_BG = colors.HexColor('#FFFDF6')


def _cert_sign_table(hr_full, other_full):
    t = _table([
        [ar(hr_full), ar(other_full)],
        ["", ""],
    ], col_widths=[83 * mm, 83 * mm], aligns=[1, 1])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.white),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_HEADER),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('LINEABOVE', (0, 1), (0, 1), 0.7, COLOR_HEADER),
        ('LINEABOVE', (1, 1), (1, 1), 0.7, _GOLD),
        ('TOPPADDING', (0, 1), (-1, 1), 12),
    ]))
    return t


def _cert_doc(buf):
    return SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=26 * mm, bottomMargin=24 * mm,
        title="شهادة رسمية", author=_signers()[0],
    )


def pdf_experience_certificate(emp):
    """شهادة خبرة رسمية فاخرة بإطار مزدوج وزخارف ذهبية"""
    company, currency = _init_common("شركتي", "شهادة خبرة")
    today = date.today()
    hire = emp.hire_date or today
    years = today.year - hire.year
    months = today.month - hire.month
    if months < 0:
        years -= 1
        months += 12
    service = f"{years} سنة و{months} شهر" if years else f"{months} شهر"

    elements = []
    elements.append(Paragraph(ar(company), _style('cc', 16, True, COLOR_HEADER, 1)))
    elements.extend(_ornament_block(_GOLD))
    elements.append(Paragraph(ar("شهادة خبرة"), _style('ct', 26, True, _GOLD, 1)))
    elements.append(Paragraph(ar("CERTIFICATE OF EXPERIENCE"), _style('cen', 9, color=colors.HexColor('#94A3B8'), align=1)))
    elements.extend(_ornament_block(COLOR_HEADER))
    elements.append(Spacer(1, 14))

    elements.append(Paragraph(ar(f"تشهد شركة {company} بأن:"), _style('cb', 12.5, align=1)))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(ar(emp.full_name), _style('cn', 26, True, COLOR_HEADER, 1)))
    elements.append(HRFlowable(width='45%', thickness=1.0, color=_GOLD, hAlign='CENTER'))
    elements.append(Spacer(1, 4))
    job = f"{emp.position.title if emp.position else 'موظف'} - {emp.department.name if emp.department else 'بالشركة'}"
    elements.append(Paragraph(ar(job), _style('cj', 12, color=colors.HexColor('#475569'), align=1)))
    elements.append(Spacer(1, 16))

    body_txt = (
        f"تعمل لدى الشركة بصفة {emp.position.title if emp.position else 'موظف'} منذ {ar_date(hire)} وحتى تاريخه، "
        f"أي لمدة {service}، وتتقاضى راتباً شهرياً قدره {emp.total_salary:,.2f} {currency}. "
        f"وقد كان سلوكه وسيرته داخل الشركة حسنين، وأداؤه في عمله متميزاً."
    )
    info = Table([[Paragraph(ar(body_txt), _style('cb2', 12.5, align=1))]], colWidths=[150 * mm])
    info.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), _GOLD_BG),
        ('BOX', (0, 0), (-1, -1), 0.9, _GOLD),
        ('TOPPADDING', (0, 0), (-1, -1), 16),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 16),
        ('LEFTPADDING', (0, 0), (-1, -1), 18),
        ('RIGHTPADDING', (0, 0), (-1, -1), 18),
    ]))
    elements.append(info)
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(ar(
        "تمنحه هذه الشهادة بناءً على طلبه دون أي مسئولية على الشركة، لاستخدامها فيما يراه مناسباً وبأمانة."
    ), _style('cc2', 10, color=colors.HexColor('#64748B'), align=1)))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(
        ar(f"الرقم الوظيفي: {emp.emp_id}     |     تحريراً في: {ar_date(today)}"),
        _style('cc3', 11, align=1)))
    elements.append(Spacer(1, 18))

    fin_full, hr_full = _signers()
    elements.append(_cert_sign_table(hr_full, "ختم الشركة"))

    buf = BytesIO()
    doc = _cert_doc(buf)
    painter = _cert_painter(company, "شهادة خبرة")
    doc.build(elements, onFirstPage=painter, onLaterPages=painter)
    return buf.getvalue()


def pdf_appreciation_certificate(emp, reason, issued_on=None):
    """شهادة تقدير رسمية فاخرة (تكريم للموظف على عمل متميز)"""
    company, currency = _init_common("شركتي", "شهادة تقدير")
    issued_on = issued_on or date.today()
    if isinstance(issued_on, datetime):
        issued_on = issued_on.date()
    reason = reason or "تقديراً لجهوده المتميزة وتفانيه في العمل خلال فترة عمله بالشركة"

    elements = []
    elements.append(Paragraph(ar(company), _style('cc', 16, True, COLOR_HEADER, 1)))
    elements.extend(_ornament_block(_GOLD))
    elements.append(Paragraph(ar("شهادة تقدير"), _style('ct', 26, True, _GOLD, 1)))
    elements.append(Paragraph(ar("CERTIFICATE OF APPRECIATION"), _style('cen', 9, color=colors.HexColor('#94A3B8'), align=1)))
    elements.extend(_ornament_block(COLOR_HEADER))
    elements.append(Spacer(1, 14))

    elements.append(Paragraph(ar("يُشهد بهذا أن:"), _style('cb', 12.5, align=1)))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(ar(emp.full_name), _style('cn', 26, True, COLOR_HEADER, 1)))
    elements.append(HRFlowable(width='45%', thickness=1.0, color=_GOLD, hAlign='CENTER'))
    elements.append(Spacer(1, 4))
    job = f"{emp.position.title if emp.position else 'موظف'} - {emp.department.name if emp.department else 'بالشركة'}"
    elements.append(Paragraph(ar(job), _style('cj', 12, color=colors.HexColor('#475569'), align=1)))
    elements.append(Spacer(1, 16))

    body_txt = (
        f"{reason}، فقد أثبت كفاءة عالية وأمانة فائقة في أداء مهامه الوظيفية، "
        f"وكان مثالاً يحتذى به في الالتزام والتفاني، لذا تستحق منا كل الشكر والتقدير."
    )
    info = Table([[Paragraph(ar(body_txt), _style('cb2', 12.5, align=1))]], colWidths=[150 * mm])
    info.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), _GOLD_BG),
        ('BOX', (0, 0), (-1, -1), 0.9, _GOLD),
        ('TOPPADDING', (0, 0), (-1, -1), 16),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 16),
        ('LEFTPADDING', (0, 0), (-1, -1), 18),
        ('RIGHTPADDING', (0, 0), (-1, -1), 18),
    ]))
    elements.append(info)
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(
        ar(f"الرقم الوظيفي: {emp.emp_id}     |     تاريخ الإصدار: {ar_date(issued_on)}"),
        _style('cc3', 11, align=1)))
    elements.append(Spacer(1, 18))

    fin_full, hr_full = _signers()
    elements.append(_cert_sign_table(hr_full, fin_full))

    buf = BytesIO()
    doc = _cert_doc(buf)
    painter = _cert_painter(company, "شهادة تقدير")
    doc.build(elements, onFirstPage=painter, onLaterPages=painter)
    return buf.getvalue()


# ==================== أدوات مساعدة ====================

def ar_date(d):
    """تاريخ عربي مثل 15 يناير 2026"""
    if not d:
        return "—"
    if isinstance(d, datetime):
        d = d.date()
    return f"{d.day} {MONTHS_AR[d.month - 1]} {d.year}"


def _amount_words(amount):
    """تحويل المبلغ إلى كلمات عربية"""
    try:
        return number_to_words(amount)
    except Exception:
        return f"{float(amount):,.2f} ج.م"


_UNITS = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة",
          "عشرة", "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر", "ستة عشر",
          "سبعة عشر", "ثمانية عشر", "تسعة عشر"]
_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
_HUNDREDS = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة"]


def _three_digits(n):
    out = []
    h = n // 100
    if h:
        out.append(_HUNDREDS[h])
    r = n % 100
    if r:
        if r < 20:
            out.append(_UNITS[r])
        else:
            u = r % 10
            t = r // 10
            if u:
                out.append(f"{_UNITS[u]} و{_TENS[t]}")
            else:
                out.append(_TENS[t])
    return " ".join(out)


def number_to_words(num):
    num = int(round(float(num)))
    if num == 0:
        return "صفر"
    parts = []
    thousands = num // 1000
    remainder = num % 1000
    if thousands:
        t = _three_digits(thousands)
        parts.append(f"{t} ألف")
    if remainder:
        parts.append(_three_digits(remainder))
    return " ".join(parts) + " جنيهاً مصرياً فقط لا غير"
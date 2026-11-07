"""PDF and Excel outputs. They only lay out figures that the loan page already calculates."""
import io
from datetime import date, timedelta
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

VALID_DAYS = 7  # the quote is valid for this many days after the quote date


def rs(v) -> str:
    """Amount as text, for the PDF (plain text, so the rupee sign isn't needed)."""
    return f"Rs. {Decimal(str(v)):,.2f}"


def fcl_pdf(loan, cust, q: dict, as_of: date) -> bytes:
    styles = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40,
                            title=f"Foreclosure quote {loan.loan_number}")
    valid_till = as_of + timedelta(days=VALID_DAYS)
    story = [
        Paragraph("Foreclosure quote", styles["Title"]),
        Paragraph(f"Quote date: {as_of:%d %b %Y} &nbsp;&nbsp; Valid till: {valid_till:%d %b %Y}", styles["Normal"]),
        Spacer(1, 12),
    ]
    details = [
        ["Account number", loan.loan_number, "Disbursal date", f"{loan.disbursal_date:%d %b %Y}"],
        ["Customer name", cust.name if cust else "", "Mobile", (cust.mobile if cust and cust.mobile else "")],
    ]
    t = Table(details, colWidths=[110, 160, 90, 160])
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                           ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                           ("BACKGROUND", (2, 0), (2, -1), colors.whitesmoke)]))
    story += [t, Spacer(1, 14)]
    lines = [
        ["Particulars", "Amount"],
        ["Principal outstanding (POS)", rs(q["principal_outstanding"])],
        [f"Interest ({q['interest_note']})", rs(q["interest"])],
        [f"Foreclosure charges ({q['fcl_percent']}% of POS)", rs(q["fcl_charges"])],
        ["GST 18% on foreclosure charges", rs(q["gst"])],
        ["Foreclosure amount", rs(q["fcl_amount"])],
        ["Charges (late and bounce)", rs(q["bounce_charges"])],
        ["Less excess held", rs(q["excess"])],
        ["Foreclosure fee", rs(q["foreclosure_fee"])],
        ["Total payable", rs(q["total"])],
    ]
    t = Table(lines, colWidths=[330, 150])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d2433")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eef0f4")),
    ]))
    story += [t, Spacer(1, 16), Paragraph("Amounts are as calculated by the loan account on the date shown.", styles["Italic"])]
    doc.build(story)
    return buf.getvalue()


DUES_COLUMNS = [
    ("Account number", None), ("Customer name", None), ("Mobile number", None),
    ("Principal outstanding", "n"), ("Interest outstanding", "n"),
    ("Overdue principal", "n"), ("Overdue interest", "n"),
    ("Charges due (unpaid actual charges)", "n"),
    ("Total overdue", "n"), ("Total outstanding", "n"),
    ("DPD", "n"), ("DPD bucket", None), ("Excess held", "n"),
]


def dues_xlsx(rows: list[dict], as_of: date) -> bytes:
    """rows: one dict per loan with the keys in DUES_COLUMNS, in order (numbers as Decimal)."""
    wb = Workbook()
    ws = wb.active
    ws.title = f"Dues {as_of:%d-%m-%Y}"
    ws.append([f"Dues as of {as_of:%d %b %Y}"])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append([])
    header = [name for name, _ in DUES_COLUMNS]
    ws.append(header)
    for c in ws[3]:
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="center")
    first = 4
    for r in rows:
        ws.append([float(r[name]) if kind == "n" and r[name] is not None else r[name]
                   for name, kind in DUES_COLUMNS])
    last = first + len(rows) - 1
    total_row = last + 1
    ws.append(["Total"] + [""] * (len(DUES_COLUMNS) - 1))
    for idx, (name, kind) in enumerate(DUES_COLUMNS, start=1):
        if kind == "n" and rows:
            col = ws.cell(row=3, column=idx).column_letter
            ws.cell(row=total_row, column=idx, value=f"=SUM({col}{first}:{col}{last})")
    for c in ws[total_row]:
        c.font = Font(bold=True)
    for row in ws.iter_rows(min_row=first, max_row=total_row):
        for c in row:
            if isinstance(c.value, float) or (isinstance(c.value, str) and c.value.startswith("=SUM")):
                c.number_format = "#,##0.00"
    widths = [16, 28, 14, 16, 16, 16, 16, 20, 16, 16, 8, 16, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=3, column=i).column_letter].width = w
    ws.freeze_panes = "A4"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

import csv
import io
import re

from docx import Document
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font

COLUMNS = ["type", "statement", "grade", "quote", "source", "note"]
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def safe(value):
    text = str(value)
    return "'" + text if text.startswith(FORMULA_STARTS) else text


def to_csv(rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([safe(row[column]) for column in COLUMNS])
    return buffer.getvalue()


def to_xlsx(rows):
    book = Workbook()
    plan = book.active
    plan.title = "Plan"
    plan.append(COLUMNS)
    for cell in plan[1]:
        cell.font = Font(bold=True)
    for row in rows:
        plan.append([safe(row[column]) for column in COLUMNS])
    for column, width in zip("ABCDEF", (16, 70, 14, 50, 22, 40)):
        plan.column_dimensions[column].width = width
    for line in plan.iter_rows(min_row=2):
        for cell in line:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    summary = book.create_sheet("Summary")
    summary.append(["Grade", "Claims"])
    for grade in ("Backed", "Testimony", "Conflicting", "Unknown", "Inferred"):
        summary.append([grade, sum(1 for row in rows if row["grade"] == grade)])
    chart = BarChart()
    chart.title = "Claims by grade"
    chart.add_data(Reference(summary, min_col=2, min_row=1, max_row=6), titles_from_data=True)
    chart.set_categories(Reference(summary, min_col=1, min_row=2, max_row=6))
    chart.legend = None
    summary.add_chart(chart, "D2")
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def plain(rows):
    return [{column: row[column] for column in COLUMNS} for row in rows]


def clean(value):
    return CONTROL.sub("", str(value))


def xml_text(value):
    return clean(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def to_xml(rows, title):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', f'<handover project="{xml_text(title)}">']
    for row in rows:
        fields = "".join(f"<{column}>{xml_text(row[column])}</{column}>" for column in COLUMNS)
        lines.append(f'  <claim section="{xml_text(row["section"])}">{fields}</claim>')
    lines.append("</handover>")
    return "\n".join(lines)


def to_docx(rows, title):
    document = Document()
    document.add_heading(clean(title), 0)
    document.add_paragraph("Every statement links back to its source. The label shows how well it is backed.")
    section = None
    for row in rows:
        if row["section"] != section:
            section = row["section"]
            document.add_heading(clean(section), 1)
        paragraph = document.add_paragraph(style="List Bullet")
        paragraph.add_run(clean(row["statement"]))
        paragraph.add_run(clean(f"  [{row['grade']}, source: {row['source']}]")).italic = True
        if row["note"]:
            paragraph.add_run(clean(f"  Note: {row['note']}"))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()

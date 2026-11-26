"""Supplementary Information for the WIMM paper: Figure S1 (trajectories) and Table S1
(every benchmark measure next to the value WIMM exported), built from the per-paradigm
sheets of the benchmark summary workbook."""
import os

import docx
import openpyxl
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "APP_vs_benchmark_summary.xlsx")
FIG_S1 = os.path.join(HERE, "FigureS1_trajectories.png")
OUT = os.path.join(HERE, "Supplementary Information.docx")
TITLE = ("From Natural Language to Laboratory Tool: AI-Assisted Development of WIMM, "
         "an Open-Source Mouse Tracking Platform")
STATUS = {"exact": "exact", "close": "close", "differs": "differs", "not reported by WIMM": "not exported"}
SHADE = {"differs": "FFC7CE"}


def fmt(v):
    if v is None:
        return "–"
    if isinstance(v, str):
        return "not exported" if v == "not reported" else v
    return f"{v:.3f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def shade(cell, hex_):
    tc = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), hex_)
    tc.append(sh)


def para(doc, text="", size=11, bold=False, italic=False, align=None, after=6):
    p = doc.add_paragraph()
    if text:
        r = p.add_run(text)
        r.bold, r.italic, r.font.size = bold, italic, Pt(size)
    p.paragraph_format.space_after = Pt(after)
    if align:
        p.alignment = align
    return p


def caption(doc, label, text):
    p = doc.add_paragraph()
    r = p.add_run(label + " ")
    r.bold = True
    p.add_run(text)
    p.paragraph_format.space_after = Pt(10)
    return p


def read_rows():
    wb = openpyxl.load_workbook(SRC, data_only=True)
    out = []
    for ws in wb.worksheets:
        if not ws.title[:2].isdigit():
            continue
        name, seen, rows = ws.title[3:].replace("_", " "), set(), []
        for sec, meas, bench, app, wname, diff, pct, st in ws.iter_rows(min_row=2, max_col=8, values_only=True):
            if not meas:
                continue
            dup = app != "not reported" and wname in seen
            seen.add(wname)
            rows.append((sec, meas, bench, app, diff, pct, st, dup))
        out.append((name, rows))
    return out


def main():
    data = read_rows()
    allr = [r for _, rows in data for r in rows]
    tot = {k: sum(r[6] == k for r in allr) for k in STATUS}
    ndup = sum(r[7] for r in allr)
    assert len(data) == 12 and len(allr) == 445 and tot == {"exact": 241, "close": 141, "differs": 20,
                                                             "not reported by WIMM": 43} and ndup == 5, (tot, ndup)

    doc = docx.Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Times New Roman", Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    for m in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, m, Cm(2))

    para(doc, "Supplementary Information", 16, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    para(doc, TITLE, 12, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=18)
    para(doc, "Contents", 12, bold=True)
    para(doc, "Supplementary Figure S1. Trajectories of the 12 synthetic validation recordings", after=2)
    para(doc, "Supplementary Table S1. Every benchmark measure compared with the value exported by WIMM", after=18)

    # --- Figure S1 -------------------------------------------------------------------
    doc.add_picture(FIG_S1, width=Cm(17))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption(doc, "Supplementary Figure S1.",
            "Trajectories of the 12 synthetic validation recordings. For each standard paradigm, the scripted path "
            "of the animal (benchmark, solid blue line) and the path tracked by WIMM 1.0.0 (dashed red line) are "
            "overlaid on a frame of the recording; the green dot marks the start. Each recording lasted 30 s "
            "(1280 × 720 pixels, 30 frames per second). The two paths coincide in every paradigm except the "
            "light–dark box, in which the dark animal could not be separated from the dark floor of the dark "
            "compartment, so that the tracked path is largely absent there.")
    doc.add_page_break()

    # --- Table S1 --------------------------------------------------------------------
    caption(doc, "Supplementary Table S1.",
            "Every benchmark measure of the 12 synthetic recordings compared with the value exported by WIMM 1.0.0. "
            "Benchmark values were calculated from the scripted path, with position defined as the centroid of the "
            "body excluding the tail, or as the tip of the snout for nose-based measures. Recordings were analyzed "
            "with default detection and smoothing settings, a movement threshold of 2 cm/s and a minimum dwell time "
            "of 0 s. Difference = WIMM − benchmark; difference (%) is relative to the benchmark value and is blank "
            "when the benchmark is 0. Status: exact, identical when rounded to two decimals; close, within 0.1 units "
            "or 5%; differs, outside both limits (counts and text values must match exactly to count as exact); "
            "not exported, a benchmark measure that WIMM does not report. Rows marked † show a WIMM value that is "
            "already listed under another benchmark name in the same paradigm (it is plotted once in Figure 2). "
            f"In total, {len(allr)} benchmark measures were listed, of which {len(allr) - tot['not reported by WIMM']} "
            f"had a WIMM value: {tot['exact']} exact, {tot['close']} close and {tot['differs']} differing "
            f"(shaded); {tot['not reported by WIMM']} were not exported by WIMM.")

    cols = ["Measure", "Benchmark", "WIMM", "Difference", "Difference (%)", "Status"]
    widths = [Cm(7.2), Cm(2.3), Cm(2.3), Cm(2.0), Cm(1.9), Cm(1.9)]
    t = doc.add_table(rows=1, cols=len(cols))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = t.rows[0]
    hdr._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))  # repeat header on each page

    def fill(row, vals, bold=False, italic=False, size=8):
        for c, v, w in zip(row.cells, vals, widths):
            c.width = w
            p = c.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(v)
            r.bold, r.italic, r.font.size = bold, italic, Pt(size)

    fill(hdr, cols, bold=True)
    for c in hdr.cells:
        shade(c, "D9D9D9")

    for name, rows in data:
        n = {k: sum(r[6] == k for r in rows) for k in STATUS}
        row = t.add_row()
        m = row.cells[0].merge(row.cells[-1])
        m.paragraphs[0].paragraph_format.space_after = Pt(0)
        r = m.paragraphs[0].add_run(f"{name}")
        r.bold, r.font.size = True, Pt(9)
        r = m.paragraphs[0].add_run(
            f"  —  {len(rows) - n['not reported by WIMM']} compared: {n['exact']} exact, {n['close']} close, "
            f"{n['differs']} differ; {n['not reported by WIMM']} not exported")
        r.font.size = Pt(8)
        shade(m, "EDEDED")
        last_sec = None
        for sec_name, meas, bench, app, diff, pct, status, dup in rows:
            if sec_name != last_sec:
                srow = t.add_row()
                sm = srow.cells[0].merge(srow.cells[-1])
                sm.paragraphs[0].paragraph_format.space_after = Pt(0)
                rr = sm.paragraphs[0].add_run(sec_name)
                rr.italic, rr.font.size = True, Pt(8)
                last_sec = sec_name
            vals = [meas + (" †" if dup else ""), fmt(bench), fmt(app), fmt(diff),
                    "" if pct is None and isinstance(diff, (int, float)) else fmt(pct), STATUS[status]]
            row = t.add_row()
            fill(row, vals)
            if status in SHADE:
                for c in row.cells:
                    shade(c, SHADE[status])
            if status == "not reported by WIMM":
                for c in row.cells:
                    for rr in c.paragraphs[0].runs:
                        rr.font.color.rgb = RGBColor(0x76, 0x76, 0x76)

    for row in t.rows:  # numbers right-aligned
        for c in row.cells[1:5]:
            if len(row.cells) == len(cols) and c.paragraphs[0].runs and row.cells[0]._tc is not row.cells[1]._tc:
                c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT

    doc.save(OUT)
    print("saved", OUT, len(allr), "rows", tot, "dup", ndup)


if __name__ == "__main__":
    main()

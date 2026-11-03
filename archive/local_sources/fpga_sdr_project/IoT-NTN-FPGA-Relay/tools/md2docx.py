#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""md2docx.py -- convert the project's Markdown report into a formatted DOCX.

Handles: headings, paragraphs, bullet/numbered lists, block quotes, fenced code
blocks, pipe tables, inline **bold** and `code`.
"""
import io
import os
import re
import sys

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

CJK = "微软雅黑"
MONO = "Consolas"
MONO_CJK = "NSimSun"   # 中英文都等宽，ASCII 图才对齐
MAXW = 17.0          # cm, A4 with 2 cm side margins


# ---------------------------------------------------------------- low level
def set_run(run, size=None, bold=None, italic=None, mono=False, color=None):
    run.font.name = MONO if mono else CJK
    # 代码/ASCII 图必须用「中英文等宽」的字体，否则中文按全宽、英文按半宽渲染，
    # 制表符画出来的框图会错位。
    run._element.rPr.rFonts.set(qn("w:eastAsia"), MONO_CJK if mono else CJK)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    return run


INLINE = re.compile(r"(\*\*.+?\*\*|~~.+?~~|`[^`]+`|(?<!\*)\*[^*\n]+?\*(?!\*))")


def add_inline(p, text, size=10.5, base_bold=False):
    """Write text into p, honouring **bold**, *italic*, ~~strike~~ and `code`."""
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            set_run(p.add_run(part[2:-2]), size=size, bold=True)
        elif part.startswith("~~") and part.endswith("~~") and len(part) > 4:
            r = set_run(p.add_run(part[2:-2]), size=size, italic=True)
            r.font.strike = True
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            r = set_run(p.add_run(part[1:-1]), size=size - 0.7, mono=True)
            r.font.color.rgb = RGBColor(0xA0, 0x30, 0x30)
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            set_run(p.add_run(part[1:-1]), size=size, italic=True)
        else:
            set_run(p.add_run(part), size=size, bold=base_bold)


def make_table(doc, rows):
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    t = doc.add_table(rows=0, cols=ncol)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False

    tblPr = t._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)

    # column widths: weight by max content length, then normalise to MAXW
    weights = []
    for c in range(ncol):
        w = max(len(r[c]) for r in rows)
        weights.append(max(w, 6))
    tot = float(sum(weights))
    widths = [max(1.3, MAXW * w / tot) for w in weights]
    scale = MAXW / sum(widths)
    widths = [w * scale for w in widths]

    grid = OxmlElement("w:tblGrid")
    for w in widths:
        gc = OxmlElement("w:gridCol")
        gc.set(qn("w:w"), str(int(Cm(w).twips)))
        grid.append(gc)
    # python-docx's add_table() already created a w:tblGrid -- remove it first,
    # otherwise the table carries two grids and the column widths are ignored.
    old = t._tbl.find(qn("w:tblGrid"))
    if old is not None:
        t._tbl.remove(old)
    t._tbl.insert(list(t._tbl).index(tblPr) + 1, grid)

    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for ci, txt in enumerate(row):
            cells[ci].width = Cm(widths[ci])
            para = cells[ci].paragraphs[0]
            para.paragraph_format.space_after = Pt(1)
            add_inline(para, txt, size=8.5, base_bold=(ri == 0))
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def add_code(doc, lines):
    for ln in lines:
        p = doc.add_paragraph()
        r = set_run(p.add_run(ln if ln else " "), size=8.2, mono=True)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.left_indent = Cm(0.5)
        p.paragraph_format.line_spacing = 1.0
    doc.add_paragraph().paragraph_format.space_after = Pt(3)


def add_quote(doc, lines):
    for ln in lines:
        p = doc.add_paragraph()
        add_inline(p, ln, size=10)
        for r in p.runs:
            r.font.italic = True
        p.paragraph_format.left_indent = Cm(0.8)
        p.paragraph_format.space_after = Pt(1)
        pPr = p._p.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        left = OxmlElement("w:left")
        left.set(qn("w:val"), "single")
        left.set(qn("w:sz"), "18")
        left.set(qn("w:space"), "6")
        left.set(qn("w:color"), "4472C4")
        bdr.append(left)
        pPr.append(bdr)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


# ---------------------------------------------------------------- converter
def convert(md_path, docx_path, title=None):
    raw = io.open(md_path, encoding="utf-8").read().split("\n")

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), CJK)

    for lvl, sz in ((1, 15), (2, 13), (3, 11.5), (4, 10.8)):
        s = doc.styles["Heading %d" % lvl]
        s.font.name = CJK
        s.element.rPr.rFonts.set(qn("w:eastAsia"), CJK)
        s.font.size = Pt(sz)
        s.font.color.rgb = RGBColor(0x1F, 0x3B, 0x63)

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin = sec.bottom_margin = Cm(2.2)

    i = 0
    n = len(raw)
    while i < n:
        line = raw[i]

        # fenced code
        if line.strip().startswith("```"):
            buf = []
            i += 1
            while i < n and not raw[i].strip().startswith("```"):
                buf.append(raw[i])
                i += 1
            i += 1
            add_code(doc, buf)
            continue

        # table
        if line.strip().startswith("|") and i + 1 < n and \
           re.match(r"^\s*\|[\s:|-]+\|\s*$", raw[i + 1]):
            rows = []
            while i < n and raw[i].strip().startswith("|"):
                cells = [c.strip() for c in raw[i].strip().strip("|").split("|")]
                if not re.match(r"^[\s:|-]+$", "|".join(cells)):
                    rows.append(cells)
                i += 1
            if rows:
                make_table(doc, rows)
            continue

        # block quote
        if line.strip().startswith(">"):
            buf = []
            while i < n and raw[i].strip().startswith(">"):
                buf.append(raw[i].strip().lstrip(">").strip())
                i += 1
            add_quote(doc, [b for b in buf if b != ""] or [""])
            continue

        # horizontal rule
        if re.match(r"^\s*(-{3,}|\*{3,})\s*$", line):
            p = doc.add_paragraph()
            pPr = p._p.get_or_add_pPr()
            bdr = OxmlElement("w:pBdr")
            bot = OxmlElement("w:bottom")
            bot.set(qn("w:val"), "single")
            bot.set(qn("w:sz"), "6")
            bot.set(qn("w:color"), "BFBFBF")
            bdr.append(bot)
            pPr.append(bdr)
            p.paragraph_format.space_after = Pt(6)
            i += 1
            continue

        # headings
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            lvl = min(len(m.group(1)), 4)
            if lvl == 1 and not doc.paragraphs:
                p = doc.add_heading("", level=0)
                set_run(p.add_run(m.group(2)), size=19, bold=True)
            else:
                p = doc.add_heading("", level=lvl)
                set_run(p.add_run(m.group(2)), size={1: 15, 2: 13, 3: 11.5, 4: 10.8}[lvl],
                        bold=True)
            i += 1
            continue

        # bullets
        if re.match(r"^\s*[-*]\s+", line):
            while i < n and re.match(r"^\s*[-*]\s+", raw[i]):
                txt = re.sub(r"^\s*[-*]\s+", "", raw[i])
                p = doc.add_paragraph(style="List Bullet")
                add_inline(p, txt)
                p.paragraph_format.space_after = Pt(2)
                i += 1
            continue

        # numbered -- written as literal text; the built-in "List Number" style
        # shares one counter across the whole document and would keep counting
        # up across unrelated sections.
        if re.match(r"^\s*\d+\.\s+", line):
            while i < n and re.match(r"^\s*\d+\.\s+", raw[i]):
                m2 = re.match(r"^\s*(\d+)\.\s+(.*)$", raw[i])
                p = doc.add_paragraph()
                set_run(p.add_run(m2.group(1) + ". "), size=10.5, bold=True)
                add_inline(p, m2.group(2))
                p.paragraph_format.left_indent = Cm(0.75)
                p.paragraph_format.first_line_indent = Cm(-0.75)
                p.paragraph_format.space_after = Pt(2)
                i += 1
            doc.add_paragraph().paragraph_format.space_after = Pt(0)
            continue

        # blank
        if not line.strip():
            i += 1
            continue

        # paragraph
        p = doc.add_paragraph()
        add_inline(p, line.strip())
        p.paragraph_format.space_after = Pt(4)
        i += 1

    doc.save(docx_path)
    return len(doc.paragraphs), len(doc.tables)


if __name__ == "__main__":
    src = sys.argv[1]
    dst = sys.argv[2]
    np_, nt = convert(src, dst)
    print("saved:", dst)
    print("paragraphs:", np_, " tables:", nt)

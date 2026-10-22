# -*- coding: utf-8 -*-
"""统一报告中图表的题注与注释格式（幂等，可重复执行）。

规范：
  - 题注（"图1　…" / "表1　…"）：居中、**加粗**、10.5pt、宋体 + Times New Roman
  - 注释（题注后紧邻的说明段落，或 "注：…"）：两端对齐、不加粗、9pt(小五)、宋体 + TNR

识别方式：题注按文本前缀；注释按**结构位置**（题注之后紧邻的非空、非标题、
非下一题注/表题段落）+ "注：" 前缀。只改格式，绝不触碰 w:t 文本。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

TNR = "Times New Roman"
SONG = "宋体"
CAP_RE = re.compile(r"^(图\d+(（[a-z]）)?　|表\d+)")
NOTE_PREFIX = re.compile(r"^注：")

CAP_SZ = 10.5
NOTE_SZ = 9.0


def style_run(run, sz_pt: float, bold: bool):
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs"):
        rf.set(qn(a), TNR)
    rf.set(qn("w:eastAsia"), SONG)
    run.font.size = Pt(sz_pt)
    run.font.bold = bold


def apply(para, sz_pt, bold, align):
    para.alignment = align
    for run in para.runs:
        if run.text.strip():
            style_run(run, sz_pt, bold)


def main(path: str) -> int:
    p = Path(path)
    d = docx.Document(str(p))
    paras = d.paragraphs

    cap_idx, note_idx = [], []
    for i, para in enumerate(paras):
        t = para.text.strip()
        if not t:
            continue
        if CAP_RE.match(t):
            cap_idx.append(i)
            j = i + 1
            while j < len(paras) and not paras[j].text.strip():
                j += 1
            if j >= len(paras):
                continue
            nt = paras[j].text.strip()
            st = paras[j].style.name if paras[j].style else ""
            if (nt and not st.startswith("Heading") and not CAP_RE.match(nt)
                    and not NOTE_PREFIX.match(nt)):
                note_idx.append(j)
        elif NOTE_PREFIX.match(t):
            note_idx.append(i)

    for i in cap_idx:
        apply(paras[i], CAP_SZ, True, WD_ALIGN_PARAGRAPH.CENTER)
    for i in note_idx:
        apply(paras[i], NOTE_SZ, False, WD_ALIGN_PARAGRAPH.JUSTIFY)

    d.save(str(p))
    print("题注 %d 处 → 居中/加粗/%.1fpt/宋体+TNR" % (len(cap_idx), CAP_SZ))
    print("注释 %d 处 → 两端对齐/不加粗/%.1fpt/宋体+TNR" % (len(note_idx), NOTE_SZ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))

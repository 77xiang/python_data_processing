# -*- coding: utf-8 -*-
"""把已生成的报告 docx 的格式对齐到模板 项目报告模版.docx。

对齐项：
- 页边距：上下 2.44cm / 左右 2.98cm（模板实测）
- docDefaults 字体：ascii/hAnsi/cs = Times New Roman，eastAsia = 宋体
- 正文（Normal）：宋体(中文)/Times New Roman(英文数字)，10.5pt(21)，两端对齐，
  单倍行距，无首行缩进（与模板一致）
- 标题 1/2/3：黑体(中文)/Times New Roman(英文数字)，24/16/13.5pt，加粗；
  H2 行距 1.7 倍(line=408 auto)，其余单倍；无缩进
- 目录（toc 1-9 / TOC Heading）：宋体/TNR，11pt(22)，对齐模板
- 代码块（表格内含 def/return/import 的单元格）：Courier New 10pt(20)
- 其余表格单元格：宋体/TNR 10.5pt

要求“数字和英语统一使用 Times New Roman” → 每个 run 的 ascii/hAnsi/cs 设为 TNR，
中文（eastAsia）按上下文设为宋体或黑体（标题）。
"""
from __future__ import annotations

import sys
import zipfile
import shutil
from pathlib import Path

from lxml import etree
import docx
from docx.shared import Cm
from docx.oxml.ns import qn as pqn

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TNR = "Times New Roman"
SONG = "宋体"
HEI = "黑体"
COURIER = "Courier New"


def w(tag: str) -> str:
    return W + tag


def set_attrs(el, **attrs):
    for k, v in attrs.items():
        el.set(w(k), str(v))


def ensure_child(parent, tag, attrs=None):
    el = parent.find(w(tag))
    if el is None:
        el = etree.SubElement(parent, w(tag))
    if attrs:
        set_attrs(el, **attrs)
    return el


def set_rfonts(rpr, ascii_font, ea_font):
    rf = ensure_child(rpr, "rFonts")
    set_attrs(rf, ascii=ascii_font, hAnsi=ascii_font, eastAsia=ea_font, cs=ascii_font)


def set_sz(rpr, half):
    sz = ensure_child(rpr, "sz")
    sz.set(w("val"), str(half))
    # 同时清掉 szCs 以免冲突（若有）
    szcs = rpr.find(w("szCs"))
    if szcs is not None:
        szcs.set(w("val"), str(half))


def ensure_bold(rpr, on: bool):
    b = rpr.find(w("b"))
    if on:
        if b is None:
            b = etree.SubElement(rpr, w("b"))
        b.set(w("val"), "1")
    else:
        if b is not None:
            b.set(w("val"), "0")


def ensure_rpr(parent):
    return ensure_child(parent, "rPr")


# ---------------------------------------------------------------------------
# 1) 页边距
# ---------------------------------------------------------------------------
def fix_margins(docx_path: Path):
    d = docx.Document(str(docx_path))
    for sec in d.sections:
        sec.top_margin = Cm(2.44)
        sec.bottom_margin = Cm(2.44)
        sec.left_margin = Cm(2.98)
        sec.right_margin = Cm(2.98)
    d.save(str(docx_path))


# ---------------------------------------------------------------------------
# 2) styles.xml
# ---------------------------------------------------------------------------
def fix_styles(styles_root):
    # docDefaults
    dd = styles_root.find(w("docDefaults"))
    if dd is None:
        dd = etree.SubElement(styles_root, w("docDefaults"))
    rpr_def = dd.find(w("rPrDefault"))
    if rpr_def is None:
        rpr_def = etree.SubElement(dd, w("rPrDefault"))
    rpr = ensure_child(rpr_def, "rPr")
    set_rfonts(rpr, TNR, SONG)
    # autoSpace 关掉（渲染层，双保险；实际空格已在源稿删除）
    for tag in ("autoSpaceDE", "autoSpaceDN"):
        n = rpr.find(w(tag))
        if n is None:
            n = etree.SubElement(rpr, w(tag))
        n.set(w("val"), "false")
    # pPrDefault 不设置行距（单倍，与模板一致）

    def get_style(name):
        for st in styles_root.iter(w("style")):
            nm = st.find(w("name"))
            if nm is not None and nm.get(w("val")) == name:
                return st
        # 新建
        st = etree.SubElement(styles_root, w("style"))
        set_attrs(st, type="paragraph", styleId=_style_id(name))
        nm = etree.SubElement(st, w("name"))
        nm.set(w("val"), name)
        return st

    def set_style_rpr(st, ascii_font, ea_font, sz_half, bold=False):
        rpr = ensure_child(st, "rPr")
        set_rfonts(rpr, ascii_font, ea_font)
        set_sz(rpr, sz_half)
        ensure_bold(rpr, bold)

    def set_style_ppr(st, jc=None, line=None, line_rule=None,
                      before=None, after=None, ind_left=None, ind_first=None):
        ppr = ensure_child(st, "pPr")
        if jc is not None:
            ensure_child(ppr, "jc").set(w("val"), jc)
        if line is not None or before is not None or after is not None:
            sp = ensure_child(ppr, "spacing")
            if line is not None:
                sp.set(w("line"), str(line))
                sp.set(w("lineRule"), line_rule or "auto")
            if before is not None:
                sp.set(w("before"), str(before))
            if after is not None:
                sp.set(w("after"), str(after))
        if ind_left is not None or ind_first is not None:
            ind = ensure_child(ppr, "ind")
            if ind_left is not None:
                ind.set(w("left"), str(ind_left))
            if ind_first is not None:
                ind.set(w("firstLine"), str(ind_first))

    # Normal
    st = get_style("Normal")
    set_style_rpr(st, TNR, SONG, 21)
    set_style_ppr(st, jc="both", ind_left=None, ind_first=None)

    # Body Text（仅段后 6pt）
    st = get_style("Body Text")
    set_style_rpr(st, TNR, SONG, 21)
    set_style_ppr(st, jc="both", after=120)

    # Heading 1/2/3
    h1 = get_style("Heading 1")
    set_style_rpr(h1, TNR, HEI, 48, bold=True)
    set_style_ppr(h1, jc="left")

    h2 = get_style("Heading 2")
    set_style_rpr(h2, TNR, HEI, 32, bold=True)
    set_style_ppr(h2, jc="left", line=408, line_rule="auto", before=0, after=0)

    h3 = get_style("Heading 3")
    set_style_rpr(h3, TNR, HEI, 27, bold=True)
    set_style_ppr(h3, jc="left")

    # TOC Heading
    th = get_style("TOC Heading")
    set_style_rpr(th, TNR, SONG, 28)
    set_style_ppr(th, before=480, line=276, line_rule="auto")

    # toc 1..9
    toc_specs = {
        "toc 1": dict(bold=True, before=360, after=360),
        "toc 2": dict(bold=True, after=60, line=360, line_rule="auto"),
    }
    for i in range(1, 10):
        name = f"toc {i}"
        st = get_style(name)
        set_style_rpr(st, TNR, SONG, 22, bold=toc_specs.get(name, {}).get("bold", False))
        spec = toc_specs.get(name, {})
        set_style_ppr(st, **{k: v for k, v in spec.items() if k in ("before", "after", "line", "line_rule")})

    # HTML Code
    st = get_style("HTML Code")
    set_style_rpr(st, COURIER, COURIER, 20)


def _style_id(name: str) -> str:
    return name.replace(" ", "").lower()


# ---------------------------------------------------------------------------
# 3) document.xml
# ---------------------------------------------------------------------------
def is_code_cell(cell_text: str) -> bool:
    markers = ("def ", "return ", "import ", "    ", "class ", "=")
    if any(m in cell_text for m in ("def ", "return ", "import ", "class ")):
        return True
    # 多行且含等宽缩进、几乎无中文 → 视为代码
    if "\n" in cell_text and "    " in cell_text and "。" not in cell_text:
        return True
    return False


def run_rpr(r):
    return ensure_child(r, "rPr")


def fix_document(doc_root, para_style_names):
    body = doc_root.find(w("body"))
    body_paras = [el for el in body if el.tag == w("p")]

    def style_name(idx):
        if 0 <= idx < len(para_style_names):
            return para_style_names[idx]
        return None

    # 第一 toc 1 的位置（body 级段落顺序），用于界定封面块
    first_toc1 = None
    for idx, p in enumerate(body_paras):
        if (style_name(idx) or "").startswith("toc"):
            first_toc1 = idx
            break
    if first_toc1 is None:
        first_toc1 = 9999

    def process_para(p, para_index):
        pstyle = style_name(para_index)
        is_heading = bool(pstyle) and pstyle.startswith("Heading")
        is_toc = bool(pstyle) and pstyle.startswith("toc")
        # 封面块：仅标题/副标题/作者行（前 3 个 body 段落）保留原字号；
        # “目录”标题单独作为 TOC Heading 处理
        in_cover = para_index < min(3, first_toc1)
        para_txt = "".join(t.text or "" for t in p.iter(w("t")))
        is_toc_title = para_txt.replace("　", "").replace(" ", "").strip() == "目录"

        ppr = p.find(w("pPr"))
        if ppr is None and (is_heading or is_toc_title or (not is_toc and not in_cover)):
            ppr = etree.SubElement(p, w("pPr"))

        # ---- 段落级 pPr ----
        if ppr is not None:
            if not is_toc:  # 目录段落保留转换器缩进/行距
                ind = ppr.find(w("ind"))
                if ind is not None:
                    ind.getparent().remove(ind)
            if (not is_heading) and (not is_toc):
                sp = ppr.find(w("spacing"))
                if sp is not None:
                    sp.getparent().remove(sp)  # 正文单倍（去掉 1.8 倍）
            if is_heading:
                jc = ensure_child(ppr, "jc")
                jc.set(w("val"), "left")
            elif is_toc_title:
                jc = ensure_child(ppr, "jc")
                jc.set(w("val"), "center")
            elif not is_toc:
                jc = ppr.find(w("jc"))
                if jc is None:
                    jc = etree.SubElement(ppr, w("jc"))
                jc.set(w("val"), "both")

        # ---- run 级 ----
        for r in p.iter(w("r")):
            rpr = run_rpr(r)
            if is_heading:
                set_rfonts(rpr, TNR, HEI)
                lvl = 24
                if pstyle == "Heading 1":
                    lvl = 48
                elif pstyle == "Heading 2":
                    lvl = 32
                elif pstyle == "Heading 3":
                    lvl = 27
                set_sz(rpr, lvl)
                ensure_bold(rpr, True)
            elif is_toc_title:
                set_rfonts(rpr, TNR, HEI)
                set_sz(rpr, 28)
                ensure_bold(rpr, False)
            elif is_toc:
                set_rfonts(rpr, TNR, SONG)
                # sz 由 toc 样式继承（22）
            elif in_cover:
                # 封面：保留原字号与中文字体，仅把英文数字改成 TNR
                set_rfonts(rpr, TNR, _current_ea(rpr) or HEI)
            else:
                set_rfonts(rpr, TNR, SONG)
                set_sz(rpr, 21)

    for idx, p in enumerate(body_paras):
        process_para(p, idx)

    # 再处理表格
    for tbl in body.iter(w("tbl")):
        for cell in tbl.iter(w("tc")):
            # 单元格文本用于判断是否代码
            ctext = "".join(t.text or "" for t in cell.iter(w("t")))
            code = is_code_cell(ctext)
            for p in cell.iter(w("p")):
                for r in p.iter(w("r")):
                    rpr = run_rpr(r)
                    if code:
                        set_rfonts(rpr, COURIER, COURIER)
                        set_sz(rpr, 20)
                    else:
                        set_rfonts(rpr, TNR, SONG)
                        set_sz(rpr, 21)


def _current_ea(rpr):
    rf = rpr.find(w("rFonts"))
    if rf is not None:
        return rf.get(w("eastAsia"))
    return None


# ---------------------------------------------------------------------------
def main():
    src = Path(sys.argv[1])
    backup = src.with_suffix(".bak_align.docx")
    if not backup.exists():
        shutil.copy(src, backup)
        print("已备份到", backup.name)

    print("1) 调整页边距 ...")
    fix_margins(src)

    print("2) 重写 styles.xml ...")
    with zipfile.ZipFile(src) as z:
        styles_xml = z.read("word/styles.xml")
        document_xml = z.read("word/document.xml")

    sroot = etree.fromstring(styles_xml)
    fix_styles(sroot)
    new_styles = etree.tostring(sroot, xml_declaration=True, encoding="UTF-8", standalone=True)

    # 用 python-docx 解析每个 body 段落的真实样式名（正确处理内置 styleId "1"/"2"）
    d_names = docx.Document(str(src))
    para_style_names = [p.style.name if p.style else None for p in d_names.paragraphs]
    print("  body 段落数:", len(para_style_names))

    print("3) 重写 document.xml（字体/行距/缩进）...")
    droot = etree.fromstring(document_xml)
    fix_document(droot, para_style_names)
    new_document = etree.tostring(droot, xml_declaration=True, encoding="UTF-8", standalone=True)

    print("4) 写回 docx ...")
    with zipfile.ZipFile(src, "r") as zin:
        data = {n: zin.read(n) for n in zin.namelist()}
    data["word/styles.xml"] = new_styles
    data["word/document.xml"] = new_document
    tmp = src.with_name(src.stem + "_tmp.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for n, b in data.items():
            zout.writestr(n, b)
    shutil.move(str(tmp), str(src))
    print("完成。", src.name)


if __name__ == "__main__":
    raise SystemExit(main())

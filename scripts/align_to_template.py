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

# 默认字号取自课程模板（半磅）：正文 10.5pt、H1 24pt、H2 16pt、H3 13.5pt
# 可用 --sizes 覆盖，例如 WPS 保存后的值是 --sizes 24:28:24:27（12/14/12/13.5pt）
DEFAULT_SIZES = {"normal": 21, "h1": 48, "h2": 32, "h3": 27}


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


def fix_margins(docx_path: Path):
    d = docx.Document(str(docx_path))
    for sec in d.sections:
        sec.top_margin = Cm(2.44)
        sec.bottom_margin = Cm(2.44)
        sec.left_margin = Cm(2.98)
        sec.right_margin = Cm(2.98)
    d.save(str(docx_path))


def fix_styles(styles_root, sizes=None):
    sizes = sizes or DEFAULT_SIZES
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

    def get_styles_all(name):
        """返回所有同名 style 元素。

        WPS 会把内置样式名小写化（"Heading 1"→"heading 1"，styleId 仍为 2/3/4），
        同时文档里可能另存一份大写名样式，因此按**大小写不敏感**匹配并全部设置，
        否则内置那套仍是 14pt/12pt，后续在 Word 里新输入文字会回退到错误字号。
        """
        key = name.lower()
        out = []
        for st in styles_root.iter(w("style")):
            nm = st.find(w("name"))
            if nm is not None and (nm.get(w("val")) or "").lower() == key:
                out.append(st)
        return out

    def get_style(name):
        out = get_styles_all(name)
        if out:
            return out[0]
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

    st = get_style("Normal")
    set_style_rpr(st, TNR, SONG, sizes["normal"])
    set_style_ppr(st, jc="both", ind_left=None, ind_first=None)

    st = get_style("Body Text")
    set_style_rpr(st, TNR, SONG, sizes["normal"])
    set_style_ppr(st, jc="both", after=120)

    for h1 in get_styles_all("Heading 1"):
        set_style_rpr(h1, TNR, HEI, sizes["h1"], bold=True)
        set_style_ppr(h1, jc="left")

    for h2 in get_styles_all("Heading 2"):
        set_style_rpr(h2, TNR, HEI, sizes["h2"], bold=True)
        set_style_ppr(h2, jc="left", line=408, line_rule="auto", before=0, after=0)

    for h3 in get_styles_all("Heading 3"):
        set_style_rpr(h3, TNR, HEI, sizes["h3"], bold=True)
        set_style_ppr(h3, jc="left")

    for th in get_styles_all("TOC Heading"):
        set_style_rpr(th, TNR, SONG, 28)
        set_style_ppr(th, before=480, line=276, line_rule="auto")

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

    st = get_style("HTML Code")
    set_style_rpr(st, COURIER, COURIER, 20)


def _style_id(name: str) -> str:
    return name.replace(" ", "").lower()


def is_code_cell(cell_text: str) -> bool:
    markers = ("def ", "return ", "import ", "    ", "class ", "=")
    if any(m in cell_text for m in ("def ", "return ", "import ", "class ")):
        return True
    if "\n" in cell_text and "    " in cell_text and "。" not in cell_text:
        return True
    return False


def run_rpr(r):
    return ensure_child(r, "rPr")


def fix_document(doc_root, para_style_names, sizes=None):
    sizes = sizes or DEFAULT_SIZES
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

        for r in p.iter(w("r")):
            rpr = run_rpr(r)
            if is_heading:
                set_rfonts(rpr, TNR, HEI)
                lvl = sizes["h2"]
                if pstyle == "Heading 1":
                    lvl = sizes["h1"]
                elif pstyle == "Heading 2":
                    lvl = sizes["h2"]
                elif pstyle == "Heading 3":
                    lvl = sizes["h3"]
                set_sz(rpr, lvl)
                ensure_bold(rpr, True)
            elif is_toc_title:
                set_rfonts(rpr, TNR, HEI)
                set_sz(rpr, 28)
                ensure_bold(rpr, False)
            elif is_toc:
                set_rfonts(rpr, TNR, SONG)
            elif in_cover:
                # 封面：保留原字号与中文字体，仅把英文数字改成 TNR
                set_rfonts(rpr, TNR, _current_ea(rpr) or HEI)
            else:
                set_rfonts(rpr, TNR, SONG)
                set_sz(rpr, sizes["normal"])

    for idx, p in enumerate(body_paras):
        process_para(p, idx)

    for tbl in body.iter(w("tbl")):
        for cell in tbl.iter(w("tc")):
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
                        set_sz(rpr, sizes["normal"])


def fix_headers_footers(data: dict):
    """页眉/页脚的 run 也要 TNR（西文）+ 宋体（中文），不改字号。"""
    fixed = []
    for name in list(data):
        if not (name.startswith("word/header") or name.startswith("word/footer")):
            continue
        if not name.endswith(".xml"):
            continue
        try:
            root = etree.fromstring(data[name])
        except Exception:
            continue
        n = 0
        for r in root.iter(w("r")):
            rpr = ensure_child(r, "rPr")
            set_rfonts(rpr, TNR, SONG)
            n += 1
        if n:
            data[name] = etree.tostring(root, xml_declaration=True,
                                       encoding="UTF-8", standalone=True)
            fixed.append((name, n))
    return fixed


def fix_theme(data: dict):
    """把主题字体写死为 TNR(西文)/宋体(中文)。

    Word 保存时会把「与主题一致的显式字体」规范化成 asciiTheme=minorHAnsi 之类的
    主题引用，若主题的 ea typeface 为空，中文与数字就会回退到默认字体。写死后
    即使出现主题引用也仍解析为 Times New Roman / 宋体。
    """
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    name = "word/theme/theme1.xml"
    if name not in data:
        return None
    try:
        root = etree.fromstring(data[name])
    except Exception:
        return None
    n = 0
    for tag in ("minorFont", "majorFont"):
        for f in root.iter(A + tag):
            for c in f:
                ln = etree.QName(c).localname
                if ln == "latin":
                    c.set("typeface", TNR)
                    n += 1
                elif ln == "ea":
                    c.set("typeface", SONG)
                    n += 1
                elif ln == "cs":
                    c.set("typeface", TNR)
                    n += 1
    data[name] = etree.tostring(root, xml_declaration=True,
                                encoding="UTF-8", standalone=True)
    return n


def _current_ea(rpr):
    rf = rpr.find(w("rFonts"))
    if rf is not None:
        return rf.get(w("eastAsia"))
    return None


def parse_sizes(argv):
    """--sizes normal:h1:h2:h3（半磅）。默认课程模板值 21:48:32:27。"""
    if "--sizes" not in argv:
        return dict(DEFAULT_SIZES)
    raw = argv[argv.index("--sizes") + 1]
    parts = [int(x) for x in raw.split(":")]
    keys = ("normal", "h1", "h2", "h3")
    return {k: v for k, v in zip(keys, parts)}


def main():
    src = Path(sys.argv[1])
    sizes = parse_sizes(sys.argv)
    print("字号(半磅):", sizes)
    backup = Path("outputs/report_backup") / (src.stem + "_对齐前.docx")
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copy(src, backup)
        print("已备份到", backup.as_posix())

    print("1) 调整页边距 ...")
    fix_margins(src)

    print("2) 重写 styles.xml ...")
    with zipfile.ZipFile(src) as z:
        styles_xml = z.read("word/styles.xml")
        document_xml = z.read("word/document.xml")

    sroot = etree.fromstring(styles_xml)
    fix_styles(sroot, sizes)
    new_styles = etree.tostring(sroot, xml_declaration=True, encoding="UTF-8", standalone=True)

    # 用 python-docx 解析每个 body 段落的真实样式名（正确处理内置 styleId "1"/"2"）
    d_names = docx.Document(str(src))
    para_style_names = [p.style.name if p.style else None for p in d_names.paragraphs]
    print("  body 段落数:", len(para_style_names))

    print("3) 重写 document.xml（字体/行距/缩进）...")
    droot = etree.fromstring(document_xml)
    fix_document(droot, para_style_names, sizes)
    new_document = etree.tostring(droot, xml_declaration=True, encoding="UTF-8", standalone=True)

    print("4) 写回 docx ...")
    with zipfile.ZipFile(src, "r") as zin:
        data = {n: zin.read(n) for n in zin.namelist()}
    data["word/styles.xml"] = new_styles
    data["word/document.xml"] = new_document

    print("5) 主题字体 ...")
    n = fix_theme(data)
    print("   theme1.xml 更新 %s 处" % n)

    print("6) 页眉/页脚字体 ...")
    for name, n in fix_headers_footers(data):
        print("   %s: %d 个 run" % (name, n))
    tmp = src.with_name(src.stem + "_tmp.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for n, b in data.items():
            zout.writestr(n, b)
    shutil.move(str(tmp), str(src))
    print("完成。", src.name)


if __name__ == "__main__":
    raise SystemExit(main())

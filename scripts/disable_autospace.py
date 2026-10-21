# -*- coding: utf-8 -*-
"""关闭 Word 的“中英文/中文与数字之间自动加空格”渲染行为，
并清理页脚“第 N 页”里中西文之间的真实空格 run。

正文里的间距一部分并非真实空格字符，而是 Word 默认开启的
w:autoSpaceDE / w:autoSpaceDN（中西文、中文与数字自动间距）渲染出来的；
把两者在 docDefaults 的 rPrDefault 上显式置为 false，即可让中英文直接相邻。
页脚的“第 _ N _ 页”则由 CSS content 字符串转换而来，空格是真实字符，
需要把仅含空格的 w:r 删掉。

用法：python scripts/disable_autospace.py <docx 路径>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import docx
from docx.oxml.ns import qn
from lxml import etree

W_NS = qn("w:docDefaults").split("}")[0].split("{")[1] + "}"
FOOTER_RE = re.compile(r"/word/footer\d+\.xml$")


def clean_footer_space_runs(doc: docx.Document) -> int:
    """删除各页脚中仅含 ASCII 空格的 w:r（如“第”与 PAGE 域之间的空格）。"""
    removed = 0
    for part in doc.part.package.iter_parts():
        if not FOOTER_RE.search(str(part.partname)):
            continue
        root = part.element
        for r in list(root.iter(qn("w:r"))):
            kids = [k for k in r if k.tag != qn("w:rPr")]
            if len(kids) != 1 or kids[0].tag != qn("w:t"):
                continue
            text = kids[0].text or ""
            if text != "" and text.strip() == "":
                r.getparent().remove(r)
                removed += 1
    return removed


def patch(path: Path) -> int:
    doc = docx.Document(str(path))
    styles = doc.styles.element
    doc_defaults = styles.find(qn("w:docDefaults"))
    if doc_defaults is None:
        doc_defaults = etree.SubElement(styles, qn("w:docDefaults"))
    rpr_default = doc_defaults.find(qn("w:rPrDefault"))
    if rpr_default is None:
        rpr_default = etree.SubElement(doc_defaults, qn("w:rPrDefault"))
    rpr = rpr_default.find(qn("w:rPr"))
    if rpr is None:
        rpr = etree.SubElement(rpr_default, qn("w:rPr"))

    added = 0
    for tag in ("w:autoSpaceDE", "w:autoSpaceDN"):
        node = rpr.find(qn(tag))
        if node is None:
            node = etree.SubElement(rpr, qn(tag))
            added += 1
        node.set(qn("w:val"), "false")

    # 逐 run 覆盖：个别 run 若自带 autoSpace 设定会盖过 docDefaults
    for run in doc.element.body.iter(qn("w:rPr")):
        for tag in ("w:autoSpaceDE", "w:autoSpaceDN"):
            node = run.find(qn(tag))
            if node is not None:
                node.set(qn("w:val"), "false")
                added += 1

    removed = clean_footer_space_runs(doc)

    doc.save(str(path))
    print(f"{path.name}: 写入/更新 autoSpaceDE/autoSpaceDN = false（{added} 处），"
          f"清理页脚空格 run {removed} 个")
    return added


def main() -> int:
    if len(sys.argv) != 2:
        print("用法：python scripts/disable_autospace.py <docx 路径>")
        return 2
    patch(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""关闭 Word 的“中英文/中文与数字之间自动加空格”渲染行为。

正文里的间距并非真实空格字符，而是 Word 与腾讯文档预览默认开启的
w:autoSpaceDE / w:autoSpaceDN（中西文、中文与数字自动间距）渲染出来的。
把两者在 docDefaults 的 rPrDefault 上显式置为 false，即可让中英文直接相邻。

用法：python scripts/disable_autospace.py <docx 路径>
"""

from __future__ import annotations

import sys
from pathlib import Path

import docx
from docx.oxml.ns import qn
from lxml import etree

W_NS = qn("w:docDefaults").split("}")[0].split("{")[1] + "}"


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

    doc.save(str(path))
    print(f"{path.name}: 写入/更新 autoSpaceDE/autoSpaceDN = false（{added} 处）")
    return added


def main() -> int:
    if len(sys.argv) != 2:
        print("用法：python scripts/disable_autospace.py <docx 路径>")
        return 2
    patch(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

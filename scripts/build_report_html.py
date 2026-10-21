# -*- coding: utf-8 -*-
"""从 docs/report_draft.md 重建 Word 排版用的 stage2 HTML。

复用既有版式的 <head>、CSS（含 @page 页脚）与封面，正文按 report_draft.md
重新生成，目录由标题自动构建。这样报告正文改动后，Word 版可以同步更新，
而不必重跑整套排版流水线。

用法：
    python scripts/build_report_html.py

输出：
    output/c5-report-word-20261021/stage2/formatted-城市电力负荷分析与预测_rebuilt.html
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "docs" / "report_draft.md"
STAGE2 = ROOT / "output" / "c5-report-word-20261021" / "stage2"
OLD_HTML = STAGE2 / "formatted-城市电力负荷分析与预测.html"
DST = STAGE2 / "formatted-城市电力负荷分析与预测_rebuilt.html"

DROP_SECTIONS = ("待解决清单",)  # 内部核对清单，不进正式报告

IDEO_SPACE = "　"

# 中文（含全角标点）与英文/数字之间的空格一律删除（用户要求）
_CJK = r"\u4e00-\u9fff\u3001-\u303f\uff00-\uffef"
_ALNUM = r"A-Za-z0-9"
# 加粗占位符（\x00）与 <b>/</b> 标签对空格剥离透明：
# "同源。** 2." 转 <b> 后空格夹在 > 与 < 之间，不透明就逃过剥离
_TOKEN = r"(?:\x00|</?b>)"


def strip_cjk_spaces(text: str) -> str:
    """删除中文与英文/数字之间的 ASCII 空格，保留全角空格与英文之间的空格。
    加粗标记/标签两侧同样处理（标记不是可见字符，不阻挡中西文相邻判定）。
    注意：匹配时把标记原样插回（\\1\\2），只删空格本身——若连标记一起删掉，
    ** 占位符会被吃掉，加粗配对错位，文档里留下残留星号。"""
    text = re.sub(rf"(?<=[{_CJK}])({_TOKEN}*) +({_TOKEN}*)(?=[{_ALNUM}])", r"\1\2", text)
    text = re.sub(rf"(?<=[{_ALNUM}])({_TOKEN}*) +({_TOKEN}*)(?=[{_CJK}])", r"\1\2", text)
    return text


def strip_md(text: str) -> str:
    """markdown 行内文本：把 ** 换成占位符后再剥离中西文空格，最后还原。
    必须在加粗转换之前调用，否则标记两侧的空格会因标签阻隔而漏删。"""
    return strip_cjk_spaces(text.replace("**", "\x00")).replace("\x00", "**")


def fmt_heading(text: str) -> str:
    """标题排版：数字编号后改用全角空格；摘要两字拉开。"""
    text = strip_cjk_spaces(text)
    if text == "摘要":
        return "摘" + IDEO_SPACE + "要"
    m = re.match(r"^(\d+(?:\.\d+)?)(.+)$", text)
    if m:
        return m.group(1) + IDEO_SPACE + m.group(2)
    m = re.match(r"^(附录[A-Z])(.+)$", text)
    if m:
        return m.group(1) + IDEO_SPACE + m.group(2)
    return text


def inline(text: str) -> str:
    """行内标记：反引号去符号，双星号转 <b>；中英文/数字间空格删除。"""
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # 先删中西文空格（** 两侧透明）再转 <b>：否则 "同源。** 2." 变
    # "同源。</b> <b>2." 后，空格夹在 > 与 < 之间，不再是中文与数字相邻，会逃过剥离
    text = strip_md(text)
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return strip_cjk_spaces(text)


def md_table(rows: list[list[str]]) -> str:
    head = "".join(f"<th>{inline(c.strip())}</th>" for c in rows[0])
    body = []
    for r in rows[1:]:
        body.append("<tr>" + "".join(f"<td>{inline(c.strip())}</td>" for c in r) + "</tr>")
    return "<table>\n<tr>" + head + "</tr>\n" + "\n".join(body) + "\n</table>"


def parse(md_text: str) -> tuple[list[dict], list[str]]:
    """把 markdown 解析为章节列表；同时返回目录条目（HTML 片段）。"""
    lines = md_text.split("\n")
    chapters: list[dict] = []
    cur: dict | None = None
    buf: list[str] = []
    skip = False

    def flush_para() -> None:
        nonlocal buf
        if cur is None:
            buf = []
            return
        text = " ".join(x.strip() for x in buf).strip()
        buf = []
        if not text:
            return
        target = cur["sections"][-1]["blocks"] if cur["sections"] else cur["blocks"]
        if text.startswith("**关键词：**") or text.startswith("关键词："):
            rest = text.split("：", 1)[1] if "：" in text else ""
            rest = rest.strip().lstrip("*").strip()  # 去掉 markdown 加粗的残留星号
            target.append(f'<p><span class="kw">关键词：</span>{inline(rest)}</p>')
        else:
            target.append(f'<p class="body-text">{inline(text)}</p>')

    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.startswith("## "):
            flush_para()
            title = line[3:].strip()
            skip = any(title.startswith(d) for d in DROP_SECTIONS)
            if skip:
                continue
            cur = {"title": title, "sections": [], "blocks": []}
            chapters.append(cur)
            continue
        if skip:
            continue
        if line.startswith("### "):
            flush_para()
            cur["sections"].append({"title": line[4:].strip(), "blocks": []})
            continue
        if cur is None:
            continue  # 文档标题与前言块引用，正文从这里之前一律跳过
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_para()
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # 跳过收尾的 ```
            esc = "\n".join(code).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            # 代码注释/字符串里的中西文空格同样删除（Python 语法空格均为 ASCII 间空格，不受影响）
            esc = strip_cjk_spaces(esc)
            target = cur["sections"][-1]["blocks"] if cur["sections"] else cur["blocks"]
            target.append(f'<pre class="code">{esc}</pre>')
            continue
        if not stripped:
            flush_para()
            continue
        if stripped.startswith("# ") or stripped == "---" or stripped.startswith("> "):
            continue
        m = re.match(r"^（此处插入(.+?)）$", stripped)
        if m:
            flush_para()
            target = cur["sections"][-1]["blocks"] if cur["sections"] else cur["blocks"]
            target.append(f'<div class="fig-ph">（此处插入{m.group(1)}）</div>')
            continue
        if stripped.startswith("|"):
            flush_para()
            rows = []
            while i <= len(lines) and lines[i - 1].strip().startswith("|"):
                raw = lines[i - 1].strip().strip("|")
                cells = raw.split("|")
                if not all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in cells):
                    rows.append(cells)
                i += 1
            target = cur["sections"][-1]["blocks"] if cur["sections"] else cur["blocks"]
            target.append(md_table(rows))
            continue
        buf.append(stripped)
    flush_para()
    return chapters, []


def build_toc(chapters: list[dict]) -> str:
    items = []
    for n, ch in enumerate(chapters, start=1):
        title = fmt_heading(ch["title"])
        if ch["sections"]:
            sub = "\n".join(
                f'        <li><a href="#section-{n}-{m}">{fmt_heading(s["title"])}</a></li>'
                for m, s in enumerate(ch["sections"], start=1)
            )
            items.append(
                f'    <li><a href="#section-{n}">{title}</a>\n      <ol>\n{sub}\n      </ol>\n    </li>'
            )
        else:
            items.append(f'    <li><a href="#section-{n}">{title}</a></li>')
    return (
        '<nav class="doc-toc" aria-label="文档目录">\n'
        '  <p class="toc-title">目　录</p>\n'
        '  <ol class="toc-list">\n'
        + "\n".join(items)
        + "\n  </ol>\n</nav>"
    )


def build_body(chapters: list[dict]) -> str:
    out = []
    for n, ch in enumerate(chapters, start=1):
        attrs = ' class="chapter" data-page-restart="1"' if n == 1 else ' class="chapter"'
        out.append(f"<section{attrs}>")
        out.append(f'<h1 id="section-{n}">{fmt_heading(ch["title"])}</h1>')
        if n == 1:  # 摘要块
            out.append('<div class="abstract-block">')
            out.extend(ch["blocks"])
            out.append("</div>")
        else:
            out.extend(ch["blocks"])
        for m, sec in enumerate(ch["sections"], start=1):
            out.append(f'<h2 id="section-{n}-{m}">{fmt_heading(sec["title"])}</h2>')
            out.extend(sec["blocks"])
        out.append("</section>\n")
    return "\n".join(out) + "\n"


def main() -> None:
    old = OLD_HTML.read_text(encoding="utf-8")
    head = old.split('<nav class="doc-toc"', 1)[0]
    # 页脚字符串同样去掉中西文间空格，与全文口径一致（"第 N 页" → "第N页"）
    head = head.replace(
        'content: "第 " counter(page) " 页";',
        'content: "第" counter(page) "页";',
    )
    # 封面等 markup 删除中西文/数字间空格；CSS 选择器与属性均为 ASCII，不受影响
    head = strip_cjk_spaces(head)
    chapters, _ = parse(MD.read_text(encoding="utf-8"))

    # head 已包含封面段与第二个 <section role="cover"> 的开头（目录独占一节）
    html = (
        head
        + build_toc(chapters)
        + "\n</section>\n\n"
        + build_body(chapters)
        + "\n</body>\n</html>\n"
    )
    DST.write_text(html, encoding="utf-8")
    n_sec = sum(len(c["sections"]) for c in chapters)
    print(f"章节 {len(chapters)} 个，小节 {n_sec} 个")
    print(f"已写出：{DST}  ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""删除代码中的冗余注释，只保留极少数必要注释（幂等）。

用 tokenize 识别真正的 COMMENT token，因此不会误伤字符串里的 "#"（颜色码、URL、
f-string 里的井号）。

保留规则：
  1. shebang / coding 声明
  2. lint 指令：noqa、type:、pragma、pylint、mypy
  3. 口径/约束/非显然逻辑类注释（关键词白名单，见 KEEP_KEYWORDS）

用法：
  python scripts/strip_comments.py            # 预演，只打印将删除的注释
  python scripts/strip_comments.py --apply    # 实际写入
"""
from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

TARGETS = ["src/*.py", "tests/*.py", "scripts/*.py"]

LINT = ("noqa", "type:", "pragma", "pylint", "mypy", "flake8")

# 只有涉及"口径 / 防泄漏 / 单位 / 约束 / 易错点"的注释才留下
KEEP_KEYWORDS = (
    "口径", "防泄漏", "泄漏", "purge", "PURGE", "未来", "回溯", "窗口", "剔除",
    "目标时刻", "目标值", "同期", "1002", "1008", "FORECAST_HORIZON", "NAIVE_LAG",
    "MSE", "RMSE", "单位", "量纲", "摄氏度", "℃", "小时", "时间步", "对齐",
    "必须", "务必", "禁止", "不要", "不可", "不能", "保证", "避免",
    "注意", "警告", "TODO", "FIXME", "WARNING",
    "假设", "协议", "约定", "定义", "退化",
    "只读", "不修改", "不删除", "不覆盖", "不参与", "不消费",
    "课程", "报告", "评分",
    "阈值", "编码", "无界面", "晚高峰", "高负荷", "精度", "容差", "漂移", "版本",
    "周一", "工作日", "周末", "测试期", "片段", "分箱",
    "基线", "验证集", "测试集", "训练集",
    "唯一", "默认", "同源", "可复现", "幂等",
    "WPS", "Word", "主题", "theme", "域", "保存", "docx", "docDefaults", "autoSpace",
    "起点", "用户", "不受影响", "一律", "封面", "正文", "目录",
)


def should_keep(text: str, row: int) -> bool:
    if row == 1 and text.startswith("#!"):
        return True
    if "coding" in text:
        return True
    low = text.lower()
    if any(k in low for k in LINT):
        return True
    return any(k in text for k in KEEP_KEYWORDS)


def process(path: Path, apply: bool):
    data = path.read_bytes()
    try:
        toks = list(tokenize.tokenize(io.BytesIO(data).readline))
    except Exception as exc:  # 语法无法解析则跳过
        print("  跳过（无法解析）: %s" % exc)
        return 0, []
    lines = data.decode("utf-8").splitlines(keepends=True)

    edits, removed_text = [], []
    for t in toks:
        if t.type != tokenize.COMMENT:
            continue
        row, col = t.start
        if should_keep(t.string, row):
            continue
        edits.append((row, col))
        removed_text.append((row, t.string.strip()))

    for row, col in sorted(edits, reverse=True):
        ln = lines[row - 1]
        new = ln[:col].rstrip()
        if not new.strip():
            lines[row - 1] = None
        else:
            lines[row - 1] = new + ("\n" if ln.endswith("\n") else "")

    out = "".join(l for l in lines if l is not None)
    # 连续空行最多保留 2 行
    out = re.sub(r"\n{4,}", "\n\n\n", out)

    if apply and removed_text:
        # 必须用二进制写入：write_text 在 Windows 上会把 \n 再转成 \r\n，
        # 原文件已是 CRLF 时会变成 \r\r\n（每行后多出一个空行）
        path.write_bytes(out.encode("utf-8"))
    return len(removed_text), removed_text


def main() -> int:
    apply = "--apply" in sys.argv
    total = 0
    for pat in TARGETS:
        for p in sorted(Path(".").glob(pat)):
            if p.name == "strip_comments.py":
                continue
            n, removed = process(p, apply)
            total += n
            flag = "写入" if apply else "预演"
            print("%-34s %s 删除 %d 处" % (p.as_posix(), flag, n))
            if not apply:
                for row, txt in removed[:200]:
                    print("      L%-4d %s" % (row, txt[:72]))
    print("\n合计 %d 处%s" % (total, "（已写入）" if apply else "（未写入，加 --apply 生效）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

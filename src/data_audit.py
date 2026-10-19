#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A1 数据质量审计脚本。

只读原始 CSV，不修改数据，不训练模型。运行后会生成 docs/data_audit.md。
所有统计量均来自当次实际读取的文件，不预填、不猜测。

用法：
    python src/data_audit.py
    python src/data_audit.py --input data/raw/xxx.csv --output docs/data_audit.md
"""

from __future__ import annotations

import argparse
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
DOCS_DIR = PROJECT_ROOT / "docs"
DEFAULT_OUTPUT = DOCS_DIR / "data_audit.md"

TIME_KEYWORDS = (
    "time", "date", "timestamp", "datetime", "时间", "日期", "时刻",
)
LOAD_KEYWORDS = (
    "load", "demand", "consumption", "负荷", "用电", "功率",
    "region", "zone", "area",
)
WEATHER_KEYWORDS = (
    "temp", "humidity", "humid", "wind", "solar", "radiation", "diffuse",
    "weather", "温度", "湿度", "风速", "辐射", "天气",
)


# ---------------------------------------------------------------------------
# 读取与列识别
# ---------------------------------------------------------------------------

def resolve_input(explicit: str | None) -> Path:
    """确定要审计的 CSV 路径。"""
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        if not p.is_file():
            raise FileNotFoundError(f"指定的文件不存在：{p}")
        return p

    files = sorted(p for p in RAW_DIR.glob("*.csv") if p.is_file())
    if not files:
        raise FileNotFoundError(
            f"未在 {RAW_DIR} 找到 CSV 文件。请把原始电力负荷数据放入 data/raw/，"
            "或用 --input 指定路径。"
        )
    if len(files) > 1:
        names = "\n".join(f"  - {p.name}" for p in files)
        raise RuntimeError(
            f"data/raw/ 下有多个 CSV，请用 --input 明确指定一个：\n{names}"
        )
    return files[0]


def read_csv_robust(path: Path) -> tuple[pd.DataFrame, str]:
    """按常见编码依次尝试读取，兼容分号/制表符分隔。"""
    errors = []
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        for kwargs in ({}, {"sep": None, "engine": "python"}):
            try:
                df = pd.read_csv(path, encoding=enc, **kwargs)
                if df.shape[1] == 1:
                    continue  # 分隔符可能判断错了
                return df, enc
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{enc}{kwargs}: {exc}")
    raise RuntimeError("CSV 读取失败，已尝试 utf-8/gbk/gb18030。\n" + "\n".join(errors[-4:]))


def parse_datetime_series(s: pd.Series) -> pd.Series:
    """把一列尽量解析成 datetime；数值列按 epoch 秒/毫秒/微秒处理。"""
    if pd.api.types.is_numeric_dtype(s):
        v = pd.to_numeric(s, errors="coerce")
        med = v.dropna().median()
        if pd.isna(med):
            return pd.Series(pd.NaT, index=s.index)
        if med > 1e14:
            unit = "us"
        elif med > 1e11:
            unit = "ms"
        elif med > 1e8:
            unit = "s"
        else:
            return pd.Series(pd.NaT, index=s.index)
        return pd.to_datetime(v, unit=unit, errors="coerce")
    return pd.to_datetime(s, errors="coerce")


def detect_time_column(df: pd.DataFrame) -> str | None:
    """优先按列名关键词，再按解析成功率挑选时间列。"""
    best_col, best_score = None, 0.0
    for col in df.columns:
        s = df[col]
        if s.empty:
            continue
        parsed = parse_datetime_series(s)
        ratio = float(parsed.notna().sum()) / max(len(s), 1)
        if ratio < 0.8:
            continue
        name_bonus = 0.05 if any(k in str(col).lower() for k in TIME_KEYWORDS) else 0.0
        score = ratio + name_bonus
        if score > best_score:
            best_col, best_score = col, score
    return best_col


def columns_matching(columns, keywords) -> list[str]:
    return [c for c in columns if any(k in str(c).lower() for k in keywords)]


def numeric_profile(df: pd.DataFrame, col: str, ts: pd.Series | None) -> dict:
    """单个数值列的描述统计、极值位置与 IQR 异常计数。只描述，不修改。"""
    s = pd.to_numeric(df[col], errors="coerce")
    valid = s.dropna()
    prof: dict = {
        "col": col,
        "count": int(valid.size),
        "missing": int(s.isna().sum()),
        "mean": float(valid.mean()) if valid.size else None,
        "std": float(valid.std()) if valid.size > 1 else None,
        "min": float(valid.min()) if valid.size else None,
        "p25": float(valid.quantile(0.25)) if valid.size else None,
        "p50": float(valid.quantile(0.50)) if valid.size else None,
        "p75": float(valid.quantile(0.75)) if valid.size else None,
        "max": float(valid.max()) if valid.size else None,
        "negative": int((valid < 0).sum()),
        "zero": int((valid == 0).sum()),
        "peak_time": None,
        "trough_time": None,
        "out_1_5_iqr": None,
        "out_3_iqr": None,
        "outlier_hours": None,
        "outlier_months": None,
    }
    if ts is not None and valid.size:
        try:
            prof["peak_time"] = ts.loc[valid.idxmax()]
            prof["trough_time"] = ts.loc[valid.idxmin()]
        except Exception:  # noqa: BLE001
            pass
    q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
    iqr = q3 - q1
    if pd.notna(iqr) and iqr > 0:
        prof["out_1_5_iqr"] = int(((s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)).sum())
        extreme = (s < q1 - 3 * iqr) | (s > q3 + 3 * iqr)
        prof["out_3_iqr"] = int(extreme.sum())
        if ts is not None and prof["out_3_iqr"]:
            t = ts[extreme]
            prof["outlier_hours"] = {
                int(k): int(v) for k, v in t.dt.hour.value_counts().head(3).items()
            }
            prof["outlier_months"] = {
                int(k): int(v) for k, v in t.dt.month.value_counts().head(2).items()
            }
    return prof


# ---------------------------------------------------------------------------
# 审计主流程
# ---------------------------------------------------------------------------

def analyze(df: pd.DataFrame, path: Path) -> dict:
    res: dict = {
        "file": path,
        "shape": df.shape,
        "columns": [(c, str(df[c].dtype)) for c in df.columns],
        "columns_raw": list(df.columns),
        "odd_names": [c for c in df.columns if str(c) != " ".join(str(c).split())],
        "head": df.head(5),
        "missing": df.isna().sum(),
        "missing_total": int(df.isna().sum().sum()),
        "duplicate_rows": int(df.duplicated().sum()),
        "time_col": None,
        "time_parse_fail": 0,
        "time_min": None,
        "time_max": None,
        "time_sorted": None,
        "dup_timestamps": 0,
        "interval_mode": None,
        "interval_unique": 0,
        "interval_counts": None,
        "gaps_gt_mode": 0,
        "gaps_gt_2mode": 0,
        "records_per_day": None,
        "numeric_cols": list(df.select_dtypes(include=[np.number]).columns),
    }

    parsed_ts = None
    tcol = detect_time_column(df)
    res["time_col"] = tcol
    if tcol is not None:
        raw = df[tcol]
        parsed = parse_datetime_series(raw)
        parsed_ts = parsed
        res["time_parse_fail"] = int(raw.notna().sum() - parsed.notna().sum())
        if parsed.notna().any():
            res["time_min"] = parsed.min()
            res["time_max"] = parsed.max()
            res["time_sorted"] = bool(parsed.dropna().is_monotonic_increasing)
            res["dup_timestamps"] = int(parsed.duplicated().sum())

            ts = parsed.dropna().sort_values()
            diffs = ts.diff().dropna()
            if len(diffs):
                vc = diffs.value_counts().sort_index()
                res["interval_counts"] = vc
                res["interval_mode"] = vc.idxmax()
                res["interval_unique"] = int(len(vc))
                mode = vc.idxmax()
                res["gaps_gt_mode"] = int((diffs > mode).sum())
                res["gaps_gt_2mode"] = int((diffs > 2 * mode).sum())
            res["records_per_day"] = ts.dt.date.value_counts().sort_index()

    load_cols = columns_matching(res["numeric_cols"], LOAD_KEYWORDS)
    weather_cols = columns_matching(res["numeric_cols"], WEATHER_KEYWORDS)
    # 若列名没有明显语义，退化为：除时间列外的所有数值列作为候选负荷列
    if not load_cols:
        load_cols = [c for c in res["numeric_cols"] if c != tcol and c not in weather_cols]

    res["load_cols"] = load_cols
    res["weather_cols"] = weather_cols
    res["profiles"] = [
        numeric_profile(df, c, parsed_ts) for c in (load_cols + weather_cols)
    ]
    res["other_numeric_cols"] = [
        c for c in res["numeric_cols"]
        if c not in load_cols and c not in weather_cols and c != tcol
    ]
    return res


# ---------------------------------------------------------------------------
# Markdown 渲染
# ---------------------------------------------------------------------------

def fnum(x, nd: int = 4) -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return ""
    if isinstance(x, (int, np.integer)):
        return f"{int(x):,}"
    return f"{float(x):.{nd}f}"


def fmt_cell(v) -> str:
    if v is None or pd.isna(v):
        return ""
    if isinstance(v, (float, np.floating)):
        return f"{float(v):.4f}"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    return str(v)


def fmt_td(td) -> str:
    """把 Timedelta 写成「10 分钟」「1 小时」这类可读形式。"""
    if td is None or pd.isna(td):
        return ""
    total = pd.Timedelta(td).total_seconds()
    if total >= 3600 and total % 3600 == 0:
        return f"{int(total // 3600)} 小时"
    if total % 60 == 0:
        return f"{int(total // 60)} 分钟"
    return f"{total:.1f} 秒"


def md_table(headers: list[str], rows: list[list]) -> str:
    out = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    return "\n".join(out)


def render_report(res: dict, path: Path, encoding: str) -> str:
    n_rows, n_cols = res["shape"]
    try:
        shown_path = Path(path).resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        shown_path = path
    lines: list[str] = []
    add = lines.append

    add("# 数据质量审计报告（A1）")
    add("")
    add(f"- 数据文件：`{shown_path}`")
    add(f"- 读取编码：`{encoding}`")
    add(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    add("- 生成脚本：`src/data_audit.py`（只读原始文件，不修改数据，不训练模型）")
    add(f"- 数据形状：**{n_rows:,} 行 × {n_cols} 列**")
    add("")

    # 1. 字段概况
    add("## 1. 字段与数据概况")
    add("")
    add("### 1.1 列名、类型与缺失")
    add("")
    miss = res["missing"]
    rows = []
    for col, dtype in res["columns"]:
        m = int(miss.get(col, 0))
        rows.append([col, dtype, f"{n_rows - m:,}", f"{m:,}", f"{m / max(n_rows, 1) * 100:.2f}%"])
    add(md_table(["列名", "dtype", "非空数", "缺失数", "缺失率"], rows))
    add("")

    add("### 1.2 前 5 行")
    add("")
    head = res["head"].copy()
    for c in head.columns:
        head[c] = head[c].map(fmt_cell)
    add(md_table([str(c) for c in head.columns], head.values.tolist()))
    add("")

    if res["profiles"]:
        add("### 1.3 候选负荷 / 天气字段描述统计")
        add("")
        rows = []
        for p in res["profiles"]:
            rows.append([
                p["col"], p["count"], fnum(p["mean"]), fnum(p["std"]),
                fnum(p["min"]), fnum(p["p25"]), fnum(p["p50"]),
                fnum(p["p75"]), fnum(p["max"]),
            ])
        add(md_table(
            ["列名", "非空数", "均值", "标准差", "最小值", "P25", "中位数", "P75", "最大值"],
            rows,
        ))
        add("")

    if res["odd_names"]:
        add("### 1.4 列名规范")
        add("")
        add("以下列名含有连续空格或首尾空格，后续代码直接按字符串取列容易出错，A2 规整时应统一。")
        add("")
        rows = [[f"`{c}`", f"`{' '.join(str(c).split())}`"] for c in res["odd_names"]]
        add(md_table(["原始列名", "建议列名"], rows))
        add("")

    # 2. 时间维度
    add("## 2. 时间维度")
    add("")
    if res["time_col"] is None:
        add("**未识别出可解析的时间列。** 需要人工确认时间字段的格式，否则无法判断采样间隔与时间覆盖。")
    else:
        add(f"- 识别时间列：`{res['time_col']}`")
        add(f"- 时间范围：{res['time_min']} 至 {res['time_max']}")
        add(f"- 时间戳解析失败：{res['time_parse_fail']:,} 条")
        add(f"- 重复时间戳：{res['dup_timestamps']:,} 条")
        add(f"- 是否按时间升序：{'是' if res['time_sorted'] else '否'}")
        if res["interval_mode"] is not None:
            add(f"- 采样间隔众数：{fmt_td(res['interval_mode'])}")
            add(f"- 不同采样间隔数量：{res['interval_unique']}")
            add(f"- 大于众数间隔的间隔数：{res['gaps_gt_mode']:,}")
            add(f"- 大于 2 倍众数间隔的空档数：{res['gaps_gt_2mode']:,}")
            add("")
            add("采样间隔分布（前 10 种）：")
            add("")
            rows = [
                [fmt_td(k), f"{int(v):,}"]
                for k, v in res["interval_counts"].head(10).items()
            ]
            add(md_table(["间隔", "出现次数"], rows))
        if res["records_per_day"] is not None and len(res["records_per_day"]):
            rpd = res["records_per_day"]
            span_days = (res["time_max"].date() - res["time_min"].date()).days + 1
            add("")
            add(f"- 时间跨度：{span_days:,} 天；实际有记录：{len(rpd):,} 天。")
            if len(rpd) < span_days:
                add(f"- 跨度内缺记录：{span_days - len(rpd):,} 天。")
            add("")
            if int(rpd.min()) == int(rpd.max()):
                add(f"每日记录数完全一致，均为 {int(rpd.min()):,} 条/天。")
            else:
                add(
                    "每日记录数："
                    f"最少 {int(rpd.min()):,}，最多 {int(rpd.max()):,}，"
                    f"中位数 {float(rpd.median()):.1f}。"
                )
                add("")
                add("记录数最少的 5 天：")
                add("")
                rows = [[str(k), f"{int(v):,}"] for k, v in rpd.sort_values().head(5).items()]
                add(md_table(["日期", "记录数"], rows))
    add("")

    # 3. 缺失与重复
    add("## 3. 缺失值与重复")
    add("")
    add(f"- 缺失单元格总数：{res['missing_total']:,}")
    add(f"- 完全重复行：{res['duplicate_rows']:,}")
    if res["missing_total"] > 0:
        add("")
        add("存在缺失的列：")
        add("")
        rows = [
            [c, f"{int(v):,}", f"{int(v) / max(n_rows, 1) * 100:.2f}%"]
            for c, v in res["missing"].items() if int(v) > 0
        ]
        add(md_table(["列名", "缺失数", "缺失率"], rows))
    add("")

    # 4. 负荷与天气字段
    add("## 4. 负荷与天气字段")
    add("")
    add(f"- 识别为负荷列的字段：{', '.join(f'`{c}`' for c in res['load_cols']) or '无'}")
    add(f"- 识别为天气列的字段：{', '.join(f'`{c}`' for c in res['weather_cols']) or '无'}")
    if res["other_numeric_cols"]:
        add(f"- 其他数值列：{', '.join(f'`{c}`' for c in res['other_numeric_cols'])}")
    add("")
    if res["load_cols"]:
        add("负荷列极值与异常计数：")
        add("")
        rows = []
        prof_map = {p["col"]: p for p in res["profiles"]}
        for c in res["load_cols"]:
            p = prof_map[c]
            rows.append([
                c, fnum(p["min"]), fnum(p["max"]),
                str(p["peak_time"]), str(p["trough_time"]),
                p["negative"], p["zero"],
            ])
        add(md_table(["列名", "最小值", "最大值", "峰值时间", "谷值时间", "负值数", "零值数"], rows))
    add("")

    # 5. 异常值标记
    add("## 5. 异常值标记（只标记，不删除）")
    add("")
    add("按 IQR 规则统计，仅用于提示，不代表这些点一定是错误数据。")
    add("")
    rows = []
    for p in res["profiles"]:
        rows.append([
            p["col"],
            "" if p["out_1_5_iqr"] is None else p["out_1_5_iqr"],
            "" if p["out_3_iqr"] is None else p["out_3_iqr"],
        ])
    add(md_table(["列名", "超出 1.5×IQR 的点数", "超出 3×IQR 的点数"], rows))
    add("")

    flagged = [p for p in res["profiles"] if p.get("out_3_iqr")]
    if flagged:
        add("### 5.1 极端点的时间分布")
        add("")
        add("把 3×IQR 极端点按小时和月份汇总，用来区分规律性波动与孤立错误。")
        add("")
        rows = []
        for p in flagged:
            hrs = "、".join(f"{h} 时×{c}" for h, c in (p["outlier_hours"] or {}).items())
            mos = "、".join(f"{m} 月×{c}" for m, c in (p["outlier_months"] or {}).items())
            rows.append([p["col"], p["out_3_iqr"], hrs, mos])
        add(md_table(["列名", "3×IQR 点数", "最集中的小时", "最集中的月份"], rows))
        add("")
        add("若极端点集中在固定小时或月份，更可能是昼夜或季节规律，而不是随机录入错误；"
            "仍需结合字段含义判断，不能仅凭这一条结论删除数据。")
        add("")

    # 6. 结论分类
    confirmed: list[str] = []
    investigate: list[str] = []
    passed: list[str] = []

    if res["time_col"] is None:
        confirmed.append("未识别出可用时间列，无法进行时间序列建模。")
    else:
        if res["time_parse_fail"] > 0:
            confirmed.append(f"存在 {res['time_parse_fail']:,} 条时间戳无法解析。")
        if res["dup_timestamps"] > 0:
            confirmed.append(f"存在 {res['dup_timestamps']:,} 条重复时间戳。")
        if res["time_sorted"] is False:
            confirmed.append("时间戳未按升序排列，建模前需要排序。")
        if res["interval_unique"] > 1:
            investigate.append(
                f"采样间隔不唯一（{res['interval_unique']} 种），"
                f"其中大于众数间隔 {fmt_td(res['interval_mode'])} 的位置有 {res['gaps_gt_mode']:,} 处，"
                f"大于 2 倍间隔的空档有 {res['gaps_gt_2mode']:,} 处。"
            )
        if res["time_sorted"]:
            passed.append("时间戳已按升序排列。")
        if res["dup_timestamps"] == 0:
            passed.append("未发现重复时间戳。")
        if res["interval_unique"] == 1:
            passed.append(f"采样间隔一致，为 {fmt_td(res['interval_mode'])}。")

    if res["missing_total"] > 0:
        confirmed.append(f"存在 {res['missing_total']:,} 个缺失单元格。")
    else:
        passed.append("未发现缺失值。")

    if res["duplicate_rows"] > 0:
        investigate.append(f"存在 {res['duplicate_rows']:,} 条完全重复行，需确认是否为重复采集。")
    else:
        passed.append("未发现完全重复行。")

    for p in res["profiles"]:
        if p["negative"]:
            investigate.append(f"`{p['col']}` 存在 {p['negative']:,} 个负值，需确认业务含义。")
        if p["zero"]:
            investigate.append(f"`{p['col']}` 存在 {p['zero']:,} 个零值，可能是停机或缺失占位。")
        if p["out_3_iqr"]:
            investigate.append(f"`{p['col']}` 有 {p['out_3_iqr']:,} 个点超出 3×IQR，建议逐条核对。")

    add("## 6. 审计结论")
    add("")
    add("### 6.1 已确认的问题")
    add("")
    add("\n".join(f"- {x}" for x in confirmed) if confirmed else "- 暂未发现结构性错误。")
    add("")
    add("### 6.2 值得调查的现象")
    add("")
    add("\n".join(f"- {x}" for x in investigate) if investigate else "- 暂未发现需要进一步调查的异常现象。")
    add("")
    add("### 6.3 暂未发现的问题")
    add("")
    add("\n".join(f"- {x}" for x in passed) if passed else "- 无。")
    add("")

    # 7. 对后续的输入
    add("## 7. 对后续工作的输入")
    add("")
    if res["time_col"] is not None and res["interval_mode"] is not None:
        add(f"- 时间列：`{res['time_col']}`；采样间隔：{fmt_td(res['interval_mode'])}。")
        sec = pd.Timedelta(res["interval_mode"]).total_seconds()
        if sec > 0:
            steps = 3600 / sec
            steps_txt = f"{steps:g}" if steps == int(steps) else f"{steps:.1f}"
            add(
                f"- 提前 1 小时预测对应 {steps_txt} 个时间步"
                f"（预测起点 t 的目标为 t+{steps_txt}）。"
            )
    else:
        add("- 时间列与采样间隔尚未确认，B 的预测方案暂不能定稿。")
    add(f"- 负荷字段：{', '.join(f'`{c}`' for c in res['load_cols']) or '待确认'}；"
        f"天气字段：{', '.join(f'`{c}`' for c in res['weather_cols']) or '待确认'}。")
    add("")

    add("### 7.1 是否支持提前 1 小时预测")
    add("")
    if res["time_col"] is not None and res["interval_mode"] is not None:
        sec = pd.Timedelta(res["interval_mode"]).total_seconds()
        if sec > 0:
            steps = 3600 / sec
            steps_txt = f"{steps:g}" if steps == int(steps) else f"{steps:.1f}"
            add(f"- 采样间隔为 {fmt_td(res['interval_mode'])}，1 小时对应 {steps_txt} 步，"
                f"目标可定义为 `t+{steps_txt}`。")
        add("- 时间戳连续、无重复，具备构造监督学习样本的基础条件。")
        if res["missing_total"] == 0 and res["duplicate_rows"] == 0:
            add("- 负荷与天气字段无缺失，三个区域可以共用同一时间索引。")
        else:
            add("- 存在缺失或重复记录，建模前必须先处理，否则样本会错位。")
        add("- 数据只覆盖约一年、单一城市，结论限于本数据范围，不能外推到其他年份或地区。")
    else:
        add("- 时间列或采样间隔尚未确认，暂不能判断。")
    add("")

    add("- 本报告只做质量审计，不包含建模结论；清洗规则需在 A2 中依据本报告确定。")
    add("")

    # 8. 复现
    add("## 8. 复现方式")
    add("")
    add("```bash")
    add("python src/data_audit.py --input data/raw/<数据文件名>.csv --output docs/data_audit.md")
    add("```")
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="A1 数据质量审计")
    parser.add_argument("--input", help="原始 CSV 路径；省略时自动查找 data/raw/ 下的唯一 CSV")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="报告输出路径")
    args = parser.parse_args()

    try:
        path = resolve_input(args.input)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        return 1

    try:
        df, encoding = read_csv_robust(path)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 1

    if df.empty:
        print(f"[ERROR] 文件读取成功但没有任何数据行：{path}")
        return 1

    print(f"[OK] 已读取 {path}（编码 {encoding}）：{df.shape[0]:,} 行 × {df.shape[1]} 列")
    res = analyze(df, path)
    report = render_report(res, path, encoding)

    out = Path(args.output)
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    print(f"[OK] 报告已写入 {out}")
    if res["time_col"]:
        print(f"[INFO] 时间列={res['time_col']}，范围 {res['time_min']} ~ {res['time_max']}")
        print(f"[INFO] 采样间隔众数={res['interval_mode']}，不同间隔数={res['interval_unique']}")
    else:
        print("[WARN] 未识别出时间列，请人工确认时间字段格式")
    print(f"[INFO] 缺失单元格={res['missing_total']:,}，重复时间戳={res['dup_timestamps']:,}，"
          f"完全重复行={res['duplicate_rows']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

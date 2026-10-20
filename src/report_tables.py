#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表 1（字段说明）与表 2（数据质量与清洗情况）。

表格编号沿用 docs/report_plan.md 的图表清单，供报告第 2、3 章直接引用。

输出：
    outputs/metrics/report_table1.csv   表 1  字段说明
    outputs/metrics/report_table2.csv   表 2  数据质量与清洗情况
    docs/report_tables.md               两张表的 Markdown 版本，可直接粘进报告

统计量全部来自实际运行，不手工填写。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data_cleaning import clean_data, iqr_flags

METRICS_DIR = PROJECT_ROOT / "outputs" / "metrics"
DOCS_DIR = PROJECT_ROOT / "docs"

# 原始列名 -> (清洗后列名, 单位, 含义)
FIELD_INFO = [
    ("DateTime", "timestamp", "—", "时间戳，10 分钟采样"),
    ("Temperature", "temperature", "℃", "气温"),
    ("Humidity", "humidity", "%", "相对湿度"),
    ("Wind Speed", "wind_speed", "未注明", "风速"),
    ("general diffuse flows", "general_diffuse_flows", "未注明", "总漫射辐射"),
    ("diffuse flows", "diffuse_flows", "未注明", "漫射辐射"),
    ("Zone 1 Power Consumption", "zone1_power", "未注明", "区域 1 负荷"),
    ("Zone 2  Power Consumption", "zone2_power", "未注明", "区域 2 负荷（原列名含连续两个空格）"),
    ("Zone 3  Power Consumption", "zone3_power", "未注明", "区域 3 负荷（原列名含连续两个空格）"),
]


def build_table1(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for i, (raw, clean, unit, desc) in enumerate(FIELD_INFO, start=1):
        dtype = "datetime64[ns]" if clean == "timestamp" else str(df[clean].dtype)
        if clean == "timestamp":
            vmin, vmax, mean = str(df[clean].min()), str(df[clean].max()), "—"
        else:
            # 极小的值（如辐照度 0.004）用两位小数会显示成 0.00，按量级调整精度
            def fmt(v: float) -> str:
                return f"{v:.4f}" if abs(v) < 1 else f"{v:,.2f}"

            series = df[clean]
            vmin = fmt(float(series.min()))
            vmax = fmt(float(series.max()))
            mean = fmt(float(series.mean()))
        rows.append({
            "序号": i,
            "原始列名": raw,
            "清洗后列名": clean,
            "类型": dtype,
            "单位": unit,
            "最小值": vmin,
            "最大值": vmax,
            "均值": mean,
            "含义": desc,
        })
    return pd.DataFrame(rows)


def build_table2(df: pd.DataFrame, summary, flags: pd.DataFrame) -> pd.DataFrame:
    load_cols = ["zone1_power", "zone2_power", "zone3_power"]
    span_days = (df["timestamp"].max() - df["timestamp"].min()).days + 1
    flag_counts = flags["column"].value_counts().to_dict() if len(flags) else {}

    rows = [
        ("原始记录数", f"{summary.n_rows:,}", "—"),
        ("字段数", str(summary.n_cols), "—"),
        ("时间范围", f"{summary.time_min} 至 {summary.time_max}", "—"),
        ("时间跨度", f"{span_days} 天", "—"),
        ("采样间隔", f"{summary.sampling_interval}（{summary.n_interval_values} 种）", "无需重采样，保持 10 分钟粒度"),
        ("缺失值", f"{summary.n_missing_cells:,} 个", "无缺失，未做插值"),
        ("完全重复行", f"{summary.n_duplicate_rows:,} 行", "重复行整行删除"),
        ("重复时间戳", f"{summary.n_duplicate_timestamps:,} 个", "无重复，不需要去重"),
        ("负荷负值", f"{summary.n_negative_load:,} 个", "无负值，未做截断"),
        ("列名规整", "2 处", "Zone 2 / Zone 3 列名的连续空格折叠为单空格，再统一为 snake_case"),
        ("类型转换失败", f"{summary.n_coerce_failures:,} 个", "全部字段可转为数值，无需人工修正"),
        ("异常值标记（3×IQR）", f"{len(flags):,} 条", "只标记到 anomaly_flags.csv，不删除、不替换"),
        ("输出记录数", f"{len(df):,}", "行按时间升序，索引重置"),
    ]

    for col, n in sorted(flag_counts.items(), key=lambda x: -x[1]):
        rows.append((f"　其中 {col}", f"{n:,} 条", "极端点集中在固定时段，按真实波动保留"))

    return pd.DataFrame(rows, columns=["检查项", "结果", "处理方式"])


def to_markdown(t1: pd.DataFrame, t2: pd.DataFrame) -> str:
    lines = [
        "# 报告表 1 与表 2",
        "",
        "由 `src/report_tables.py` 生成，数字来自实际运行，可直接粘贴进报告。",
        "",
        "## 表 1  数据字段说明",
        "",
        "| " + " | ".join(t1.columns) + " |",
        "|" + "|".join(["---"] * len(t1.columns)) + "|",
    ]
    for r in t1.itertuples(index=False):
        lines.append("| " + " | ".join(str(x) for x in r) + " |")

    lines += [
        "",
        "注：温度与湿度按数值范围判断为 ℃ 和 %；风速、辐照度、负荷的单位原始数据未注明，"
        "本表不做推断，报告中的比值类结论不受影响。",
        "",
        "## 表 2  数据质量与清洗情况",
        "",
        "| " + " | ".join(t2.columns) + " |",
        "|" + "|".join(["---"] * len(t2.columns)) + "|",
    ]
    for r in t2.itertuples(index=False):
        lines.append("| " + " | ".join(str(x) for x in r) + " |")

    lines += [
        "",
        "注：异常值为 IQR 规则的统计标记，仅用于提示，清洗阶段不做删除或替换；"
        "负荷峰值属于真实用电行为，保留原值。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    df, summary = clean_data(write=False)
    flags = iqr_flags(df)

    t1 = build_table1(df)
    t2 = build_table2(df, summary, flags)

    t1.to_csv(METRICS_DIR / "report_table1.csv", index=False, encoding="utf-8-sig")
    t2.to_csv(METRICS_DIR / "report_table2.csv", index=False, encoding="utf-8-sig")
    (DOCS_DIR / "report_tables.md").write_text(to_markdown(t1, t2), encoding="utf-8")

    print(f"表 1：{len(t1)} 行；表 2：{len(t2)} 行")
    print(f"已写入 {METRICS_DIR} 与 {DOCS_DIR / 'report_tables.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

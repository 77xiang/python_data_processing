#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A2 数据读取、校验与清洗模块。

设计原则：
- 原始 CSV 只读，不覆盖、不修改。
- 不做插值、不删负荷峰值、不做标准化；异常值只标记并单独输出。
- 输出统一的列名、类型和时间顺序，供成员 B 的建模代码直接使用。

用法：
    python src/data_cleaning.py
    python src/data_cleaning.py --input data/raw/xxx.csv --output data/processed/power_load_clean.csv
"""

from __future__ import annotations

import argparse
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DEFAULT_OUTPUT = PROCESSED_DIR / "power_load_clean.csv"
DEFAULT_FLAGS = PROCESSED_DIR / "anomaly_flags.csv"

RAW_COLUMN_MAP = {
    "datetime": "timestamp",
    "temperature": "temperature",
    "humidity": "humidity",
    "wind speed": "wind_speed",
    "general diffuse flows": "general_diffuse_flows",
    "diffuse flows": "diffuse_flows",
    "zone 1 power consumption": "zone1_power",
    "zone 2 power consumption": "zone2_power",
    "zone 3 power consumption": "zone3_power",
}

WEATHER_COLUMNS = [
    "temperature",
    "humidity",
    "wind_speed",
    "general_diffuse_flows",
    "diffuse_flows",
]
LOAD_COLUMNS = ["zone1_power", "zone2_power", "zone3_power"]
REQUIRED_COLUMNS = ["timestamp", "temperature", "humidity", "wind_speed"] + LOAD_COLUMNS
OUTPUT_COLUMNS = ["timestamp"] + WEATHER_COLUMNS + LOAD_COLUMNS


@dataclass
class DataQualitySummary:
    n_rows: int
    n_cols: int
    columns: list[str]
    time_min: str | None
    time_max: str | None
    sampling_interval: str | None
    n_interval_values: int
    n_missing_cells: int
    missing_by_column: dict[str, int] = field(default_factory=dict)
    n_duplicate_rows: int = 0
    n_duplicate_timestamps: int = 0
    is_time_sorted: bool = True
    n_coerce_failures: int = 0
    n_negative_load: int = 0
    dropped_columns: list[str] = field(default_factory=list)

    def format(self) -> str:
        lines = [
            f"行数：{self.n_rows:,}；列数：{self.n_cols}",
            f"时间范围：{self.time_min} ~ {self.time_max}",
            f"采样间隔：{self.sampling_interval}（{self.n_interval_values} 种）",
            f"缺失单元格：{self.n_missing_cells:,}",
            f"完全重复行（已删除）：{self.n_duplicate_rows:,}",
            f"重复时间戳：{self.n_duplicate_timestamps:,}",
            f"时间升序：{'是' if self.is_time_sorted else '否'}",
            f"类型转换失败：{self.n_coerce_failures:,}",
            f"负荷负值：{self.n_negative_load:,}",
        ]
        if self.missing_by_column:
            detail = "、".join(f"{k}={v}" for k, v in self.missing_by_column.items())
            lines.append(f"缺失分布：{detail}")
        if self.dropped_columns:
            lines.append(f"未纳入输出的列：{', '.join(self.dropped_columns)}")
        return "\n".join(lines)


def _normalize_name(name) -> str:
    """折叠连续空白、去首尾空格、转小写，用于匹配原始列名。"""
    return re.sub(r"\s+", " ", str(name)).strip().lower()


def _snake_name(name) -> str:
    s = _normalize_name(name)
    s = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "_", s)
    return s.strip("_")


def find_raw_file(path: str | Path | None = None) -> Path:
    if path is not None:
        p = Path(path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        if not p.is_file():
            raise FileNotFoundError(f"输入文件不存在：{p}")
        return p

    files = sorted(p for p in RAW_DIR.glob("*.csv") if p.is_file())
    if not files:
        raise FileNotFoundError(
            f"未在 {RAW_DIR} 找到 CSV 文件，请放入原始数据或用 --input 指定路径。"
        )
    if len(files) > 1:
        names = "\n".join(f"  - {p.name}" for p in files)
        raise RuntimeError(f"data/raw/ 下有多个 CSV，请用 --input 明确指定：\n{names}")
    return files[0]


def load_raw(path: str | Path | None = None) -> pd.DataFrame:
    """读取原始 CSV，按常见编码依次尝试。"""
    p = find_raw_file(path)
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            df = pd.read_csv(p, encoding=encoding)
        except UnicodeDecodeError:
            continue
        if df.empty:
            raise ValueError(f"文件读取成功但没有数据行：{p}")
        return df
    raise RuntimeError(f"CSV 读取失败，已尝试 utf-8/gbk/gb18030：{p}")


def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """把原始列名统一成 snake_case；已知列按固定映射，未知列保留但改名。"""
    mapping = {}
    for col in df.columns:
        key = _normalize_name(col)
        mapping[col] = RAW_COLUMN_MAP.get(key, _snake_name(col))
    out = df.rename(columns=mapping)
    if out.columns.duplicated().any():
        dup = out.columns[out.columns.duplicated()].unique().tolist()
        raise ValueError(f"列名规整后出现重复：{dup}")
    return out


def parse_datetime(df: pd.DataFrame, column: str = "timestamp") -> pd.DataFrame:
    """解析时间列；解析失败直接报错，避免带着错误时间进入建模。"""
    if column not in df.columns:
        raise ValueError(f"缺少时间列 `{column}`，现有列：{list(df.columns)}")

    raw = df[column]
    parsed = pd.to_datetime(raw, errors="coerce")
    if parsed.notna().sum() < raw.notna().sum() * 0.8:
        alt = pd.to_datetime(raw, errors="coerce", dayfirst=True)
        if alt.notna().sum() > parsed.notna().sum():
            parsed = alt

    bad = raw.notna() & parsed.isna()
    if bad.any():
        examples = raw[bad].head(5).tolist()
        raise ValueError(f"时间列有 {int(bad.sum()):,} 条无法解析，示例：{examples}")

    out = df.copy()
    out[column] = parsed
    return out


def _fmt_td(td) -> str | None:
    if td is None or pd.isna(td):
        return None
    total = pd.Timedelta(td).total_seconds()
    if total >= 3600 and total % 3600 == 0:
        return f"{int(total // 3600)} 小时"
    if total % 60 == 0:
        return f"{int(total // 60)} 分钟"
    return f"{total:.1f} 秒"


def validate_frame(
    df: pd.DataFrame,
    *,
    n_duplicate_rows: int | None = None,
    n_coerce_failures: int = 0,
    dropped_columns: list[str] | None = None,
) -> DataQualitySummary:
    """检查必需字段、时间顺序、重复和采样间隔。不修改传入的 DataFrame。"""
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"缺少必需字段：{missing_cols}")

    ts = df["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(ts):
        raise TypeError("`timestamp` 必须是 datetime64 类型，请先调用 parse_datetime()")

    diffs = ts.sort_values().diff().dropna()
    interval_counts = diffs.value_counts()
    interval = interval_counts.idxmax() if len(interval_counts) else None

    loads = df[LOAD_COLUMNS]
    n_negative = int((loads < 0).sum().sum())

    missing_by_column = {
        c: int(df[c].isna().sum()) for c in df.columns if int(df[c].isna().sum()) > 0
    }

    return DataQualitySummary(
        n_rows=int(len(df)),
        n_cols=int(df.shape[1]),
        columns=list(df.columns),
        time_min=str(ts.min()) if ts.notna().any() else None,
        time_max=str(ts.max()) if ts.notna().any() else None,
        sampling_interval=_fmt_td(interval),
        n_interval_values=int(len(interval_counts)),
        n_missing_cells=int(df.isna().sum().sum()),
        missing_by_column=missing_by_column,
        n_duplicate_rows=int(df.duplicated().sum()) if n_duplicate_rows is None else int(n_duplicate_rows),
        n_duplicate_timestamps=int(ts.duplicated().sum()),
        is_time_sorted=bool(ts.is_monotonic_increasing),
        n_coerce_failures=int(n_coerce_failures),
        n_negative_load=n_negative,
        dropped_columns=list(dropped_columns or []),
    )


# 异常点标记（只输出标记，不修改数据）

def iqr_flags(
    df: pd.DataFrame,
    columns: list[str] | None = None,
    k: float = 3.0,
) -> pd.DataFrame:
    """按 k×IQR 规则标记极端点，返回长表；不删除、不修正任何行。"""
    cols = columns or [c for c in LOAD_COLUMNS + WEATHER_COLUMNS if c in df.columns]
    records = []
    for col in cols:
        s = pd.to_numeric(df[col], errors="coerce")
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if pd.isna(iqr) or iqr <= 0:
            continue
        lower, upper = q1 - k * iqr, q3 + k * iqr
        mask = (s < lower) | (s > upper)
        for idx in s.index[mask.fillna(False)]:
            records.append({
                "timestamp": df.loc[idx, "timestamp"],
                "column": col,
                "value": float(s.loc[idx]),
                "rule": f"IQR_k{k:g}",
                "lower_bound": float(lower),
                "upper_bound": float(upper),
            })
    if not records:
        return pd.DataFrame(
            columns=["timestamp", "column", "value", "rule", "lower_bound", "upper_bound"]
        )
    return pd.DataFrame.from_records(records)


def clean_data(
    path: str | Path | None = None,
    *,
    output_path: str | Path | None = DEFAULT_OUTPUT,
    flags_path: str | Path | None = DEFAULT_FLAGS,
    write: bool = True,
    on_duplicate: str = "raise",
    k: float = 3.0,
) -> tuple[pd.DataFrame, DataQualitySummary]:
    """读取原始数据并完成规整。

    参数：
        path: 原始 CSV；省略时自动找 data/raw 下的唯一 CSV。
        output_path: 清洗结果输出路径；传 None 表示不写文件。
        flags_path: 异常标记输出路径；传 None 表示不写。
        write: 是否写文件。
        on_duplicate: 同一时间戳对应不同数值时的处理，'raise'（默认）或 'first'。
        k: 异常标记使用的 IQR 倍数，默认 3.0；只影响标记文件，不影响清洗结果。
    """
    raw = load_raw(path)
    df = standardize_columns(raw)

    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(
            f"清洗后仍缺少必需字段：{missing_cols}。"
            f"原始列名：{list(raw.columns)}"
        )

    df = parse_datetime(df, "timestamp")

    coerce_failures = 0
    for col in WEATHER_COLUMNS + LOAD_COLUMNS:
        if col not in df.columns:
            continue
        before = df[col].notna().sum()
        df[col] = pd.to_numeric(df[col], errors="coerce")
        coerce_failures += int(before - df[col].notna().sum())

    n_duplicate_rows = int(df.duplicated().sum())
    if n_duplicate_rows:
        df = df.drop_duplicates().reset_index(drop=True)

    # 同一时间戳但数值不同：默认报错，避免静默丢信息
    dup_ts = int(df["timestamp"].duplicated().sum())
    if dup_ts:
        if on_duplicate == "first":
            df = df.drop_duplicates(subset="timestamp", keep="first").reset_index(drop=True)
        elif on_duplicate == "raise":
            sample = df[df["timestamp"].duplicated(keep=False)].sort_values("timestamp").head(6)
            raise ValueError(
                f"存在 {dup_ts:,} 条时间戳重复但内容不同的记录，"
                f"请先确认如何处理，或显式传 on_duplicate='first'。示例：\n{sample}"
            )
        else:
            raise ValueError("on_duplicate 只能是 'raise' 或 'first'")

    df = df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)

    # 固定输出列；其余列记录后丢弃，保证接口稳定
    dropped = [c for c in df.columns if c not in OUTPUT_COLUMNS]
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            raise ValueError(f"输出列缺失：{col}")
    df = df[OUTPUT_COLUMNS].copy()

    summary = validate_frame(
        df,
        n_duplicate_rows=n_duplicate_rows,
        n_coerce_failures=coerce_failures,
        dropped_columns=dropped,
    )

    if write:
        if output_path is not None:
            out = Path(output_path)
            if not out.is_absolute():
                out = PROJECT_ROOT / out
            out.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(out, index=False, date_format="%Y-%m-%d %H:%M:%S")

        if flags_path is not None:
            flags = iqr_flags(df, k=k)
            fl = Path(flags_path)
            if not fl.is_absolute():
                fl = PROJECT_ROOT / fl
            fl.parent.mkdir(parents=True, exist_ok=True)
            flags.to_csv(fl, index=False, date_format="%Y-%m-%d %H:%M:%S")

    return df, summary


def load_clean(path: str | Path | None = None) -> pd.DataFrame:
    """读取已生成的清洗结果，并做最基本的类型检查。"""
    p = Path(path) if path is not None else DEFAULT_OUTPUT
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    if not p.is_file():
        raise FileNotFoundError(
            f"找不到清洗结果：{p}。请先运行 `python src/data_cleaning.py`。"
        )
    df = pd.read_csv(p)
    df = parse_datetime(df, "timestamp")
    missing_cols = [c for c in OUTPUT_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"清洗结果缺少列：{missing_cols}")
    return df


def main() -> int:
    parser = argparse.ArgumentParser(description="A2 数据读取、校验与清洗")
    parser.add_argument("--input", help="原始 CSV；省略时自动查找 data/raw 下的唯一 CSV")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="清洗结果输出路径")
    parser.add_argument("--flags", default=str(DEFAULT_FLAGS), help="异常标记输出路径")
    parser.add_argument("--no-write", action="store_true", help="只校验，不写文件")
    parser.add_argument("--k", type=float, default=3.0, help="IQR 异常标记倍数，默认 3")
    args = parser.parse_args()

    try:
        df, summary = clean_data(
            args.input,
            output_path=args.output,
            flags_path=args.flags,
            write=not args.no_write,
            k=args.k,
        )
    except (FileNotFoundError, RuntimeError, ValueError, TypeError) as exc:
        print(f"[ERROR] {exc}")
        return 1

    print("[OK] 清洗完成")
    print(summary.format())
    if not args.no_write:
        print(f"[OK] 清洗结果：{args.output}")
        print(f"[OK] 异常标记：{args.flags}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

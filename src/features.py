#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B2 特征构造模块。

按 docs/experiment_plan.md 第 3 节为三个区域构造预测样本：

- 样本 =（预测起点 t，目标 y(t+6)），t ∈ [1008, n_rows-1-6]；
- 默认历史特征（同区域，索引相对起点 t 的回溯步数）：
    load_lag_0    y(t)      当前负荷
    load_lag_6    y(t-6)    1 小时前
    load_lag_144  y(t-144)  24 小时前同期
    load_lag_1008 y(t-1008) 7 天前同期
- 时间特征取自预测起点 t 的时刻；目标时刻恒为 t+1 小时（确定性日历平移），
  因此无需为目标另建时间列；
- 天气特征取 t 时刻的同步观测（include_weather 开关，供 C2 消融切换）；
- 候选扩展特征（include_candidates 开关，默认关闭，与协议 3.2/11.2 一致）：
    load_lag_3        y(t-3)
    load_roll24_mean  回溯窗口 [t-143, t] 的 24 小时均值（右端点为 t，不含未来）
    load_season7_mean 过去 7 天同期均值 mean(y(t-144k))，k=1..7

泄漏规则：所有特征只使用 timestamp ≤ t 的观测；滚动窗口一律回溯（右端点 t），
不使用居中窗口。本模块不做任何拟合型预处理（标准化在 B3 模型管线中于训练集上拟合）。

接口：
    build_zone_samples(df, zone, *, include_weather=True, include_candidates=False)
        -> (X, y, meta)
    build_all_zones(df, **kwargs) -> dict[zone, (X, y, meta)]
    feature_groups(...) -> dict[str, list[str]]   特征分组，供 C2 消融引用
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data_cleaning import LOAD_COLUMNS, WEATHER_COLUMNS
from src.splits import (
    FORECAST_HORIZON,
    WEEK_STEPS,
    origin_bounds,
    split_labels,
)

ZONES = {"zone1": "zone1_power", "zone2": "zone2_power", "zone3": "zone3_power"}

# 默认主特征集的历史负荷特征：特征名 -> 相对起点的回溯步数
HISTORY_LAGS = {
    "load_lag_0": 0,
    "load_lag_6": 6,
    "load_lag_144": 144,
    "load_lag_1008": 1008,
}

TIME_FEATURES = ["hour", "dayofweek", "month", "hour_sin", "hour_cos"]

# 候选扩展特征（默认不进主特征集，B3 可用验证集决定是否保留）
CANDIDATE_FEATURES = ["load_lag_3", "load_roll24_mean", "load_season7_mean"]

ROLL24_WINDOW = 24 * 6      # 24 小时 = 144 步
DAY_STEPS = 144
SEASON_DAYS = 7


def _resolve_zone(zone: str) -> tuple[str, str]:
    """把 'zone1' 或 'zone1_power' 统一成 (标签, 列名)。"""
    if zone in ZONES:
        return zone, ZONES[zone]
    if zone in ZONES.values():
        label = zone[: -len("_power")]
        return label, zone
    raise ValueError(f"未知区域 {zone!r}，可选：{sorted(ZONES) | sorted(ZONES.values())}")


def _validate_df(df: pd.DataFrame, include_weather: bool) -> None:
    required = ["timestamp", *LOAD_COLUMNS]
    if include_weather:
        required += WEATHER_COLUMNS
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"缺少必需字段：{missing}")

    ts = df["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(ts):
        raise TypeError("`timestamp` 必须是 datetime64 类型，请先运行成员 A 的 clean_data()")
    if not ts.is_monotonic_increasing:
        raise ValueError("`timestamp` 必须按时间升序")

    n = len(df)
    if n < WEEK_STEPS + FORECAST_HORIZON + 1:
        raise ValueError(f"数据行数 {n} 不足以构造预测样本（至少 {WEEK_STEPS + FORECAST_HORIZON + 1}）")


def feature_groups(
    include_weather: bool = True,
    include_candidates: bool = False,
) -> dict[str, list[str]]:
    """返回特征分组，供 C2 消融与报告引用。

    - history + time          ：消融 A 组（无天气）
    - history + time + weather：消融 B 组（主实验特征集）
    """
    groups: dict[str, list[str]] = {
        "history": list(HISTORY_LAGS),
        "time": list(TIME_FEATURES),
    }
    if include_candidates:
        groups["history"] = groups["history"] + list(CANDIDATE_FEATURES)
    if include_weather:
        groups["weather"] = list(WEATHER_COLUMNS)
    return groups


def build_zone_samples(
    df: pd.DataFrame,
    zone: str,
    *,
    include_weather: bool = True,
    include_candidates: bool = False,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """为单个区域构造预测样本。

    参数：
        df: 成员 A 的 clean_data()/load_clean() 输出，按 timestamp 升序。
        zone: 'zone1' | 'zone2' | 'zone3'（或对应列名）。
        include_weather: 是否加入起点时刻的天气特征（C2 消融开关）。
        include_candidates: 是否加入候选扩展特征（默认关闭，与协议一致）。

    返回 (X, y, meta)，行索引均为预测起点的清洗后行号：
        X    特征矩阵，列固定（见模块 docstring）
        y    目标负荷 y(t+6)，Series 名为 'target'
        meta 时间与切分信息：origin_timestamp / target_timestamp / zone / split
    """
    zone_label, zone_col = _resolve_zone(zone)
    _validate_df(df, include_weather)

    n = len(df)
    first, last = origin_bounds(n)
    origins = np.arange(first, last + 1, dtype=int)
    load = df[zone_col].to_numpy(dtype=float)
    ts_arr = df["timestamp"].to_numpy()

    X = pd.DataFrame(index=origins)

    # 历史负荷滞后特征（相对起点 t 回溯，全部 ≤ t）
    for name, k in HISTORY_LAGS.items():
        X[name] = load[origins - k]

    if include_candidates:
        X["load_lag_3"] = load[origins - 3]
        # 回溯 24 小时均值：窗口 [t-143, t]，右端点 t，不含任何未来观测
        roll24 = (
            pd.Series(load)
            .rolling(window=ROLL24_WINDOW, min_periods=ROLL24_WINDOW)
            .mean()
            .to_numpy(dtype=float)
        )
        X["load_roll24_mean"] = roll24[origins]
        # 过去 7 天同期均值：mean(y(t-144k))，k=1..7
        season7 = np.zeros(len(origins), dtype=float)
        for k in range(1, SEASON_DAYS + 1):
            season7 += load[origins - k * DAY_STEPS]
        X["load_season7_mean"] = season7 / SEASON_DAYS

    # 时间特征：取预测起点 t 的时刻
    origin_dt = pd.DatetimeIndex(ts_arr[origins])
    hour = origin_dt.hour.to_numpy(dtype=float)
    X["hour"] = hour
    X["dayofweek"] = origin_dt.dayofweek.to_numpy(dtype=float)
    X["month"] = origin_dt.month.to_numpy(dtype=float)
    X["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    X["hour_cos"] = np.cos(2 * np.pi * hour / 24)

    # 天气特征：t 时刻同步观测（可用性假设见协议 3.3）
    if include_weather:
        for col in WEATHER_COLUMNS:
            X[col] = df[col].to_numpy(dtype=float)[origins]

    y = pd.Series(load[origins + FORECAST_HORIZON], index=origins, name="target")

    meta = pd.DataFrame(index=origins)
    meta["origin_timestamp"] = ts_arr[origins]
    meta["target_timestamp"] = ts_arr[origins + FORECAST_HORIZON]
    meta["zone"] = zone_label
    meta["split"] = split_labels(origins, n)

    return X, y, meta


def build_all_zones(
    df: pd.DataFrame,
    **kwargs,
) -> dict[str, tuple[pd.DataFrame, pd.Series, pd.DataFrame]]:
    """为三个区域构造样本；kwargs 透传给 build_zone_samples()。"""
    return {label: build_zone_samples(df, label, **kwargs) for label in ZONES}

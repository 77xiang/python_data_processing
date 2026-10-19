#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B2 时间切分模块。

按 docs/experiment_plan.md 第 4 节固化训练/验证/测试边界：

- 切分对象是预测起点（清洗后数据的行索引）；
- 可用起点满足 1008 ≤ t ≤ n_rows-1-6（下界保证 7 天历史特征存在，
  上界保证目标 t+6 存在）；
- 按起点时间顺序取前 70% 为训练、中间 15% 为验证、最后 15% 为测试；
- 三个区域共用同一套边界，避免不同区域测试区间不一致。

本模块不读取文件、不做清洗，只基于行数与固定比例计算索引区间；
`verify_against_plan()` 用于校验当前数据是否与实验协议完全一致。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FORECAST_HORIZON = 6      # 提前 1 小时 = 6 个时间步（10 分钟采样）
WEEK_STEPS = 1008         # 7 天 = 144 步/天 × 7
TRAIN_RATIO = 0.70
VAL_RATIO = 0.15

# 与 docs/experiment_plan.md 第 4 节一致的期望值（2026-10-19 实测）
EXPECTED_N_ROWS = 52416
EXPECTED_SPLITS = {
    "train": (35981, "2017-01-08 00:00:00", "2017-09-14 20:40:00"),
    "val": (7710, "2017-09-14 20:50:00", "2017-11-07 09:40:00"),
    "test": (7711, "2017-11-07 09:50:00", "2017-12-30 22:50:00"),
}
EXPECTED_TEST_TARGET = ("2017-11-07 10:50:00", "2017-12-30 23:50:00")


def origin_bounds(n_rows: int) -> tuple[int, int]:
    """返回可用预测起点的闭区间 (first, last)。

    下界：最远的默认历史特征 y(t-1008) 必须存在；
    上界：目标 y(t+FORECAST_HORIZON) 必须存在。
    """
    if n_rows < WEEK_STEPS + FORECAST_HORIZON + 1:
        raise ValueError(f"数据行数 {n_rows} 不足以构造预测样本")
    return WEEK_STEPS, n_rows - 1 - FORECAST_HORIZON


def split_ranges(n_rows: int) -> dict[str, tuple[int, int]]:
    """按协议计算训练/验证/测试的起点索引闭区间。"""
    first, last = origin_bounds(n_rows)
    n_origins = last - first + 1
    n_train = round(TRAIN_RATIO * n_origins)
    n_val = round(VAL_RATIO * n_origins)
    train_end = first + n_train - 1
    val_end = train_end + n_val
    return {
        "train": (first, train_end),
        "val": (train_end + 1, val_end),
        "test": (val_end + 1, last),
    }


def split_origin_indices(n_rows: int) -> dict[str, np.ndarray]:
    """返回各子集的预测起点行索引（升序 numpy 数组）。"""
    ranges = split_ranges(n_rows)
    return {
        name: np.arange(start, end + 1, dtype=int)
        for name, (start, end) in ranges.items()
    }


def split_labels(origins: np.ndarray, n_rows: int) -> np.ndarray:
    """按起点行索引给出 train/val/test 标签（向量化）。"""
    ranges = split_ranges(n_rows)
    train_end = ranges["train"][1]
    val_end = ranges["val"][1]
    return np.where(
        origins <= train_end, "train",
        np.where(origins <= val_end, "val", "test"),
    ).astype(object)


def verify_against_plan(df: pd.DataFrame) -> dict[str, object]:
    """校验清洗后数据与实验协议一致，返回边界摘要；不一致时抛 AssertionError。"""
    n = len(df)
    assert n == EXPECTED_N_ROWS, f"行数与协议不符：实际 {n}，协议 {EXPECTED_N_ROWS}"
    ts = df["timestamp"]
    assert pd.api.types.is_datetime64_any_dtype(ts), "timestamp 必须是 datetime64"
    assert ts.is_monotonic_increasing, "timestamp 必须按时间升序"

    summary: dict[str, object] = {"n_rows": n}
    for name, (exp_n, exp_first, exp_last) in EXPECTED_SPLITS.items():
        start, end = split_ranges(n)[name]
        n_split = end - start + 1
        assert n_split == exp_n, f"{name} 样本数与协议不符：实际 {n_split}，协议 {exp_n}"
        actual_first = str(ts.iloc[start])
        actual_last = str(ts.iloc[end])
        assert actual_first == exp_first, f"{name} 起点时间与协议不符：实际 {actual_first}，协议 {exp_first}"
        assert actual_last == exp_last, f"{name} 终点时间与协议不符：实际 {actual_last}，协议 {exp_last}"
        summary[f"{name}_range"] = (actual_first, actual_last)
        summary[f"{name}_n"] = n_split

    test_start, test_end = split_ranges(n)["test"]
    target_first = str(ts.iloc[test_start + FORECAST_HORIZON])
    target_last = str(ts.iloc[test_end + FORECAST_HORIZON])
    assert (target_first, target_last) == EXPECTED_TEST_TARGET, (
        f"测试集目标时间与协议不符：实际 ({target_first}, {target_last})，"
        f"协议 {EXPECTED_TEST_TARGET}"
    )
    summary["test_target_range"] = (target_first, target_last)
    return summary

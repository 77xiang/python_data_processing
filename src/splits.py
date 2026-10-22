#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B2 时间切分模块。

按 docs/experiment_plan.md 第 4 节固化训练/验证/测试边界：

- 切分对象是预测起点（清洗后数据的行索引）；
- 可用起点满足 1008 ≤ t ≤ n_rows-1-6（下界保证 7 天历史特征存在，
  上界保证目标 t+6 存在）；
- 按起点时间顺序取前 70% 为训练、中间 15% 为验证、最后 15% 为测试；
- 三个区域共用同一套边界，避免不同区域测试区间不一致。

**purge（边界剔除）**：目标在起点之后 1 小时，因此某个子集末尾的若干起点，
其标签时刻会落到下一个子集的起点区间内——训练集末尾起点的标签会被验证集
"看到"，验证集末尾同理。为切断这条轻微的边界泄漏，训练集与验证集末尾各
剔除 FORECAST_HORIZON（6）个起点，被剔除的样本不进入任何子集。
剔除后：训练末起点的目标时刻 < 验证集首起点时刻，验证末起点的目标时刻 <
测试集首起点时刻，任一子集的目标区间与下一子集的起点区间不再重叠。

本模块不读取文件、不做清洗，只基于行数与固定比例计算索引区间；
`verify_against_plan()` 用于校验当前数据是否与实验协议完全一致。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FORECAST_HORIZON = 6      # 提前 1 小时 = 6 个时间步（10 分钟采样）
WEEK_STEPS = 1008
TRAIN_RATIO = 0.70
VAL_RATIO = 0.15

# 子集末尾剔除的起点数：等于预测时域，保证末起点的目标不落入下一子集
PURGE = FORECAST_HORIZON

# 与 docs/experiment_plan.md 第 4 节一致的期望值（2026-10-21 加 purge 后实测）
EXPECTED_N_ROWS = 52416
EXPECTED_SPLITS = {
    "train": (35975, "2017-01-08 00:00:00", "2017-09-14 19:40:00"),
    "val": (7704, "2017-09-14 20:50:00", "2017-11-07 08:40:00"),
    "test": (7711, "2017-11-07 09:50:00", "2017-12-30 22:50:00"),
}
# 被 purge 剔除的起点区间（不进入任何子集）
EXPECTED_PURGED = {
    "train_tail": (6, "2017-09-14 19:50:00", "2017-09-14 20:40:00"),
    "val_tail": (6, "2017-11-07 08:50:00", "2017-11-07 09:40:00"),
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


def _raw_boundaries(n_rows: int) -> tuple[int, int, int, int]:
    """未按比例切分的原始边界 (first, last, raw_train_end, raw_val_end)。"""
    first, last = origin_bounds(n_rows)
    n_origins = last - first + 1
    n_train = round(TRAIN_RATIO * n_origins)
    n_val = round(VAL_RATIO * n_origins)
    raw_train_end = first + n_train - 1
    raw_val_end = raw_train_end + n_val
    return first, last, raw_train_end, raw_val_end


def split_ranges(n_rows: int) -> dict[str, tuple[int, int]]:
    """按协议计算训练/验证/测试的起点索引闭区间（已剔除 purge 段）。"""
    first, last, raw_train_end, raw_val_end = _raw_boundaries(n_rows)
    return {
        "train": (first, raw_train_end - PURGE),
        "val": (raw_train_end + 1, raw_val_end - PURGE),
        "test": (raw_val_end + 1, last),
    }


def purge_ranges(n_rows: int) -> dict[str, tuple[int, int]]:
    """返回被剔除的起点区间（训练集尾部与验证集尾部各 PURGE 个）。"""
    _, _, raw_train_end, raw_val_end = _raw_boundaries(n_rows)
    return {
        "train_tail": (raw_train_end - PURGE + 1, raw_train_end),
        "val_tail": (raw_val_end - PURGE + 1, raw_val_end),
    }


def split_origin_indices(n_rows: int) -> dict[str, np.ndarray]:
    """返回各子集的预测起点行索引（升序 numpy 数组）。"""
    ranges = split_ranges(n_rows)
    return {
        name: np.arange(start, end + 1, dtype=int)
        for name, (start, end) in ranges.items()
    }


def split_labels(origins: np.ndarray, n_rows: int) -> np.ndarray:
    """按起点行索引给出 train/val/purge/test 标签（向量化）。

    purge 段不属于任何子集，调用方按 train/val/test 取子集时会自动排除。
    """
    ranges = split_ranges(n_rows)
    purged = purge_ranges(n_rows)
    train_end = ranges["train"][1]
    val_end = ranges["val"][1]
    train_tail_end = purged["train_tail"][1]
    val_tail_end = purged["val_tail"][1]
    return np.where(
        origins <= train_end, "train",
        np.where(
            origins <= train_tail_end, "purge",
            np.where(
                origins <= val_end, "val",
                np.where(origins <= val_tail_end, "purge", "test"),
            ),
        ),
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

    # purge 段：数量与时刻
    for name, (exp_n, exp_first, exp_last) in EXPECTED_PURGED.items():
        start, end = purge_ranges(n)[name]
        assert end - start + 1 == exp_n, f"{name} 剔除数与协议不符：实际 {end - start + 1}，协议 {exp_n}"
        assert str(ts.iloc[start]) == exp_first, f"{name} 首点与协议不符：实际 {ts.iloc[start]}，协议 {exp_first}"
        assert str(ts.iloc[end]) == exp_last, f"{name} 末点与协议不符：实际 {ts.iloc[end]}，协议 {exp_last}"
        summary[f"purged_{name}_n"] = exp_n

    # 防泄漏：任一子集末起点的目标时刻，必须早于下一子集的首起点时刻
    ts_np = ts.to_numpy()
    ranges = split_ranges(n)
    for prev_name, next_name in (("train", "val"), ("val", "test")):
        prev_last_target = ts_np[ranges[prev_name][1] + FORECAST_HORIZON]
        next_first_origin = ts_np[ranges[next_name][0]]
        assert prev_last_target < next_first_origin, (
            f"{prev_name} 末起点的目标时刻 {prev_last_target} 未早于 "
            f"{next_name} 首起点时刻 {next_first_origin}，边界泄漏未切断"
        )

    test_start, test_end = ranges["test"]
    target_first = str(ts.iloc[test_start + FORECAST_HORIZON])
    target_last = str(ts.iloc[test_end + FORECAST_HORIZON])
    assert (target_first, target_last) == EXPECTED_TEST_TARGET, (
        f"测试集目标时间与协议不符：实际 ({target_first}, {target_last})，"
        f"协议 {EXPECTED_TEST_TARGET}"
    )
    summary["test_target_range"] = (target_first, target_last)
    return summary

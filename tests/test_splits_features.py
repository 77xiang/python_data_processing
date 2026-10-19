#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B2 索引对齐与切分一致性检查。

用法（任选其一）：
    python tests/test_splits_features.py      # 直接运行
    pytest tests/ -q                          # 如已安装 pytest

检查内容（全部来自实际运行，无预填结果）：
1. 切分边界与 docs/experiment_plan.md 第 4 节完全一致；
2. 三个区域共用完全相同的起点与切分；
3. 小样本索引核对：预测起点 -> 目标时刻恒为 +1 小时，各滞后特征取值
   与原始行逐一相等，天气/时间特征取自起点行；
4. 候选回溯特征只使用 ≤ t 的观测（与手工回溯窗口逐值比对）；
5. 样本数、列结构与协议一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data_cleaning import WEATHER_COLUMNS, clean_data  # noqa: E402
from src.features import (  # noqa: E402
    CANDIDATE_FEATURES,
    HISTORY_LAGS,
    TIME_FEATURES,
    ZONES,
    build_all_zones,
    build_zone_samples,
    feature_groups,
)
from src.splits import (  # noqa: E402
    EXPECTED_N_ROWS,
    EXPECTED_SPLITS,
    EXPECTED_TEST_TARGET,
    split_origin_indices,
    verify_against_plan,
)

# 人工核对用的预测起点（行索引）：首起点、B1 示例点、各切分边界点、末起点
SPOT_ORIGINS = [1008, 23265, 36988, 36989, 44698, 44699, 52409]
SPOT_SPLITS = ["train", "train", "train", "val", "val", "test", "test"]

_DF: pd.DataFrame | None = None


def _df() -> pd.DataFrame:
    global _DF
    if _DF is None:
        _DF, _ = clean_data(write=False)   # 只读校验，不写文件
    return _DF


def test_splits_match_plan() -> None:
    df = _df()
    summary = verify_against_plan(df)
    assert summary["n_rows"] == EXPECTED_N_ROWS

    indices = split_origin_indices(len(df))
    assert {k: len(v) for k, v in indices.items()} == {
        "train": 35981, "val": 7710, "test": 7711,
    }
    ts = df["timestamp"]
    for name, (exp_n, exp_first, exp_last) in EXPECTED_SPLITS.items():
        idx = indices[name]
        assert str(ts.iloc[idx[0]]) == exp_first
        assert str(ts.iloc[idx[-1]]) == exp_last
    test_idx = indices["test"]
    assert str(ts.iloc[test_idx[0] + 6]) == EXPECTED_TEST_TARGET[0]
    assert str(ts.iloc[test_idx[-1] + 6]) == EXPECTED_TEST_TARGET[1]


def test_all_zones_share_identical_splits() -> None:
    df = _df()
    samples = build_all_zones(df)
    base = samples["zone1"][2]
    for zone in ("zone2", "zone3"):
        meta = samples[zone][2]
        pd.testing.assert_series_equal(
            meta["origin_timestamp"], base["origin_timestamp"], check_names=False
        )
        pd.testing.assert_series_equal(
            meta["target_timestamp"], base["target_timestamp"], check_names=False
        )
        pd.testing.assert_series_equal(meta["split"], base["split"], check_names=False)
        assert set(meta["zone"]) == {zone}


def test_feature_index_alignment() -> None:
    df = _df()
    X, y, meta = build_zone_samples(df, "zone1")
    ts = df["timestamp"]
    load = df["zone1_power"]

    for t, exp_split in zip(SPOT_ORIGINS, SPOT_SPLITS):
        row = X.loc[t]
        # 目标时刻 = 起点 + 1 小时；切分标签按起点时间
        assert meta.loc[t, "target_timestamp"] == ts.iloc[t] + pd.Timedelta(hours=1)
        assert meta.loc[t, "split"] == exp_split
        # 滞后特征与原始行逐一相等（同一数组元素，精确比较）
        assert row["load_lag_0"] == load.iloc[t]
        assert row["load_lag_6"] == load.iloc[t - 6]
        assert row["load_lag_144"] == load.iloc[t - 144]
        assert row["load_lag_1008"] == load.iloc[t - 1008]
        # 天气特征取自起点行
        for col in WEATHER_COLUMNS:
            assert row[col] == df[col].iloc[t]
        # 时间特征取自起点时刻
        t0 = ts.iloc[t]
        assert row["hour"] == t0.hour
        assert row["dayofweek"] == t0.dayofweek
        assert row["month"] == t0.month
        assert np.isclose(row["hour_sin"], np.sin(2 * np.pi * t0.hour / 24))
        assert np.isclose(row["hour_cos"], np.cos(2 * np.pi * t0.hour / 24))
        # 目标值 = 起点后第 6 步的负荷
        assert y.loc[t] == load.iloc[t + 6]


def test_backward_only_candidates() -> None:
    df = _df()
    X, _, _ = build_zone_samples(df, "zone1", include_candidates=True)
    load = df["zone1_power"].to_numpy(dtype=float)
    for t in (1008, 23265, 44699):
        assert X.loc[t, "load_lag_3"] == load[t - 3]
        # 手工回溯窗口 [t-143, t]（右端点 t，不含未来）
        manual24 = float(load[t - 143 : t + 1].mean())
        manual7 = float(np.mean([load[t - 144 * k] for k in range(1, 8)]))
        assert np.isclose(X.loc[t, "load_roll24_mean"], manual24)
        assert np.isclose(X.loc[t, "load_season7_mean"], manual7)


def test_sample_counts_and_columns() -> None:
    df = _df()
    X, y, meta = build_zone_samples(df, "zone1")
    assert len(X) == 51402
    assert meta["split"].value_counts().to_dict() == {
        "train": 35981, "val": 7710, "test": 7711,
    }
    expected_cols = list(HISTORY_LAGS) + TIME_FEATURES + WEATHER_COLUMNS
    assert list(X.columns) == expected_cols
    assert y.name == "target"
    assert list(meta.columns) == ["origin_timestamp", "target_timestamp", "zone", "split"]

    # include_weather=False：天气列不出现（C2 消融 A 组）
    X_no_w, _, _ = build_zone_samples(df, "zone1", include_weather=False)
    assert list(X_no_w.columns) == list(HISTORY_LAGS) + TIME_FEATURES

    # include_candidates=True：候选列追加在天气列之前
    X_c, _, _ = build_zone_samples(df, "zone1", include_candidates=True)
    assert list(X_c.columns) == (
        list(HISTORY_LAGS) + CANDIDATE_FEATURES + TIME_FEATURES + WEATHER_COLUMNS
    )

    # feature_groups 与协议一致：消融 B 组 = history + time + weather
    groups = feature_groups()
    assert groups["history"] == list(HISTORY_LAGS)
    assert groups["time"] == TIME_FEATURES
    assert groups["weather"] == WEATHER_COLUMNS


def test_zones_count_and_shape() -> None:
    df = _df()
    samples = build_all_zones(df)
    for zone in ZONES:
        X, y, meta = samples[zone]
        assert len(X) == 51402
        assert X.shape[1] == 4 + 5 + 5
        assert set(meta["zone"]) == {zone}


def _print_spot_check_table() -> None:
    """打印人工核对表：预测起点、目标时刻、切分与关键特征取值。"""
    df = _df()
    samples = build_all_zones(df)
    print("\n== 人工核对表（Zone 1，特征值与原始行逐一比对已通过断言）==")
    print(f"{'起点(行号)':>12} {'目标时刻':>19} {'切分':>5} "
          f"{'y(t)':>10} {'y(t-6)':>10} {'y(t-144)':>10} {'y(t-1008)':>10} {'温度(t)':>7}")
    X, y, meta = samples["zone1"]
    for t in SPOT_ORIGINS:
        row = X.loc[t]
        print(
            f"{str(meta.loc[t, 'origin_timestamp']):>19} "
            f"{str(meta.loc[t, 'target_timestamp']):>19} {meta.loc[t, 'split']:>5} "
            f"{row['load_lag_0']:>10,.0f} {row['load_lag_6']:>10,.0f} "
            f"{row['load_lag_144']:>10,.0f} {row['load_lag_1008']:>10,.0f} "
            f"{row['temperature']:>7.2f}"
        )
    print(f"目标值示例（行号 {SPOT_ORIGINS[1]}）：y = {y.loc[SPOT_ORIGINS[1]]:,.2f}")


def main() -> int:
    tests = [
        test_splits_match_plan,
        test_all_zones_share_identical_splits,
        test_feature_index_alignment,
        test_backward_only_candidates,
        test_sample_counts_and_columns,
        test_zones_count_and_shape,
    ]
    failed = []
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as exc:
            failed.append(fn.__name__)
            print(f"FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed.append(fn.__name__)
            print(f"ERROR {fn.__name__}: {exc!r}")

    if not failed:
        _print_spot_check_table()
        print("\n全部检查通过")
        return 0
    print(f"\n失败项：{failed}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

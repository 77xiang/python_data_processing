#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B3 模型正确性与输出一致性检查。

用法（任选其一）：
    python tests/test_models.py
    pytest tests/ -q

检查内容（全部来自实际运行）：
1. 历史同期基线的索引对齐：预测值 == y(t-1002)（目标时刻上一周同期）；
2. 线性回归管线只在训练集拟合、输出有限且指标可算；
3. run_models() 的指标行数与协议一致（2 模型 × 3 区域 × 3 子集）；
4. 预测文件内容：actual == y(t+6)、naive 的 predicted == y(t-1002)，
   行列数与协议一致。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data_cleaning import clean_data  # noqa: E402
from src.evaluate import evaluate_split, mae, rmse, run_models  # noqa: E402
from src.models import (  # noqa: E402
    LINEAR_REGRESSION,
    SEASONAL_NAIVE,
    seasonal_naive_predict,
    train_linear_regression,
)
from src.splits import FORECAST_HORIZON, WEEK_STEPS  # noqa: E402

_DF: pd.DataFrame | None = None


def _df() -> pd.DataFrame:
    global _DF
    if _DF is None:
        _DF, _ = clean_data(write=False)
    return _DF


def test_naive_index_alignment() -> None:
    df = _df()
    load = df["zone1_power"].to_numpy(dtype=float)
    rng = np.random.default_rng(7)
    origins = np.sort(rng.integers(1008, len(df) - 1 - 6, size=50))
    pred = seasonal_naive_predict(load, origins)
    assert np.array_equal(pred, load[origins - (WEEK_STEPS - FORECAST_HORIZON)])
    # 每个预测值的取值时刻 = 目标时刻往前 7 天
    ts = df["timestamp"]
    for t in origins[:5]:
        target_time = ts.iloc[t + FORECAST_HORIZON]
        naive_time = ts.iloc[t + FORECAST_HORIZON - WEEK_STEPS]
        assert target_time - naive_time == pd.Timedelta(days=7)


def test_metrics_functions() -> None:
    y = np.array([10.0, 20.0, 30.0])
    y_pred = np.array([12.0, 18.0, 27.0])
    assert mae(y, y_pred) == 7 / 3
    assert np.isclose(rmse(y, y_pred), np.sqrt((4 + 4 + 9) / 3))
    out = evaluate_split(y, y_pred)
    assert out == {"n_samples": 3, "mae": 7 / 3, "rmse": np.sqrt(17 / 3)}


def test_linear_regression_runs() -> None:
    df = _df()
    from src.features import build_zone_samples

    X, y, meta = build_zone_samples(df, "zone2")
    train_mask = (meta["split"] == "train").to_numpy()
    model = train_linear_regression(X.to_numpy()[train_mask], y.to_numpy()[train_mask])
    pred = model.predict(X)
    assert len(pred) == len(X)
    assert np.isfinite(pred).all()
    # 训练集指标非负且有限
    for split in ("train", "val", "test"):
        mask = (meta["split"] == split).to_numpy()
        m = evaluate_split(y.to_numpy()[mask], pred[mask])
        assert m["n_samples"] == int(mask.sum())
        assert 0 <= m["mae"] < np.inf and 0 <= m["rmse"] < np.inf


def test_run_models_output_consistency() -> None:
    df = _df()
    metrics = run_models(df, [SEASONAL_NAIVE, LINEAR_REGRESSION], save=False)
    # 2 模型 × 3 区域 × 3 子集
    assert len(metrics) == 18
    assert set(metrics["model"]) == {SEASONAL_NAIVE, LINEAR_REGRESSION}
    assert set(metrics["zone"]) == {"zone1", "zone2", "zone3"}
    assert set(metrics["split"]) == {"train", "val", "test"}
    for _, row in metrics.iterrows():
        if row["split"] == "test":
            assert row["n_samples"] == 7711

    # naive 预测与 y(t-1002) 逐值相等（抽查两个区域若干行）
    samples = {z: None for z in ("zone1", "zone3")}
    from src.features import build_zone_samples

    for zone in samples:
        X, y, meta = build_zone_samples(df, zone)
        load = df[f"{zone}_power"].to_numpy(dtype=float)
        test_idx = X.index.to_numpy()[(meta["split"] == "test").to_numpy()]
        pred = seasonal_naive_predict(load, test_idx)
        expected = load[test_idx - (WEEK_STEPS - FORECAST_HORIZON)]
        assert np.array_equal(pred, expected)
        rng = np.random.default_rng(1)
        spot = rng.choice(len(test_idx), size=20, replace=False)
        assert np.array_equal(
            y.to_numpy()[(meta["split"] == "test").to_numpy()][spot],
            load[test_idx[spot] + FORECAST_HORIZON],
        )


def test_saved_prediction_files() -> None:
    """保存的测试集预测文件与指标文件内容一致（协议 8.1/8.2 格式）。"""
    from src.evaluate import METRICS_DIR, PREDICTIONS_DIR, DEFAULT_METRICS_FILE

    for model in (SEASONAL_NAIVE, LINEAR_REGRESSION):
        p = PREDICTIONS_DIR / f"predictions_{model}.csv"
        assert p.is_file(), f"缺少预测文件 {p}"
        pred = pd.read_csv(p)
        assert list(pred.columns) == [
            "origin_timestamp", "target_timestamp", "zone",
            "actual", "predicted", "model", "split",
        ]
        assert set(pred["model"]) == {model}
        assert set(pred["split"]) == {"test"}
        assert set(pred["zone"]) == {"zone1", "zone2", "zone3"}
        assert len(pred) == 7711 * 3
        # 时间对齐：target = origin + 1 小时
        dt = pd.to_datetime(pred["target_timestamp"]) - pd.to_datetime(pred["origin_timestamp"])
        assert (dt == pd.Timedelta(hours=1)).all()
        assert pred[["actual", "predicted"]].notna().all().all()

    m = METRICS_DIR / DEFAULT_METRICS_FILE
    assert m.is_file(), f"缺少指标文件 {m}"
    metrics = pd.read_csv(m)
    assert list(metrics.columns) == ["model", "zone", "split", "n_samples", "mae", "rmse"]
    assert len(metrics) == 18


def test_gbt_deterministic_and_finite() -> None:
    """运行稳定性：同种子、同配置两次训练，预测逐值一致且有限。"""
    df = _df()
    from src.features import build_zone_samples
    from src.models import train_gradient_boosting

    X, y, meta = build_zone_samples(df, "zone3")
    train_mask = (meta["split"] == "train").to_numpy()
    kwargs = dict(max_iter=100, learning_rate=0.1, max_depth=5)
    m1 = train_gradient_boosting(X.to_numpy()[train_mask], y.to_numpy()[train_mask], **kwargs)
    m2 = train_gradient_boosting(X.to_numpy()[train_mask], y.to_numpy()[train_mask], **kwargs)
    pred = m1.predict(X)
    assert np.isfinite(pred).all()
    assert np.array_equal(pred, m2.predict(X))


def _nan_equal(a, b) -> bool:
    a_is_nan = pd.isna(a)
    b_is_nan = pd.isna(b)
    if a_is_nan and b_is_nan:
        return True
    return not a_is_nan and not b_is_nan and a == b


def test_gbt_output_files() -> None:
    """B4 输出文件：格式、行数、选定配置与调参明细一致。"""
    from src.evaluate import (
        GBT_CONFIG_FILE,
        GBT_METRICS_FILE,
        GBT_TUNING_FILE,
        METRICS_DIR,
        PREDICTIONS_DIR,
    )
    from src.models import GRADIENT_BOOSTING

    p = PREDICTIONS_DIR / f"predictions_{GRADIENT_BOOSTING}.csv"
    assert p.is_file(), f"缺少预测文件 {p}"
    pred = pd.read_csv(p)
    assert list(pred.columns) == [
        "origin_timestamp", "target_timestamp", "zone",
        "actual", "predicted", "model", "split",
    ]
    assert set(pred["model"]) == {GRADIENT_BOOSTING}
    assert set(pred["split"]) == {"test"}
    assert len(pred) == 7711 * 3
    dt = pd.to_datetime(pred["target_timestamp"]) - pd.to_datetime(pred["origin_timestamp"])
    assert (dt == pd.Timedelta(hours=1)).all()
    assert pred[["actual", "predicted"]].notna().all().all()

    metrics = pd.read_csv(METRICS_DIR / GBT_METRICS_FILE)
    assert list(metrics.columns) == ["model", "zone", "split", "n_samples", "mae", "rmse"]
    assert len(metrics) == 9

    tuning = pd.read_csv(METRICS_DIR / GBT_TUNING_FILE)
    config = pd.read_csv(METRICS_DIR / GBT_CONFIG_FILE)
    assert len(config) == 3 and set(config["zone"]) == {"zone1", "zone2", "zone3"}
    # 每个区域的选定配置 = 该区域验证集 RMSE 最小的候选
    for _, row in config.iterrows():
        zone_rows = tuning[tuning["zone"] == row["zone"]]
        best = zone_rows.loc[zone_rows["val_rmse"].idxmin()]
        assert _nan_equal(row["val_rmse"], best["val_rmse"])
        for key in ("max_iter", "learning_rate", "max_depth"):
            assert _nan_equal(row[key], best[key]), f"{row['zone']} 配置 {key} 与调参明细不符"
    # 调参只使用验证集：明细表只有 val 指标列，测试集指标不在其中
    assert not any("test" in c for c in tuning.columns)


def main() -> int:
    tests = [
        test_naive_index_alignment,
        test_metrics_functions,
        test_linear_regression_runs,
        test_run_models_output_consistency,
        test_saved_prediction_files,
        test_gbt_deterministic_and_finite,
        test_gbt_output_files,
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
        print("\n全部检查通过")
        return 0
    print(f"\n失败项：{failed}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

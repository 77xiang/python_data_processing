#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C3 误差分析的输入契约检查（基线与 tag 实验的读取口径）。

用法（任选其一）：
    python tests/test_error_analysis_io.py
    pytest tests/ -q

背景：src/probe_target_week.py 只保存改进模型的预测，不重复保存不消费特征的
历史同期基线，因此 predictions_seasonal_naive_tw.csv 并非脚本产物。这里用隔离
临时目录验证基线复用是安全的，且任何错配都会显式报错而不是静默继续。

检查内容：
1. 缺少 _tw 基线文件时，实验仍能复用主实验基线并正确运行；
2. 预测文件缺失时明确报 FileNotFoundError（主实验不会静默回退）；
3. 基线样本数 / 目标时间区间 / actual 与本次实验不一致时明确报 ValueError；
4. 主实验与 _tw 实验的输出文件相互独立，不会互相覆盖。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.error_analysis as ea  # noqa: E402
from src.data_cleaning import clean_data  # noqa: E402
from src.splits import FORECAST_HORIZON, split_origin_indices  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
N = 24

# 实验方案第 4 节口径：训练集目标时间范围 2017-01-08 01:00 – 2017-09-14 20:40
# （行 1014..36988，每区域 35,975 行）的负荷 Q90
EXPECTED_THRESHOLDS = {"zone1": 43120.5, "zone2": 27272.6, "zone3": 28369.5}

MAIN_FILES = [f"predictions_{m}.csv" for m in ea.MODELS]
TW_FILES = [f"predictions_{m}_tw.csv" for m in ea.MODELS]


def _frame(model: str, n: int = N, actual_shift: float = 0.0, predicted_shift: float = 0.0) -> pd.DataFrame:
    origin = pd.date_range("2017-01-01 00:00:00", periods=n, freq="10min")
    parts = []
    for zone in ea.ZONES:
        parts.append(pd.DataFrame({
            "origin_timestamp": origin,
            "target_timestamp": origin + pd.Timedelta(hours=1),
            "zone": zone,
            "actual": 1000.0 + np.arange(n) + actual_shift,
            "predicted": 1010.0 + np.arange(n) + predicted_shift,
            "model": model,
            "split": "test",
        }))
    return pd.concat(parts, ignore_index=True)


def _write_pred_dir(root: Path, tag: str = "", *, baseline: bool = True,
                    baseline_shift: float = 0.0, baseline_n: int | None = None,
                    baseline_time_shift_hours: int = 0) -> Path:
    """写入一套合成预测文件；baseline_* 参数用于制造错配场景。"""
    d = root / "pred"
    d.mkdir(parents=True, exist_ok=True)
    for model in ea.MODELS:
        if model == ea.BASELINE_MODEL:
            continue
        _frame(model, predicted_shift=5.0 if tag == "_tw" else 0.0).to_csv(
            d / f"predictions_{model}{tag}.csv", index=False)
    if baseline:
        b = _frame(ea.BASELINE_MODEL, n=baseline_n or N, actual_shift=baseline_shift)
        if baseline_time_shift_hours:
            b["target_timestamp"] = b["target_timestamp"] + pd.Timedelta(hours=baseline_time_shift_hours)
            b["origin_timestamp"] = b["origin_timestamp"] + pd.Timedelta(hours=baseline_time_shift_hours)
        b.to_csv(d / f"predictions_{ea.BASELINE_MODEL}{tag}.csv", index=False)
    return d


@contextmanager
def _isolated(pred_dir: Path, metrics_dir: Path, figures_dir: Path, thresholds=None):
    saved = (ea.PRED_DIR, ea.METRICS_DIR, ea.FIGURES_DIR, ea.train_thresholds)
    ea.PRED_DIR, ea.METRICS_DIR, ea.FIGURES_DIR = pred_dir, metrics_dir, figures_dir
    if thresholds is not None:
        ea.train_thresholds = lambda: thresholds
    try:
        yield
    finally:
        ea.PRED_DIR, ea.METRICS_DIR, ea.FIGURES_DIR, ea.train_thresholds = saved


def _expect_raises(exc_type, fn, *args, keyword: str = "", **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        assert keyword in str(exc), f"错误信息缺少关键提示 {keyword!r}：{exc}"
        return str(exc)
    raise AssertionError(f"应抛出 {exc_type.__name__}，但函数正常返回（静默继续）")


def test_tw_reuses_main_baseline_when_absent() -> None:
    """没有 _tw 基线文件时，应复用主实验基线并正常运行。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pred = _write_pred_dir(root, "_tw", baseline=False)
        _frame(ea.BASELINE_MODEL).to_csv(pred / f"predictions_{ea.BASELINE_MODEL}.csv", index=False)
        with _isolated(pred, root / "metrics", root / "figures"):
            df = ea.load_predictions("_tw")
        assert set(df["model"]) == set(ea.MODELS), "三个模型都应参与分析"
        assert len(df) == 3 * len(ea.ZONES) * N
        base = df[df["model"] == ea.BASELINE_MODEL]
        assert np.allclose(base["actual"], _frame(ea.BASELINE_MODEL)["actual"].values)
        assert np.allclose(base["predicted"], _frame(ea.BASELINE_MODEL)["predicted"].values)


def test_missing_model_prediction_file_raises() -> None:
    """改进模型预测文件缺失时必须报错，不能静默跳过。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pred = _write_pred_dir(root, "", baseline=True)
        (pred / "predictions_gradient_boosting.csv").unlink()
        with _isolated(pred, root / "metrics", root / "figures"):
            _expect_raises(FileNotFoundError, ea.load_predictions, "", keyword="缺少预测文件")


def test_missing_baseline_without_tag_raises() -> None:
    """主实验自身缺少基线文件时不得回退到别的文件。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pred = _write_pred_dir(root, "", baseline=False)
        with _isolated(pred, root / "metrics", root / "figures"):
            _expect_raises(FileNotFoundError, ea.load_predictions, "", keyword="缺少预测文件")


def test_baseline_sample_count_mismatch_raises() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pred = _write_pred_dir(root, "_tw", baseline=False)
        _frame(ea.BASELINE_MODEL, n=N - 1).to_csv(
            pred / f"predictions_{ea.BASELINE_MODEL}.csv", index=False)
        with _isolated(pred, root / "metrics", root / "figures"):
            _expect_raises(ValueError, ea.load_predictions, "_tw", keyword="样本数")


def test_baseline_timestamp_mismatch_raises() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pred = _write_pred_dir(root, "_tw", baseline=False)
        b = _frame(ea.BASELINE_MODEL)
        b["target_timestamp"] = b["target_timestamp"] + pd.Timedelta(hours=3)
        b.to_csv(pred / f"predictions_{ea.BASELINE_MODEL}.csv", index=False)
        with _isolated(pred, root / "metrics", root / "figures"):
            _expect_raises(ValueError, ea.load_predictions, "_tw", keyword="不一致")


def test_baseline_actual_mismatch_raises() -> None:
    """actual 对不上说明读到的是过期文件，必须拒绝使用。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pred = _write_pred_dir(root, "_tw", baseline=False)
        _frame(ea.BASELINE_MODEL, actual_shift=7.5).to_csv(
            pred / f"predictions_{ea.BASELINE_MODEL}.csv", index=False)
        with _isolated(pred, root / "metrics", root / "figures"):
            _expect_raises(ValueError, ea.load_predictions, "_tw", keyword="过期文件")


def test_main_and_tw_outputs_are_independent() -> None:
    """两次分析各自写 <name>.csv / <name>_tw.csv，互不覆盖。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pred = root / "pred"
        pred.mkdir()
        _write_pred_dir(root, "")
        _write_pred_dir(root, "_tw", baseline=False)
        _frame(ea.BASELINE_MODEL).to_csv(
            pred / f"predictions_{ea.BASELINE_MODEL}.csv", index=False)
        metrics, figures = root / "metrics", root / "figures"
        thresholds = {z: 1005.0 for z in ea.ZONES}

        saved_argv = sys.argv
        try:
            for tag in ("", "_tw"):
                with _isolated(pred, metrics, figures, thresholds):
                    sys.argv = ["error_analysis.py", "--tag", tag]
                    ea.main()
        finally:
            sys.argv = saved_argv

        main_csv = metrics / "error_overall.csv"
        tw_csv = metrics / "error_overall_tw.csv"
        assert main_csv.is_file() and tw_csv.is_file(), "两个后缀的输出都应存在"
        a = pd.read_csv(main_csv)
        b = pd.read_csv(tw_csv)
        assert len(a) == len(b) == 3 * len(ea.ZONES)
        merged = a.merge(b, on=["model", "zone"], suffixes=("", "_tw"))
        assert not np.allclose(merged["mae"], merged["mae_tw"]), "两次实验的指标不应相同"
        for name in ("error_by_hour", "error_by_dayofweek", "error_by_month", "error_peak_vs_normal"):
            assert (metrics / f"{name}.csv").is_file(), f"{name}.csv 被覆盖或缺失"
            assert (metrics / f"{name}_tw.csv").is_file(), f"{name}_tw.csv 缺失"
        assert len(list(figures.glob("*.png"))) == 6, "两组图各自输出，共 6 张"


def test_train_thresholds_window_and_values() -> None:
    """阈值只由方案规定的训练集目标期确定：不含前 1008 行，也不含验证/测试。"""
    thresholds = ea.train_thresholds()
    for zone, expected in EXPECTED_THRESHOLDS.items():
        got = thresholds[zone]
        assert abs(got - expected) < 0.1, f"{zone} 阈值 {got:.1f} 与方案口径值 {expected} 不一致"

    df, _ = clean_data()
    origins = split_origin_indices(len(df))
    idx = origins["train"] + FORECAST_HORIZON
    for zone, expected in EXPECTED_THRESHOLDS.items():
        recomputed = float(df.loc[idx, f"{zone}_power"].quantile(ea.PEAK_QUANTILE))
        assert abs(recomputed - expected) < 0.1, f"{zone} 独立重算 {recomputed:.1f} 与预期不符"
    assert int(idx.min()) == 1014, "阈值窗口须从训练集首个目标行开始（不含被排除的前 1008 行）"
    assert int(idx.max()) < int(origins["val"][0]), "阈值窗口末点须早于验证集首起点"
    ts = df["timestamp"]
    assert str(ts.iloc[int(idx.min())]) == "2017-01-08 01:00:00", "窗口起点与方案表不符"
    assert str(ts.iloc[int(idx.max())]) == "2017-09-14 20:40:00", "窗口终点与方案表不符"


def main() -> int:
    tests = [
        test_tw_reuses_main_baseline_when_absent,
        test_missing_model_prediction_file_raises,
        test_missing_baseline_without_tag_raises,
        test_baseline_sample_count_mismatch_raises,
        test_baseline_timestamp_mismatch_raises,
        test_baseline_actual_mismatch_raises,
        test_main_and_tw_outputs_are_independent,
        test_train_thresholds_window_and_values,
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
    if failed:
        print(f"\n失败项：{failed}")
        return 1
    print("\n全部检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

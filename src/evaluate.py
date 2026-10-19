#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B3 评价与实验运行模块。

- 指标：MAE、RMSE，按（模型 × 区域 × 子集）计算（协议第 7 节）；
- run_models()：对三个区域分别训练/评估指定模型，并保存
    - 测试集预测 outputs/predictions/predictions_<model>.csv（协议 8.1 格式）
    - 指标表 outputs/metrics/baseline_metrics.csv（协议 8.2 格式）
- 切分由 src/splits.py 提供，三个模型共用同一测试区间；
- 验证集在本阶段只做记录（无超参可调），测试集仅用于最终评价。

用法：
    python src/evaluate.py
    python src/evaluate.py --models seasonal_naive linear_regression
    python src/evaluate.py --no-save      # 只计算指标，不写文件
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许直接以 `python src/evaluate.py` 运行：把项目根目录加入模块搜索路径
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.data_cleaning import load_clean
from src.features import ZONES, build_zone_samples
from src.models import (
    LINEAR_REGRESSION,
    SEASONAL_NAIVE,
    SUPPORTED_MODELS,
    seasonal_naive_predict,
    train_linear_regression,
)
from src.splits import verify_against_plan

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS_DIR = PROJECT_ROOT / "outputs" / "predictions"
METRICS_DIR = PROJECT_ROOT / "outputs" / "metrics"
DEFAULT_METRICS_FILE = "baseline_metrics.csv"

SPLITS = ("train", "val", "test")


def mae(y, y_pred) -> float:
    """平均绝对误差。"""
    y = np.asarray(y, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return float(np.mean(np.abs(y - y_pred)))


def rmse(y, y_pred) -> float:
    """均方根误差。"""
    y = np.asarray(y, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return float(np.sqrt(np.mean((y - y_pred) ** 2)))


def evaluate_split(y, y_pred) -> dict[str, float]:
    return {"n_samples": int(len(y)), "mae": mae(y, y_pred), "rmse": rmse(y, y_pred)}


def _predict_zone(model_name: str, X, y, meta, load: np.ndarray) -> np.ndarray:
    """对单个区域生成全部起点（train+val+test）的预测。"""
    origins = X.index.to_numpy(dtype=int)
    if model_name == SEASONAL_NAIVE:
        # 历史同期基线不消费特征，直接按 y(t-1002) 取值
        return seasonal_naive_predict(load, origins)

    if model_name == LINEAR_REGRESSION:
        train_mask = (meta["split"] == "train").to_numpy()
        # 标准化与回归都只在训练集上拟合
        model = train_linear_regression(X.to_numpy()[train_mask], y.to_numpy()[train_mask])
        return model.predict(X)

    raise ValueError(f"未知模型：{model_name}，可选 {SUPPORTED_MODELS}")


def run_models(
    df: pd.DataFrame,
    model_names: list[str],
    *,
    save: bool = True,
    metrics_filename: str = DEFAULT_METRICS_FILE,
) -> pd.DataFrame:
    """对三个区域分别训练/评估指定模型，返回指标长表（协议 8.2 格式）。"""
    unknown = [m for m in model_names if m not in SUPPORTED_MODELS]
    if unknown:
        raise ValueError(f"未知模型：{unknown}，可选 {SUPPORTED_MODELS}")

    metric_rows = []
    prediction_frames: dict[str, pd.DataFrame] = {}

    for model_name in model_names:
        test_frames = []
        for zone in ZONES:
            X, y, meta = build_zone_samples(df, zone)
            load = df[f"{zone}_power"].to_numpy(dtype=float)
            pred_all = _predict_zone(model_name, X, y, meta, load)

            for split in SPLITS:
                mask = (meta["split"] == split).to_numpy()
                metric_rows.append(
                    {
                        "model": model_name,
                        "zone": zone,
                        "split": split,
                        **evaluate_split(y.to_numpy()[mask], pred_all[mask]),
                    }
                )

            test_mask = (meta["split"] == "test").to_numpy()
            origin_ts = meta["origin_timestamp"].to_numpy()
            target_ts = meta["target_timestamp"].to_numpy()
            test_frames.append(
                pd.DataFrame(
                    {
                        "origin_timestamp": origin_ts[test_mask],
                        "target_timestamp": target_ts[test_mask],
                        "zone": zone,
                        "actual": y.to_numpy()[test_mask],
                        "predicted": pred_all[test_mask],
                        "model": model_name,
                        "split": "test",
                    }
                )
            )
        prediction_frames[model_name] = pd.concat(test_frames, ignore_index=True)

    metrics_df = pd.DataFrame(metric_rows)

    if save:
        PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
        METRICS_DIR.mkdir(parents=True, exist_ok=True)
        for model_name, frame in prediction_frames.items():
            out = PREDICTIONS_DIR / f"predictions_{model_name}.csv"
            frame.to_csv(out, index=False, date_format="%Y-%m-%d %H:%M:%S")
        metrics_df.to_csv(METRICS_DIR / metrics_filename, index=False)
    return metrics_df


def main() -> int:
    parser = argparse.ArgumentParser(description="B3 基线模型实验：历史同期基线与线性回归")
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(SUPPORTED_MODELS),
        choices=SUPPORTED_MODELS,
        help="要运行的模型",
    )
    parser.add_argument("--no-save", action="store_true", help="只计算指标，不写文件")
    args = parser.parse_args()

    df = load_clean()
    verify_against_plan(df)  # 运行前校验切分与协议一致

    metrics = run_models(df, args.models, save=not args.no_save)
    print(metrics.to_string(index=False))
    if not args.no_save:
        print(f"[OK] 预测文件已写入 {PREDICTIONS_DIR}")
        print(f"[OK] 指标表已写入 {METRICS_DIR / DEFAULT_METRICS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

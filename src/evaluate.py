#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B3/B4 评价与实验运行模块。

- 指标：MAE、RMSE，按（模型 × 区域 × 子集）计算（协议第 7 节）；
- run_models()：对三个区域分别训练/评估无调参模型（历史同期基线、线性回归）；
- run_gbt_experiment()：梯度提升树实验，先在验证集上小范围比较
  n_estimators/learning_rate/max_depth 少量候选（测试集不参与选参），
  再用选定配置生成预测与指标；
- 保存
    - 测试集预测 outputs/predictions/predictions_<model>.csv（协议 8.1 格式）
    - 指标表 outputs/metrics/<file>.csv（协议 8.2 格式）
    - GBT 调参明细 outputs/metrics/gbt_tuning.csv、选定配置 outputs/metrics/gbt_config.csv
- 切分由 src/splits.py 提供，三个模型共用同一测试区间。

用法：
    python src/evaluate.py                                  # 基线 + 线性回归
    python src/evaluate.py --models gradient_boosting       # 梯度提升树实验
    python src/evaluate.py --no-save                        # 只计算指标，不写文件
"""

from __future__ import annotations

import argparse
import itertools
import sys
import time
from pathlib import Path

# 允许直接以 `python src/evaluate.py` 运行：把项目根目录加入模块搜索路径
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.data_cleaning import load_clean
from src.features import ZONES, build_zone_samples
from src.models import (
    GRADIENT_BOOSTING,
    LINEAR_REGRESSION,
    SEASONAL_NAIVE,
    SUPPORTED_MODELS,
    GBT_CANDIDATES,
    GBT_SEED,
    seasonal_naive_predict,
    train_gradient_boosting,
    train_linear_regression,
)
from src.splits import verify_against_plan

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS_DIR = PROJECT_ROOT / "outputs" / "predictions"
METRICS_DIR = PROJECT_ROOT / "outputs" / "metrics"
DEFAULT_METRICS_FILE = "baseline_metrics.csv"
GBT_METRICS_FILE = "gbt_metrics.csv"
GBT_TUNING_FILE = "gbt_tuning.csv"
GBT_CONFIG_FILE = "gbt_config.csv"

SPLITS = ("train", "val", "test")

# 无调参模型走 run_models()；梯度提升树走 run_gbt_experiment()
UNTUNED_MODELS = (SEASONAL_NAIVE, LINEAR_REGRESSION)


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
    """对三个区域分别训练/评估无调参模型，返回指标长表（协议 8.2 格式）。

    梯度提升树需要先在验证集上选参，请改用 run_gbt_experiment()。
    """
    unknown = [m for m in model_names if m not in UNTUNED_MODELS]
    if unknown:
        raise ValueError(f"run_models 不支持：{unknown}，可选 {UNTUNED_MODELS}；梯度提升树请用 run_gbt_experiment()")

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


def gbt_candidate_grid(
    candidates: dict | None = None,
) -> list[dict]:
    """把候选参数展开成小网格（协议 §6：少量关键参数）。"""
    candidates = candidates or GBT_CANDIDATES
    keys = list(candidates)
    return [
        dict(zip(keys, combo))
        for combo in itertools.product(*(candidates[k] for k in keys))
    ]


def select_gbt_config(
    df: pd.DataFrame,
    zone: str,
    *,
    seed: int = GBT_SEED,
) -> tuple[dict, HistGradientBoostingRegressor, pd.DataFrame]:
    """在验证集上比较少量候选参数，返回 (最佳配置, 已训练模型, 调参明细)。

    只使用训练集拟合、验证集 RMSE 选优；测试集完全不参与选参。
    """
    X, y, meta = build_zone_samples(df, zone)
    train_mask = (meta["split"] == "train").to_numpy()
    val_mask = (meta["split"] == "val").to_numpy()
    X_train = X.to_numpy()[train_mask]
    y_train = y.to_numpy()[train_mask]
    y_val = y.to_numpy()[val_mask]

    records = []
    best_model: HistGradientBoostingRegressor | None = None
    best_score = float("inf")

    for params in gbt_candidate_grid():
        t0 = time.time()
        model = train_gradient_boosting(X_train, y_train, seed=seed, **params)
        fit_s = time.time() - t0
        pred_val = model.predict(X.to_numpy()[val_mask])
        score = rmse(y_val, pred_val)
        records.append(
            {
                "zone": zone,
                **params,
                "fit_s": round(fit_s, 1),
                "val_mae": round(mae(y_val, pred_val), 2),
                "val_rmse": round(score, 2),
            }
        )
        if score < best_score:
            best_score = score
            best_model = model
            best_params = dict(params)

    tuning_df = pd.DataFrame.from_records(records)
    return best_params, best_model, tuning_df


def run_gbt_experiment(
    df: pd.DataFrame,
    *,
    seed: int = GBT_SEED,
    save: bool = True,
    metrics_filename: str = GBT_METRICS_FILE,
    verbose: bool = True,
) -> pd.DataFrame:
    """梯度提升树实验：验证集选参 -> 用选定配置生成三区域预测与指标。

    返回指标长表（协议 8.2 格式）；save=True 时写出预测、指标、调参明细与配置。
    """
    metric_rows = []
    test_frames = []
    config_rows = []
    tuning_frames = []

    for zone in ZONES:
        best_params, model, tuning_df = select_gbt_config(df, zone, seed=seed)
        X, y, meta = build_zone_samples(df, zone)
        pred_all = model.predict(X)

        for split in SPLITS:
            mask = (meta["split"] == split).to_numpy()
            metric_rows.append(
                {
                    "model": GRADIENT_BOOSTING,
                    "zone": zone,
                    "split": split,
                    **evaluate_split(y.to_numpy()[mask], pred_all[mask]),
                }
            )

        test_mask = (meta["split"] == "test").to_numpy()
        test_frames.append(
            pd.DataFrame(
                {
                    "origin_timestamp": meta["origin_timestamp"].to_numpy()[test_mask],
                    "target_timestamp": meta["target_timestamp"].to_numpy()[test_mask],
                    "zone": zone,
                    "actual": y.to_numpy()[test_mask],
                    "predicted": pred_all[test_mask],
                    "model": GRADIENT_BOOSTING,
                    "split": "test",
                }
            )
        )
        config_rows.append(
            {
                "zone": zone,
                "seed": seed,
                **best_params,
                "val_rmse": float(
                    tuning_df.loc[
                        tuning_df["val_rmse"] == tuning_df["val_rmse"].min(),
                        "val_rmse",
                    ].iloc[0]
                ),
            }
        )
        tuning_frames.append(tuning_df)

    metrics_df = pd.DataFrame(metric_rows)
    predictions_df = pd.concat(test_frames, ignore_index=True)
    tuning_df = pd.concat(tuning_frames, ignore_index=True)
    config_df = pd.DataFrame(config_rows)

    if save:
        PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
        METRICS_DIR.mkdir(parents=True, exist_ok=True)
        predictions_df.to_csv(
            PREDICTIONS_DIR / f"predictions_{GRADIENT_BOOSTING}.csv",
            index=False,
            date_format="%Y-%m-%d %H:%M:%S",
        )
        metrics_df.to_csv(METRICS_DIR / metrics_filename, index=False)
        tuning_df.to_csv(METRICS_DIR / GBT_TUNING_FILE, index=False)
        config_df.to_csv(METRICS_DIR / GBT_CONFIG_FILE, index=False)

    if verbose:
        print("\n== GBT 验证集选参明细 ==")
        print(tuning_df.to_string(index=False))
        print("\n== GBT 选定配置 ==")
        print(config_df.to_string(index=False))
    return metrics_df


def main() -> int:
    parser = argparse.ArgumentParser(
        description="B3/B4 模型实验：历史同期基线、线性回归、梯度提升树"
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(UNTUNED_MODELS),
        choices=SUPPORTED_MODELS,
        help="要运行的模型（默认：历史同期基线与线性回归）",
    )
    parser.add_argument("--no-save", action="store_true", help="只计算指标，不写文件")
    args = parser.parse_args()

    df = load_clean()
    verify_against_plan(df)  # 运行前校验切分与协议一致
    save = not args.no_save

    untuned = [m for m in args.models if m in UNTUNED_MODELS]
    if untuned:
        metrics = run_models(df, untuned, save=save)
        print(metrics.to_string(index=False))
        if save:
            print(f"[OK] 预测文件已写入 {PREDICTIONS_DIR}")
            print(f"[OK] 指标表已写入 {METRICS_DIR / DEFAULT_METRICS_FILE}")

    if GRADIENT_BOOSTING in args.models:
        metrics = run_gbt_experiment(df, save=save)
        print(metrics.to_string(index=False))
        if save:
            print(f"[OK] 预测文件已写入 {PREDICTIONS_DIR / f'predictions_{GRADIENT_BOOSTING}.csv'}")
            print(f"[OK] 指标表已写入 {METRICS_DIR / GBT_METRICS_FILE}")
            print(f"[OK] 调参明细已写入 {METRICS_DIR / GBT_TUNING_FILE}、配置已写入 {METRICS_DIR / GBT_CONFIG_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

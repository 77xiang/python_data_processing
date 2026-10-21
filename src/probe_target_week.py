#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""追加验证实验：给学习模型补充"目标时刻对齐"的上周同期特征。

背景：历史同期基线用的是 ŷ(t+6) = y(t+6-1008) = y(t-1002)，即**目标时刻**
上一周的同期值；而主特征集里的 load_lag_1008 是**起点**前一周的值，比目标
时刻早一小时。两个学习模型因此没有直接拿到基线所使用的那条记录。

本脚本做单变量对照：除新增特征外，样本、切分、模型配置、评价指标全部不变。
    main                    主实验特征集（历史 + 时间 + 天气）
    main_plus_target_week   主实验特征集 + load_lag_target_week = y(t-1002)
梯度提升树逐区域沿用 outputs/metrics/gbt_config.csv 的已选配置（不重新选参），
以便把差异归因到特征本身。历史同期基线一并列出作为参照。

输出：
    outputs/metrics/probe_target_week.csv        长表
    outputs/metrics/probe_target_week_summary.csv 测试集对照汇总（含基线参照）

用法：
    python src/probe_target_week.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data_cleaning import clean_data  # noqa: E402
from src.evaluate import evaluate_split  # noqa: E402
from src.features import ZONES, build_zone_samples  # noqa: E402
from src.models import (  # noqa: E402
    GRADIENT_BOOSTING,
    LINEAR_REGRESSION,
    SEASONAL_NAIVE,
    seasonal_naive_predict,
    train_gradient_boosting,
    train_linear_regression,
)

METRICS_DIR = PROJECT_ROOT / "outputs" / "metrics"
PRED_DIR = PROJECT_ROOT / "outputs" / "predictions"
GBT_CONFIG_FILE = METRICS_DIR / "gbt_config.csv"

FEATURE_SETS = {"main": False, "main_plus_target_week": True}


def load_gbt_configs() -> dict[str, dict]:
    cfg = pd.read_csv(GBT_CONFIG_FILE)
    out = {}
    for row in cfg.itertuples(index=False):
        out[row.zone] = {
            "seed": int(row.seed),
            "max_iter": int(row.max_iter),
            "learning_rate": float(row.learning_rate),
            "max_depth": None if pd.isna(row.max_depth) else int(row.max_depth),
        }
    return out


def run_probe() -> pd.DataFrame:
    df, _ = clean_data()
    gbt_configs = load_gbt_configs()
    rows = []
    # 逐区域累积测试集预测，循环结束后统一写文件（按模型分文件）
    pred_frames: dict[str, list[pd.DataFrame]] = {LINEAR_REGRESSION: [], GRADIENT_BOOSTING: []}

    for zone in ZONES:
        for set_name, with_target_week in FEATURE_SETS.items():
            X, y, meta = build_zone_samples(
                df, zone, include_weather=True, include_target_week=with_target_week
            )
            train_mask = (meta["split"] == "train").to_numpy()
            X_train, y_train = X.to_numpy()[train_mask], y.to_numpy()[train_mask]

            models = {
                LINEAR_REGRESSION: train_linear_regression(X_train, y_train),
                GRADIENT_BOOSTING: train_gradient_boosting(X_train, y_train, **gbt_configs[zone]),
            }
            for model_name, model in models.items():
                pred = model.predict(X.to_numpy())

                # 累积"加目标对齐周特征"模型的测试集预测，供 C3 误差分析复用
                if with_target_week:
                    test_mask = (meta["split"] == "test").to_numpy()
                    pred_frames[model_name].append(
                        pd.DataFrame(
                            {
                                "origin_timestamp": meta["origin_timestamp"].to_numpy()[test_mask],
                                "target_timestamp": meta["target_timestamp"].to_numpy()[test_mask],
                                "zone": zone,
                                "actual": y.to_numpy()[test_mask],
                                "predicted": pred[test_mask],
                                "model": model_name,
                                "split": "test",
                            }
                        )
                    )

                for split in ("val", "test"):
                    mask = (meta["split"] == split).to_numpy()
                    rows.append(
                        {
                            "model": model_name,
                            "zone": zone,
                            "feature_set": set_name,
                            "n_features": X.shape[1],
                            "split": split,
                            **evaluate_split(y.to_numpy()[mask], pred[mask]),
                        }
                    )

        # 历史同期基线（不消费特征），作为参照线
        X0, y0, meta0 = build_zone_samples(df, zone)
        origins = X0.index.to_numpy(dtype=int)
        load = df[f"{zone}_power"].to_numpy(dtype=float)
        pred_naive = seasonal_naive_predict(load, origins)
        for split in ("val", "test"):
            mask = (meta0["split"] == split).to_numpy()
            rows.append(
                {
                    "model": SEASONAL_NAIVE,
                    "zone": zone,
                    "feature_set": "baseline_no_features",
                    "n_features": 0,
                    "split": split,
                    **evaluate_split(y0.to_numpy()[mask], pred_naive[mask]),
                }
            )

    PRED_DIR.mkdir(parents=True, exist_ok=True)
    for model_name, frames in pred_frames.items():
        pd.concat(frames, ignore_index=True).to_csv(
            PRED_DIR / f"predictions_{model_name}_tw.csv",
            index=False,
            date_format="%Y-%m-%d %H:%M:%S",
        )
    return pd.DataFrame(rows)


def make_summary(results: pd.DataFrame) -> pd.DataFrame:
    """测试集上"加目标对齐周特征"相对主特征集的误差变化（负值 = 误差下降）。"""
    test = results[results["split"] == "test"]
    wide = test.pivot_table(
        index=["model", "zone"], columns="feature_set", values=["mae", "rmse"]
    )
    naive = test[test["model"] == SEASONAL_NAIVE].set_index("zone")
    rows = []
    for (model, zone), r in wide.iterrows():
        rec = {"model": model, "zone": zone}
        for metric in ("mae", "rmse"):
            base = r[(metric, "main")]
            new = r[(metric, "main_plus_target_week")]
            nv = naive.loc[zone, metric]
            rec[f"{metric}_main"] = base
            rec[f"{metric}_plus"] = new
            rec[f"{metric}_delta_pct"] = (
                np.nan if (base is None or np.isnan(base)) else 100 * (new - base) / base
            )
            rec[f"{metric}_vs_naive_pct"] = 100 * (new - nv) / nv
        rows.append(rec)

    # 基线单独成行，便于对照
    naive = test[test["model"] == SEASONAL_NAIVE].set_index("zone")
    for zone in naive.index:
        rows.append(
            {
                "model": SEASONAL_NAIVE,
                "zone": zone,
                "mae_main": np.nan,
                "mae_plus": naive.loc[zone, "mae"],
                "mae_delta_pct": np.nan,
                "rmse_main": np.nan,
                "rmse_plus": naive.loc[zone, "rmse"],
                "rmse_delta_pct": np.nan,
                "rmse_vs_naive_pct": 0.0,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    results = run_probe()
    summary = make_summary(results)
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    results.to_csv(METRICS_DIR / "probe_target_week.csv", index=False)
    summary.to_csv(METRICS_DIR / "probe_target_week_summary.csv", index=False)

    pd.set_option("display.width", 200)
    print("== 追加验证：是否加入 load_lag_target_week（测试集）==")
    print(summary.round(2).to_string(index=False))
    print("\n[OK] ->", METRICS_DIR / "probe_target_week_summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

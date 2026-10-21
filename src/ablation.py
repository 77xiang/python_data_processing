#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 天气特征消融实验。

对照设计（docs/experiment_plan.md §3.3、§8.3）：
    A 组：历史负荷特征 + 时间特征（include_weather=False）
    B 组：历史负荷特征 + 时间特征 + 天气特征（include_weather=True，即主实验特征集）
两组除天气特征外，样本、切分、模型、参数选择方式、评价指标完全一致。

模型：线性回归（无超参）+ 梯度提升树（逐区域沿用 B4 在验证集上选定的配置，
见 outputs/metrics/gbt_config.csv）。天气特征只取预测起点 t 的同步观测，
不含目标时刻的任何未来信息；不预设天气特征有效，如实报告结果。

带 --target-week 时，两组都额外包含目标时刻对齐的上周同期特征
`load_lag_target_week = y(t-1002)`（主实验证实该特征能大幅降低学习模型误差，
因此消融必须在新特征集上重做，见 docs/experiment_log.md EXP-20261021-04/05），
输出文件名加 `_tw` 后缀，与主特征集结果分开保存。

输出：
    outputs/metrics/ablation_results.csv  长表：model/zone/feature_set/split/指标
    outputs/metrics/ablation_summary.csv  测试集对照汇总（绝对/相对变化）
    outputs/figures/fig9_ablation.png     测试集 RMSE 对照图

用法：
    python src/ablation.py                  # 主特征集
    python src/ablation.py --target-week    # 含目标对齐周特征的特征集
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data_cleaning import clean_data
from src.evaluate import evaluate_split
from src.features import build_zone_samples
from src.models import train_gradient_boosting, train_linear_regression

METRICS_DIR = PROJECT_ROOT / "outputs" / "metrics"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
GBT_CONFIG_FILE = METRICS_DIR / "gbt_config.csv"

ZONES = ("zone1", "zone2", "zone3")
FEATURE_SETS = {"A_no_weather": False, "B_with_weather": True}
SPLIT_LABELS = ("val", "test")  # 训练集指标对消融结论无意义，只记录 val/test

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False


def load_gbt_configs() -> dict[str, dict]:
    """读取 B4 逐区域选定的 GBT 配置（测试集不参与选参，直接复用）。"""
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


def run_ablation(target_week: bool = False) -> pd.DataFrame:
    df, _ = clean_data()
    gbt_configs = load_gbt_configs()

    rows = []
    for zone in ZONES:
        for set_name, include_weather in FEATURE_SETS.items():
            X, y, meta = build_zone_samples(
                df, zone, include_weather=include_weather, include_target_week=target_week
            )
            train_mask = (meta["split"] == "train").to_numpy()
            X_train, y_train = X.to_numpy()[train_mask], y.to_numpy()[train_mask]

            models = {
                "linear_regression": train_linear_regression(X_train, y_train),
                "gradient_boosting": train_gradient_boosting(
                    X_train, y_train, **gbt_configs[zone]
                ),
            }
            for model_name, model in models.items():
                pred = model.predict(X.to_numpy())
                for split in SPLIT_LABELS:
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
    return pd.DataFrame(rows)


def make_summary(results: pd.DataFrame) -> pd.DataFrame:
    """测试集上 B 组相对 A 组的误差绝对/相对变化（负值 = 加天气后误差下降）。"""
    test = results[results["split"] == "test"]
    wide = test.pivot_table(
        index=["model", "zone"], columns="feature_set", values=["mae", "rmse"]
    )
    rows = []
    for (model, zone), r in wide.iterrows():
        rows.append(
            {
                "model": model,
                "zone": zone,
                "mae_no_weather": r[("mae", "A_no_weather")],
                "mae_with_weather": r[("mae", "B_with_weather")],
                "mae_delta": r[("mae", "B_with_weather")] - r[("mae", "A_no_weather")],
                "mae_delta_pct": 100
                * (r[("mae", "B_with_weather")] - r[("mae", "A_no_weather")])
                / r[("mae", "A_no_weather")],
                "rmse_no_weather": r[("rmse", "A_no_weather")],
                "rmse_with_weather": r[("rmse", "B_with_weather")],
                "rmse_delta": r[("rmse", "B_with_weather")] - r[("rmse", "A_no_weather")],
                "rmse_delta_pct": 100
                * (r[("rmse", "B_with_weather")] - r[("rmse", "A_no_weather")])
                / r[("rmse", "A_no_weather")],
            }
        )
    return pd.DataFrame(rows)


def make_figure(results: pd.DataFrame, out_path: Path) -> None:
    test = results[results["split"] == "test"]
    models = ["linear_regression", "gradient_boosting"]
    model_labels = {"linear_regression": "线性回归", "gradient_boosting": "梯度提升树"}

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    x = np.arange(len(ZONES))
    width = 0.35
    for ax, model in zip(axes, models):
        sub = test[test["model"] == model].set_index(["zone", "feature_set"])
        no_w = [sub.loc[(z, "A_no_weather"), "rmse"] for z in ZONES]
        with_w = [sub.loc[(z, "B_with_weather"), "rmse"] for z in ZONES]
        ax.bar(x - width / 2, no_w, width, label="无天气特征（A 组）", color="#9db8d2")
        ax.bar(x + width / 2, with_w, width, label="含天气特征（B 组）", color="#c0504d")
        ax.set_title(model_labels[model])
        ax.set_xticks(x)
        ax.set_xticklabels(["Zone 1", "Zone 2", "Zone 3"])
        ax.set_xlabel("区域")
        ax.legend(fontsize=9)
    axes[0].set_ylabel("测试集 RMSE")
    fig.suptitle("天气特征消融：测试集 RMSE 对照（越低越好）")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="C2 天气特征消融实验")
    parser.add_argument(
        "--target-week",
        action="store_true",
        help="两组都加入目标时刻对齐的上周同期特征 load_lag_target_week",
    )
    args = parser.parse_args()
    suffix = "_tw" if args.target_week else ""

    results = run_ablation(target_week=args.target_week)
    summary = make_summary(results)

    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    results.to_csv(METRICS_DIR / f"ablation_results{suffix}.csv", index=False)
    summary.to_csv(METRICS_DIR / f"ablation_summary{suffix}.csv", index=False)
    make_figure(results, FIGURES_DIR / f"fig9_ablation{suffix}.png")

    pd.set_option("display.width", 160)
    print("== 消融汇总（测试集，delta 为 B 组 − A 组，负值表示加天气后误差下降）==")
    print(
        summary.round(2).to_string(index=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

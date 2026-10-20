#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C3 分区域与高负荷时段误差分析。

输入：B5 交付的测试集预测文件 outputs/predictions/predictions_<model>.csv
（协议 8.1），以及清洗后数据（仅用于按训练集负荷分布定高负荷阈值）。

分析内容：
1. 三区域 × 三模型总体指标：MAE / RMSE / bias（预测−实际均值，看系统性高估低估）
   / MAPE / nRMSE（RMSE ÷ 区域测试集均值，消除量级差异便于区域间公平比较）；
2. 误差按目标时刻的小时、星期、月份分组，检查系统性差异；
3. 高负荷时段：阈值 = 训练集该区域负荷分布的 Q90（只用训练集，不在测试集上调阈值），
   比较高峰 vs 普通时段误差；
4. 残差分布与残差随时间变化（图）。

输出：
    outputs/metrics/error_overall.csv        区域×模型总体指标
    outputs/metrics/error_by_hour.csv        按小时分组（测试集）
    outputs/metrics/error_by_dayofweek.csv   按星期分组（测试集）
    outputs/metrics/error_peak_vs_normal.csv 高峰/普通时段对比（测试集）
    outputs/figures/fig8_error_by_hour.png   各区域分小时 MAE
    outputs/figures/fig8_residual_dist.png   残差分布（主模型 GBT）
    docs/error_analysis_findings.md          结果段落草稿（C4 润色）
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
from src.splits import split_labels

PRED_DIR = PROJECT_ROOT / "outputs" / "predictions"
METRICS_DIR = PROJECT_ROOT / "outputs" / "metrics"
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
DOCS_DIR = PROJECT_ROOT / "docs"

MODELS = ("seasonal_naive", "linear_regression", "gradient_boosting")
MODEL_LABELS = {
    "seasonal_naive": "历史同期基线",
    "linear_regression": "线性回归",
    "gradient_boosting": "梯度提升树",
}
ZONES = ("zone1", "zone2", "zone3")
PEAK_QUANTILE = 0.9  # 高负荷阈值：训练集负荷分布 Q90

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False


def load_predictions() -> pd.DataFrame:
    frames = []
    for m in MODELS:
        f = pd.read_csv(PRED_DIR / f"predictions_{m}.csv", parse_dates=["origin_timestamp", "target_timestamp"])
        frames.append(f)
    df = pd.concat(frames, ignore_index=True)
    df["error"] = df["predicted"] - df["actual"]
    df["abs_error"] = df["error"].abs()
    return df


def train_thresholds() -> dict[str, float]:
    """各区域高负荷阈值：训练集（起点 split=train）负荷分布的 Q90。"""
    df, _ = clean_data()
    n = len(df)
    labels = split_labels(np.arange(n), n)  # 与协议一致的行级切分标签
    out = {}
    for z in ZONES:
        train_load = df.loc[labels == "train", f"{z}_power"]
        out[z] = float(train_load.quantile(PEAK_QUANTILE))
    return out


def overall_metrics(pred: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (model, zone), g in pred.groupby(["model", "zone"]):
        mean_load = g["actual"].mean()
        rows.append({
            "model": model,
            "zone": zone,
            "n_samples": len(g),
            "mae": g["abs_error"].mean(),
            "rmse": np.sqrt((g["error"] ** 2).mean()),
            "bias": g["error"].mean(),
            "mape_pct": 100 * (g["abs_error"] / g["actual"]).mean(),
            "nrmse_pct": 100 * np.sqrt((g["error"] ** 2).mean()) / mean_load,
        })
    return pd.DataFrame(rows)


def group_errors(pred: pd.DataFrame, key: str, values) -> pd.DataFrame:
    tmp = pred.assign(**{key: values})
    rows = []
    for (model, zone, v), g in tmp.groupby(["model", "zone", key]):
        rows.append({
            "model": model, "zone": zone, key: v,
            "n_samples": len(g),
            "mae": g["abs_error"].mean(),
            "rmse": np.sqrt((g["error"] ** 2).mean()),
            "bias": g["error"].mean(),
        })
    return pd.DataFrame(rows)


def peak_vs_normal(pred: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    rows = []
    for (model, zone), g in pred.groupby(["model", "zone"]):
        peak = g["actual"] >= thresholds[zone]
        for flag, sub in ((True, g[peak]), (False, g[~peak])):
            if len(sub) == 0:
                continue
            rows.append({
                "model": model, "zone": zone,
                "period": "peak" if flag else "normal",
                "n_samples": len(sub),
                "mae": sub["abs_error"].mean(),
                "rmse": np.sqrt((sub["error"] ** 2).mean()),
                "bias": sub["error"].mean(),
                "mape_pct": 100 * (sub["abs_error"] / sub["actual"]).mean(),
            })
    return pd.DataFrame(rows)


def fig_error_by_hour(by_hour: pd.DataFrame, out: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharex=True)
    for ax, zone in zip(axes, ZONES):
        for model in MODELS:
            sub = by_hour[(by_hour["model"] == model) & (by_hour["zone"] == zone)]
            ax.plot(sub["hour"], sub["mae"], marker="o", ms=3, label=MODEL_LABELS[model])
        ax.set_title(zone)
        ax.set_xlabel("目标时刻（小时）")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("测试集 MAE")
    axes[-1].legend(fontsize=9)
    fig.suptitle("分小时预测误差（测试集）")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def fig_residual_dist(pred: pd.DataFrame, out: Path) -> None:
    gbt = pred[pred["model"] == "gradient_boosting"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for ax, zone in zip(axes, ZONES):
        r = gbt[gbt["zone"] == zone]["error"]
        ax.hist(r, bins=80, color="#4b7fb5", alpha=0.85)
        ax.axvline(0, color="k", lw=1)
        ax.axvline(r.mean(), color="red", ls="--", lw=1, label=f"bias={r.mean():.0f}")
        ax.set_title(f"{zone} 残差分布（GBT）")
        ax.set_xlabel("残差（预测 - 实际）")
        ax.legend(fontsize=9)
    axes[0].set_ylabel("频数")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def fig_residual_time(pred: pd.DataFrame, out: Path) -> None:
    gbt = pred[pred["model"] == "gradient_boosting"]
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    for ax, zone in zip(axes, ZONES):
        sub = gbt[gbt["zone"] == zone].sort_values("target_timestamp")
        daily = sub.set_index("target_timestamp")["error"].resample("1D").mean()
        ax.plot(daily.index, daily.values, lw=1.2, color="#c0504d")
        ax.axhline(0, color="k", lw=0.8)
        ax.set_ylabel(f"{zone}\n日平均残差")
        ax.grid(alpha=0.3)
    axes[-1].set_xlabel("日期")
    fig.suptitle("残差随时间变化（GBT，日平均）")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def main() -> int:
    pred = load_predictions()
    thresholds = train_thresholds()
    print("高负荷阈值（训练集 Q90）：", {k: round(v, 1) for k, v in thresholds.items()})

    overall = overall_metrics(pred)
    by_hour = group_errors(pred, "hour", pred["target_timestamp"].dt.hour)
    by_dow = group_errors(pred, "dayofweek", pred["target_timestamp"].dt.dayofweek)
    by_month = group_errors(pred, "month", pred["target_timestamp"].dt.month)
    peak = peak_vs_normal(pred, thresholds)

    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    overall.to_csv(METRICS_DIR / "error_overall.csv", index=False)
    by_hour.to_csv(METRICS_DIR / "error_by_hour.csv", index=False)
    by_dow.to_csv(METRICS_DIR / "error_by_dayofweek.csv", index=False)
    by_month.to_csv(METRICS_DIR / "error_by_month.csv", index=False)
    peak.to_csv(METRICS_DIR / "error_peak_vs_normal.csv", index=False)

    fig_error_by_hour(by_hour, FIGURES_DIR / "fig8_error_by_hour.png")
    fig_residual_dist(pred, FIGURES_DIR / "fig8_residual_dist.png")
    fig_residual_time(pred, FIGURES_DIR / "fig8_residual_time.png")

    pd.set_option("display.width", 200)
    print("\n== 总体指标（测试集）==")
    print(overall.round(2).to_string(index=False))
    print("\n== 高峰 vs 普通时段（GBT）==")
    print(peak[peak["model"] == "gradient_boosting"].round(2).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B5 主实验统一比较模块。

从清洗数据出发完整重跑三个模型（历史同期基线、线性回归、梯度提升树），
保证所有结果可重新生成，然后合并指标并输出：

- outputs/metrics/model_comparison.csv   全部模型 × 区域 × 子集的指标（协议 8.2 格式）
- outputs/metrics/report_table3.csv      报告表 3：测试集 MAE/RMSE（含三区合并口径）
- outputs/metrics/improvement_vs_naive.csv  相对历史同期基线的误差变化（测试集）
- outputs/figures/fig7_pred_vs_actual.png   图 7：测试集片段真实值 vs 预测值（3 区 × 3 模型）
- outputs/figures/fig_residual_scatter.png  残差 vs 预测值散点（辅助分析，图 8 的深入分析由 C3 完成）

三个模型使用同一测试时间范围与同一目标定义；不挑选区域或时段报告。

用法：
    python src/compare.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 无界面环境直接写文件

# 允许直接以 `python src/compare.py` 运行：把项目根目录加入模块搜索路径
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager

from src.data_cleaning import load_clean
from src.evaluate import (
    DEFAULT_METRICS_FILE,
    GBT_METRICS_FILE,
    METRICS_DIR,
    PREDICTIONS_DIR,
    UNTUNED_MODELS,
    mae,
    rmse,
    run_gbt_experiment,
    run_models,
)
from src.models import (
    GRADIENT_BOOSTING,
    LINEAR_REGRESSION,
    SEASONAL_NAIVE,
    SUPPORTED_MODELS,
)
from src.splits import verify_against_plan

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"

MODEL_ORDER = (SEASONAL_NAIVE, LINEAR_REGRESSION, GRADIENT_BOOSTING)
MODEL_NAMES_CN = {
    SEASONAL_NAIVE: "历史同期基线",
    LINEAR_REGRESSION: "线性回归",
    GRADIENT_BOOSTING: "梯度提升树",
}
FIG7_WINDOW = ("2017-12-14 00:00:00", "2017-12-17 23:50:00")  # 测试期 4 天片段


def _setup_cjk() -> bool:
    """配置中文字体；返回是否找到可用的 CJK 字体。"""
    for name in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC"):
        try:
            font_manager.findfont(name, fallback_to_default=False)
        except Exception:  # noqa: BLE001
            continue
        plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        return True
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    return False


def _model_label(model: str, cjk: bool) -> str:
    if cjk:
        return MODEL_NAMES_CN[model]
    return model


def load_all_predictions() -> pd.DataFrame:
    """读取三个模型的测试集预测文件并合并（协议 8.1 格式）。"""
    frames = []
    for model in MODEL_ORDER:
        p = PREDICTIONS_DIR / f"predictions_{model}.csv"
        if not p.is_file():
            raise FileNotFoundError(f"缺少 {p}，请先运行 python src/evaluate.py")
        frames.append(pd.read_csv(p))
    preds = pd.concat(frames, ignore_index=True)
    preds["target_timestamp"] = pd.to_datetime(preds["target_timestamp"])
    preds["origin_timestamp"] = pd.to_datetime(preds["origin_timestamp"])
    return preds


def improvement_vs_naive(metrics: pd.DataFrame) -> pd.DataFrame:
    """测试集上，各模型相对历史同期基线的绝对/相对误差变化（协议 7、B5 要求 5）。"""
    test = metrics[metrics["split"] == "test"]
    naive = test[test["model"] == SEASONAL_NAIVE].set_index("zone")
    rows = []
    for model in (LINEAR_REGRESSION, GRADIENT_BOOSTING):
        other = test[test["model"] == model].set_index("zone")
        for zone in naive.index:
            for metric in ("mae", "rmse"):
                base = float(naive.loc[zone, metric])
                value = float(other.loc[zone, metric])
                rows.append(
                    {
                        "model": model,
                        "zone": zone,
                        "metric": metric.upper(),
                        "baseline": base,
                        "model_value": value,
                        "abs_change": value - base,
                        "rel_change_pct": (value - base) / base * 100.0,
                    }
                )
    return pd.DataFrame(rows)


def plot_pred_vs_actual(preds: pd.DataFrame, cjk: bool, out_path: Path) -> None:
    """图 7：测试集片段真实值 vs 预测值（3 区域 × 3 模型，共享同段窗口）。"""
    start, end = pd.Timestamp(FIG7_WINDOW[0]), pd.Timestamp(FIG7_WINDOW[1])
    fig, axes = plt.subplots(3, 3, figsize=(18, 10), sharex="col", sharey="row")
    zone_labels = {"zone1": "Zone 1", "zone2": "Zone 2", "zone3": "Zone 3"}
    for row, zone in enumerate(zone_labels):
        for col, model in enumerate(MODEL_ORDER):
            ax = axes[row][col]
            sub = preds[
                (preds["zone"] == zone)
                & (preds["model"] == model)
                & (preds["target_timestamp"] >= start)
                & (preds["target_timestamp"] <= end)
            ]
            ax.plot(sub["target_timestamp"], sub["actual"], color="black", lw=1.0,
                    label="实际" if cjk else "actual")
            ax.plot(sub["target_timestamp"], sub["predicted"], color="#1f77b4", lw=0.8,
                    label="预测" if cjk else "predicted")
            ax.axhline(0, color="grey", lw=0.3)
            if row == 0:
                ax.set_title(_model_label(model, cjk), fontsize=12)
            if col == 0:
                ax.set_ylabel(f"{zone_labels[zone]} 负荷" if cjk else f"{zone_labels[zone]} load",
                              fontsize=11)
            ax.tick_params(labelsize=8)
            ax.legend(fontsize=8, loc="upper right", ncol=1)
    for ax in axes[-1]:
        ax.xaxis.set_major_formatter(
            matplotlib.dates.DateFormatter("%m-%d %H") if cjk else matplotlib.dates.DateFormatter("%m-%d %H")
        )
    fig.suptitle("图 7  测试集片段：真实负荷 vs 预测负荷（2017-12-14 至 12-17）"
                 if cjk else "Fig 7  Test slice: actual vs predicted (2017-12-14 to 12-17)",
                 fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_residual_scatter(preds: pd.DataFrame, cjk: bool, out_path: Path) -> None:
    """残差（实际−预测）vs 预测值散点，按模型 × 区域布局，用于观察系统偏差。"""
    fig, axes = plt.subplots(3, 3, figsize=(15, 11), sharex="col")
    for row, zone in enumerate(("zone1", "zone2", "zone3")):
        for col, model in enumerate(MODEL_ORDER):
            ax = axes[row][col]
            sub = preds[(preds["zone"] == zone) & (preds["model"] == model)]
            resid = (sub["actual"] - sub["predicted"]).to_numpy()
            ax.scatter(sub["predicted"], resid, s=2, alpha=0.25, color="#1f77b4")
            ax.axhline(0, color="red", lw=1.0, ls="--")
            mean_r = float(np.mean(resid))
            ax.axhline(mean_r, color="orange", lw=1.0)
            ax.set_title(f"{zone} · {_model_label(model, cjk)}", fontsize=10)
            ax.tick_params(labelsize=8)
            if col == 0:
                ax.set_ylabel("残差 (实际−预测)" if cjk else "residual", fontsize=10)
            if row == 2:
                ax.set_xlabel("预测负荷" if cjk else "predicted", fontsize=10)
    fig.suptitle("测试集残差 vs 预测值（红虚线=零线，橙线=均值）"
                 if cjk else "Test residuals vs predicted (red=zero, orange=mean)",
                 fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def total_metrics(preds: pd.DataFrame) -> pd.DataFrame:
    """三区域样本合并口径的测试集指标（协议 7 的补充口径）。"""
    rows = []
    for model in MODEL_ORDER:
        sub = preds[preds["model"] == model]
        rows.append(
            {
                "model": model,
                "zone": "total",
                "mae": mae(sub["actual"], sub["predicted"]),
                "rmse": rmse(sub["actual"], sub["predicted"]),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    cjk = _setup_cjk()
    df = load_clean()
    verify_against_plan(df)

    # 从清洗数据完整重跑，保证可复现
    print("== 重跑历史同期基线与线性回归 ==")
    baseline = run_models(df, list(UNTUNED_MODELS), save=True)
    print(baseline.to_string(index=False))
    print("\n== 重跑梯度提升树（验证集选参） ==")
    gbt = run_gbt_experiment(df, save=True, verbose=False)
    print(gbt.to_string(index=False))

    comparison = pd.concat([baseline, gbt], ignore_index=True)
    comparison = comparison.sort_values(["model", "zone", "split"]).reset_index(drop=True)
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(METRICS_DIR / "model_comparison.csv", index=False)

    preds = load_all_predictions()
    table3 = comparison[comparison["split"] == "test"][["model", "zone", "mae", "rmse"]].copy()
    table3 = pd.concat([table3, total_metrics(preds)], ignore_index=True)
    # 课程要求同时给出 MSE；由 RMSE 平方得到，与逐点计算完全等价
    table3["mse"] = table3["rmse"] ** 2
    table3.to_csv(METRICS_DIR / "report_table3.csv", index=False)

    improvement = improvement_vs_naive(comparison)
    improvement.to_csv(METRICS_DIR / "improvement_vs_naive.csv", index=False)

    fig7 = FIGURES_DIR / "fig7_pred_vs_actual.png"
    resid = FIGURES_DIR / "fig_residual_scatter.png"
    plot_pred_vs_actual(preds, cjk, fig7)
    plot_residual_scatter(preds, cjk, resid)

    print("\n== 表 3：测试集 MAE / RMSE（报告表） ==")
    print(table3.pivot(index="model", columns="zone", values=["mae", "rmse"]).round(2)
          .reindex(index=list(MODEL_ORDER)).to_string())

    print("\n== 相对历史同期基线的误差变化（测试集，正值=误差增大） ==")
    print(improvement.round(2).to_string(index=False))

    print(f"\n[OK] model_comparison.csv -> {METRICS_DIR / 'model_comparison.csv'}")
    print(f"[OK] report_table3.csv   -> {METRICS_DIR / 'report_table3.csv'}")
    print(f"[OK] improvement_vs_naive.csv -> {METRICS_DIR / 'improvement_vs_naive.csv'}")
    print(f"[OK] 图 7 -> {fig7}")
    print(f"[OK] 残差散点 -> {resid}")
    print(f"[OK] 指标源文件（供 C3 复算）：{METRICS_DIR / DEFAULT_METRICS_FILE}、{METRICS_DIR / GBT_METRICS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

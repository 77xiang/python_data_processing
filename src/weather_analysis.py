#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A4 天气与负荷的关系：相关性热力图与温度—负荷分箱曲线。

输入：
    data/processed/power_load_clean.csv

输出：
    outputs/figures/fig5_weather_correlation.png   图 5  天气因子与负荷的相关系数热力图
    outputs/figures/fig6_temperature_relation.png  图 6  温度—负荷散点与分箱均值
    outputs/metrics/weather_correlation.csv        各区负荷与各天气因子的 Pearson / Spearman 系数
    outputs/metrics/temperature_bins.csv           温度分箱后的样本量与平均负荷

只报告统计关系，不涉及因果推断；相关系数未做去趋势处理，仅作描述性指标使用。
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

from src.data_cleaning import load_clean

FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
METRICS_DIR = PROJECT_ROOT / "outputs" / "metrics"

WEATHER = ["temperature", "humidity", "wind_speed", "general_diffuse_flows", "diffuse_flows"]
ZONES = ["zone1_power", "zone2_power", "zone3_power"]
LABELS = {
    "temperature": "温度",
    "humidity": "湿度",
    "wind_speed": "风速",
    "general_diffuse_flows": "总漫射辐射",
    "diffuse_flows": "漫射辐射",
    "zone1_power": "区域 1 负荷",
    "zone2_power": "区域 2 负荷",
    "zone3_power": "区域 3 负荷",
}
ZONE_LABELS = {"zone1_power": "区域 1", "zone2_power": "区域 2", "zone3_power": "区域 3"}
ZONE_COLORS = {"zone1_power": "#c0392b", "zone2_power": "#2471a3", "zone3_power": "#1e8449"}
BIN_WIDTH = 1.0      # 温度分箱宽度（摄氏度）
MIN_BIN_SAMPLES = 50  # 样本太少的温度区间不画均值，避免噪声


def setup_chinese_font() -> None:
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Microsoft YaHei", "SimHei", "SimSun"):
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            break
    else:
        print("[WARN] 未找到中文字体，图中中文可能显示为方块")
    plt.rcParams["axes.unicode_minus"] = False


def spearman(a: pd.Series, b: pd.Series) -> float:
    """秩相关，不依赖 scipy。"""
    return float(a.rank().corr(b.rank()))


def plot_correlation_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    cols = WEATHER + ZONES
    corr = df[cols].corr(method="pearson")

    fig, ax = plt.subplots(figsize=(8.8, 7.2))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)

    labels = [LABELS[c] for c in cols]
    ax.set_xticks(range(len(cols)))
    ax.set_yticks(range(len(cols)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax.set_yticklabels(labels, fontsize=9)

    for i in range(len(cols)):
        for j in range(len(cols)):
            v = corr.values[i, j]
            ax.text(
                j, i, f"{v:.2f}",
                ha="center", va="center", fontsize=8,
                color="white" if abs(v) > 0.55 else "black",
            )

    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
    cbar.set_label("Pearson 相关系数")

    ax.set_title("图 5  天气因子与各区域负荷的相关系数", fontsize=12, pad=12)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "fig5_weather_correlation.png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    return corr


def compute_correlations(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for z in ZONES:
        for w in WEATHER:
            rows.append({
                "zone": z,
                "weather_factor": w,
                "pearson": round(float(df[z].corr(df[w])), 4),
                "spearman": round(spearman(df[z], df[w]), 4),
            })
    return pd.DataFrame(rows)


def temperature_bins(df: pd.DataFrame) -> pd.DataFrame:
    t = df["temperature"]
    lo = np.floor(t.min() / BIN_WIDTH) * BIN_WIDTH
    hi = np.ceil(t.max() / BIN_WIDTH) * BIN_WIDTH
    edges = np.arange(lo, hi + BIN_WIDTH, BIN_WIDTH)
    centers = (edges[:-1] + edges[1:]) / 2
    which = np.digitize(t.values, edges) - 1

    rows = []
    for z in ZONES:
        values = df[z].values
        for idx, center in enumerate(centers):
            mask = which == idx
            n = int(mask.sum())
            if n == 0:
                continue
            rows.append({
                "zone": z,
                "temperature_bin": round(float(center), 1),
                "count": n,
                "mean_load": round(float(values[mask].mean()), 2),
            })
    return pd.DataFrame(rows)


def plot_temperature_relation(df: pd.DataFrame, bins: pd.DataFrame) -> None:
    rng = np.random.default_rng(42)
    sample_idx = rng.choice(len(df), size=min(8000, len(df)), replace=False)
    sample = df.iloc[sample_idx]

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.4), sharey=False)
    for ax, z in zip(axes, ZONES):
        ax.scatter(
            sample["temperature"], sample[z],
            s=4, alpha=0.12, color="#7f8c8d", edgecolors="none",
        )
        part = bins[(bins["zone"] == z) & (bins["count"] >= MIN_BIN_SAMPLES)]
        ax.plot(
            part["temperature_bin"], part["mean_load"],
            color=ZONE_COLORS[z], lw=2.2, marker="o", ms=4,
            label="分箱均值（样本 ≥ %d）" % MIN_BIN_SAMPLES,
        )
        ax.set_title(ZONE_LABELS[z], fontsize=11)
        ax.set_xlabel("温度（℃）")
        ax.grid(alpha=0.3, ls="--")
        ax.legend(frameon=False, fontsize=8, loc="upper center")

    axes[0].set_ylabel("负荷")
    fig.suptitle("图 6  温度与负荷的关系（灰点为抽样散点，折线为 1 ℃ 分箱均值）", fontsize=12)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "fig6_temperature_relation.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    setup_chinese_font()
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_DIR.mkdir(parents=True, exist_ok=True)

    df = load_clean()
    print(f"读入 {len(df):,} 条记录")
    print("缺失检查：", int(df[WEATHER + ZONES].isna().sum().sum()), "个缺失值")

    corr = plot_correlation_heatmap(df)
    table = compute_correlations(df)

    bins = temperature_bins(df)
    plot_temperature_relation(df, bins)

    table.to_csv(METRICS_DIR / "weather_correlation.csv", index=False, encoding="utf-8-sig")
    bins.to_csv(METRICS_DIR / "temperature_bins.csv", index=False, encoding="utf-8-sig")

    print("\n负荷与天气因子的相关系数（Pearson / Spearman）：")
    for z in ZONES:
        part = table[table["zone"] == z]
        cells = "  ".join(
            f"{LABELS[r.weather_factor]} {r.pearson:+.2f}/{r.spearman:+.2f}"
            for r in part.itertuples()
        )
        print(f"  {ZONE_LABELS[z]}：{cells}")

    print(f"\n图已保存到 {FIGURES_DIR}")
    print(f"数字已保存到 {METRICS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A3 负荷时序规律分析：日、周、季节三个尺度。

输入：
    data/processed/power_load_clean.csv（由 src/data_cleaning.py 生成）

输出：
    outputs/figures/fig1_zone_overview.png    图 1  三分区日均负荷全年走势
    outputs/figures/fig2_hourly_profile.png   图 2  日内负荷曲线（工作日 / 周末）
    outputs/figures/fig3_weekday_pattern.png  图 3  星期规律
    outputs/figures/fig4_monthly_pattern.png  图 4  月份规律（分布）
    outputs/metrics/eda_hourly_profile.csv    区 × 是否周末 × 小时 的平均负荷
    outputs/metrics/eda_weekday_profile.csv   区 × 星期的平均负荷
    outputs/metrics/eda_monthly_profile.csv   区 × 月份的平均负荷
    outputs/metrics/eda_summary.csv           各区域的时序特征汇总

只做描述性统计与可视化，不建模、不改变原始取值；除 7 日滑动平均外不做任何平滑。
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data_cleaning import load_clean

FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
METRICS_DIR = PROJECT_ROOT / "outputs" / "metrics"

ZONES = ("zone1_power", "zone2_power", "zone3_power")
ZONE_LABELS = {"zone1_power": "区域 1", "zone2_power": "区域 2", "zone3_power": "区域 3"}
ZONE_COLORS = {"zone1_power": "#c0392b", "zone2_power": "#2471a3", "zone3_power": "#1e8449"}
WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
SEASON_MAP = {
    3: "春季", 4: "春季", 5: "春季",
    6: "夏季", 7: "夏季", 8: "夏季",
    9: "秋季", 10: "秋季", 11: "秋季",
    12: "冬季", 1: "冬季", 2: "冬季",
}
EVENING_HOURS = (18, 19, 20, 21)  # 晚高峰时段，用于工作日/周末对比


# ---------------------------------------------------------------------------
# 准备
# ---------------------------------------------------------------------------

def setup_chinese_font() -> None:
    """挑一个可用的中文字体，避免图里中文变成方块。"""
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Microsoft YaHei", "SimHei", "SimSun"):
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            break
    else:
        print("[WARN] 未找到中文字体，图中中文可能显示为方块")
    plt.rcParams["axes.unicode_minus"] = False


def load_eda_frame() -> pd.DataFrame:
    """读清洗结果并补充时间特征。"""
    df = load_clean()
    ts = df["timestamp"]
    df["hour"] = ts.dt.hour
    df["dow"] = ts.dt.dayofweek          # 0=周一，6=周日
    df["month"] = ts.dt.month
    df["season"] = df["month"].map(SEASON_MAP)
    df["is_weekend"] = df["dow"] >= 5
    return df


# ---------------------------------------------------------------------------
# 图
# ---------------------------------------------------------------------------

def plot_zone_overview(df: pd.DataFrame) -> None:
    """图 1：三分区日均负荷的全年走势，用于看季节趋势与区域量级差异。"""
    daily = df.set_index("timestamp")[list(ZONES)].resample("D").mean()

    fig, ax = plt.subplots(figsize=(12, 4.6))
    for z in ZONES:
        ax.plot(daily.index, daily[z], color=ZONE_COLORS[z], lw=0.7, alpha=0.3)
        ax.plot(
            daily.index,
            daily[z].rolling(7, center=True).mean(),
            color=ZONE_COLORS[z],
            lw=2.0,
            label=ZONE_LABELS[z],
        )

    summer = daily[daily.index.month.isin([6, 7, 8])]
    if len(summer):
        ax.axvspan(summer.index.min(), summer.index.max(), color="#f39c12", alpha=0.08)

    ax.set_title("图 1  三个区域日均负荷的全年走势（浅色为日均值，粗线为 7 日滑动平均）", fontsize=12)
    ax.set_xlabel("日期")
    ax.set_ylabel("负荷")
    ax.grid(alpha=0.3, ls="--")
    ax.legend(loc="upper right", frameon=False, ncol=3)
    ax.margins(x=0.01)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m月"))

    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "fig1_zone_overview.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_hourly_profile(df: pd.DataFrame) -> None:
    """图 2：日内 24 小时平均负荷，工作日与周末分开画。"""
    hourly = {
        False: df[~df["is_weekend"]].groupby("hour")[list(ZONES)].mean(),
        True: df[df["is_weekend"]].groupby("hour")[list(ZONES)].mean(),
    }

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2), sharex=True)
    for ax, z in zip(axes, ZONES):
        for weekend, style, label in ((False, "-", "工作日"), (True, "--", "周末")):
            series = hourly[weekend][z]
            ax.plot(
                series.index, series.values, style,
                color=ZONE_COLORS[z], lw=1.8, marker="o", ms=3, label=label,
            )
        ax.set_title(ZONE_LABELS[z], fontsize=11)
        ax.set_xlabel("小时")
        ax.set_xticks(range(0, 24, 3))
        ax.grid(alpha=0.3, ls="--")

    axes[0].set_ylabel("平均负荷")
    axes[0].legend(frameon=False, loc="upper left")
    fig.suptitle("图 2  日内负荷曲线：工作日与周末对比", fontsize=12)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "fig2_hourly_profile.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_weekday_pattern(df: pd.DataFrame) -> None:
    """图 3：周内各天的平均负荷。"""
    weekly = df.groupby("dow")[list(ZONES)].mean()

    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.0), sharex=True)
    for ax, z in zip(axes, ZONES):
        values = weekly[z].reindex(range(7)).values
        ax.bar(range(7), values, color=ZONE_COLORS[z], alpha=0.85, width=0.62)
        for i, v in enumerate(values):
            ax.text(i, v, f"{v / 1000:.1f}k", ha="center", va="bottom", fontsize=8)
        ax.set_xticks(range(7))
        ax.set_xticklabels(WEEKDAY_LABELS, fontsize=9)
        ax.set_title(ZONE_LABELS[z], fontsize=11)
        ax.grid(axis="y", alpha=0.3, ls="--")
        ax.margins(y=0.15)

    axes[0].set_ylabel("平均负荷")
    fig.suptitle("图 3  周内各天的平均负荷", fontsize=12)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "fig3_weekday_pattern.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_monthly_pattern(df: pd.DataFrame) -> None:
    """图 4：按月份画负荷分布，箱线图看中位数与离散程度。"""
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2), sharex=True)
    for ax, z in zip(axes, ZONES):
        data = [df.loc[df["month"] == m, z].values for m in range(1, 13)]
        bp = ax.boxplot(
            data, patch_artist=True, widths=0.6,
            showfliers=False, medianprops=dict(color="black", lw=1.2),
        )
        for patch in bp["boxes"]:
            patch.set_facecolor(ZONE_COLORS[z])
            patch.set_alpha(0.55)
        ax.set_xticks(range(1, 13))
        ax.set_xticklabels([str(m) for m in range(1, 13)], fontsize=9)
        ax.set_title(ZONE_LABELS[z], fontsize=11)
        ax.set_xlabel("月份")
        ax.grid(axis="y", alpha=0.3, ls="--")

    axes[0].set_ylabel("负荷")
    fig.suptitle("图 4  按月份的负荷分布（箱体为四分位区间，横线为中位数，已隐去离群点）", fontsize=12)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "fig4_monthly_pattern.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 明细数字
# ---------------------------------------------------------------------------

def _to_long(frame: pd.DataFrame, index_name: str, value_name: str) -> pd.DataFrame:
    long = frame.reset_index().melt(id_vars=index_name, var_name="zone", value_name=value_name)
    order = pd.CategoricalDtype(categories=ZONES, ordered=True)
    long["zone"] = long["zone"].astype(order)
    return long.sort_values(["zone", index_name]).reset_index(drop=True)


def write_profiles(df: pd.DataFrame) -> None:
    """按小时 / 星期 / 月份输出明细，供报告取数。"""
    hourly = df.groupby(["hour", "is_weekend"])[list(ZONES)].mean()
    long = hourly.reset_index().melt(
        id_vars=["hour", "is_weekend"], var_name="zone", value_name="mean_load"
    )
    long["zone"] = long["zone"].astype(pd.CategoricalDtype(categories=ZONES, ordered=True))
    long = long.sort_values(["zone", "is_weekend", "hour"]).reset_index(drop=True)
    long["period"] = long["is_weekend"].map({False: "workday", True: "weekend"})
    long[["zone", "period", "hour", "mean_load"]].to_csv(
        METRICS_DIR / "eda_hourly_profile.csv", index=False, encoding="utf-8-sig"
    )

    weekly = df.groupby("dow")[list(ZONES)].mean()
    wlong = _to_long(weekly, "dow", "mean_load")
    wlong["weekday"] = wlong["dow"].map(dict(enumerate(WEEKDAY_LABELS)))
    wlong[["zone", "dow", "weekday", "mean_load"]].to_csv(
        METRICS_DIR / "eda_weekday_profile.csv", index=False, encoding="utf-8-sig"
    )

    monthly = df.groupby("month")[list(ZONES)].mean()
    mlong = _to_long(monthly, "month", "mean_load")
    mlong["season"] = mlong["month"].map(SEASON_MAP)
    mlong[["zone", "month", "season", "mean_load"]].to_csv(
        METRICS_DIR / "eda_monthly_profile.csv", index=False, encoding="utf-8-sig"
    )


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    """各区域时序特征汇总，一行一个区域。"""
    rows = []
    for z in ZONES:
        hourly = df.groupby("hour")[z].mean()
        peak_hour = int(hourly.idxmax())
        trough_hour = int(hourly.idxmin())

        evening = df[df["hour"].isin(EVENING_HOURS)]
        workday_evening = evening.loc[~evening["is_weekend"], z].mean()
        weekend_evening = evening.loc[evening["is_weekend"], z].mean()

        monthly = df.groupby("month")[z].mean()
        seasonal = df.groupby("season")[z].mean()
        weekly = df.groupby("dow")[z].mean()

        rows.append({
            "zone": z,
            "annual_mean": round(df[z].mean(), 2),
            "peak_hour": peak_hour,
            "trough_hour": trough_hour,
            "daily_peak_mean": round(hourly.max(), 2),
            "daily_trough_mean": round(hourly.min(), 2),
            "peak_trough_ratio": round(hourly.max() / hourly.min(), 3),
            "workday_mean": round(df.loc[~df["is_weekend"], z].mean(), 2),
            "weekend_mean": round(df.loc[df["is_weekend"], z].mean(), 2),
            "weekend_effect_pct": round(
                (df.loc[df["is_weekend"], z].mean() / df.loc[~df["is_weekend"], z].mean() - 1) * 100, 2
            ),
            "workday_evening_mean": round(workday_evening, 2),
            "weekend_evening_mean": round(weekend_evening, 2),
            "evening_weekend_gap_pct": round((weekend_evening / workday_evening - 1) * 100, 2),
            "max_month": int(monthly.idxmax()),
            "max_month_mean": round(monthly.max(), 2),
            "min_month": int(monthly.idxmin()),
            "min_month_mean": round(monthly.min(), 2),
            "summer_mean": round(seasonal.get("夏季"), 2),
            "winter_mean": round(seasonal.get("冬季"), 2),
            "summer_winter_ratio": round(seasonal.get("夏季") / seasonal.get("冬季"), 3),
            "max_weekday": WEEKDAY_LABELS[int(weekly.idxmax())],
            "min_weekday": WEEKDAY_LABELS[int(weekly.idxmin())],
            "max_weekday_mean": round(weekly.max(), 2),
            "min_weekday_mean": round(weekly.min(), 2),
            "weekday_weekend_ratio": round(
                weekly.loc[[0, 1, 2, 3, 4]].mean() / weekly.loc[[5, 6]].mean(), 3
            ),
        })
    return pd.DataFrame(rows)


def build_daily_extremes(df: pd.DataFrame) -> pd.DataFrame:
    """每日峰谷时刻的稳定性。

    用来判断日周期是否稳定到可以作为滞后特征的依据：若大部分日子的峰值都落在
    同一时段，说明 24 小时前的同期观测对预测目标有稳定参考价值。
    """
    work = df[["timestamp", "hour"] + list(ZONES)].copy()
    work["date"] = work["timestamp"].dt.date

    rows = []
    for z in ZONES:
        hourly = work.groupby(["date", "hour"])[z].mean().unstack()
        peak = hourly.idxmax(axis=1)
        trough = hourly.idxmin(axis=1)
        daily_peak = hourly.max(axis=1)
        rows.append({
            "zone": z,
            "n_days": int(len(hourly)),
            "peak_hour_mode": int(peak.mode().iloc[0]),
            "peak_share_18_21_pct": round(float(peak.isin([18, 19, 20, 21]).mean() * 100), 1),
            "peak_share_20_pct": round(float((peak == 20).mean() * 100), 1),
            "trough_share_4_7_pct": round(float(trough.isin([4, 5, 6, 7]).mean() * 100), 1),
            "daily_peak_mean": round(float(daily_peak.mean()), 2),
            "daily_peak_cv_pct": round(float(daily_peak.std() / daily_peak.mean() * 100), 1),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> int:
    setup_chinese_font()
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_DIR.mkdir(parents=True, exist_ok=True)

    df = load_eda_frame()
    print(f"读入 {len(df):,} 条记录，{df['timestamp'].min()} 至 {df['timestamp'].max()}")

    plot_zone_overview(df)
    plot_hourly_profile(df)
    plot_weekday_pattern(df)
    plot_monthly_pattern(df)
    write_profiles(df)

    summary = build_summary(df)
    summary.to_csv(METRICS_DIR / "eda_summary.csv", index=False, encoding="utf-8-sig")

    extremes = build_daily_extremes(df)
    extremes.to_csv(METRICS_DIR / "eda_daily_extremes.csv", index=False, encoding="utf-8-sig")

    print("\n分区汇总：")
    print(summary.to_string(index=False))
    print("\n每日峰谷稳定性：")
    print(extremes.to_string(index=False))
    print(f"\n图已保存到 {FIGURES_DIR}")
    print(f"数字已保存到 {METRICS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

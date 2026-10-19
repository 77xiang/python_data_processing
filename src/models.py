#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B3 模型模块：历史同期基线与线性回归。

历史同期基线（seasonal_naive）：
    ŷ(t+6) = y(t+6-1008) = y(t-1002)，即目标时刻的上一周同期负荷。
    只使用预测起点时已经观测到的历史负荷；无训练、无超参。
    不消费特征矩阵，直接按起点行索引从负荷序列取值；
    起点行索引已由协议保证 ≥ 1008（即 t-1002 ≥ 6 ≥ 0，恒可取到）。

线性回归（linear_regression）：
    StandardScaler（只在训练集拟合）+ sklearn.linear_model.LinearRegression；
    特征为协议 3.2 的默认主特征集（历史滞后 + 时间 + 起点时刻天气）；
    无超参，训练过程确定性可复现。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.splits import FORECAST_HORIZON, WEEK_STEPS

SEASONAL_NAIVE = "seasonal_naive"
LINEAR_REGRESSION = "linear_regression"
SUPPORTED_MODELS = (SEASONAL_NAIVE, LINEAR_REGRESSION)

# 历史同期基线取"目标时刻往前 7 天"的负荷：t+6-1008 = t-1002
NAIVE_LAG = WEEK_STEPS - FORECAST_HORIZON


def seasonal_naive_predict(load: np.ndarray, origins: np.ndarray) -> np.ndarray:
    """历史同期基线预测。

    load: 负荷序列（与清洗后数据行序一致）；
    origins: 预测起点行索引（协议保证 ≥ 1008）。
    """
    origins = np.asarray(origins, dtype=int)
    if (origins - NAIVE_LAG).min() < 0:
        raise ValueError(
            "存在起点不足 7 天历史的样本，无法取上一周同期值；"
            "协议规定可用起点必须 ≥ 1008，请检查切分逻辑"
        )
    return load[origins - NAIVE_LAG]


def train_linear_regression(X_train, y_train) -> Pipeline:
    """标准化（仅训练集拟合）+ 线性回归。X_train 可为 DataFrame 或数组。"""
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("regressor", LinearRegression()),
        ]
    ).fit(X_train, y_train)

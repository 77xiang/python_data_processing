# 模型交付报告（B6）

- 负责人：况子昱（成员 B，预测模型与时间序列验证）
- 日期：2026-10-20（本报告为最终版，覆盖成员 C 的 C2/C3 已合并后的仓库状态）
- 依据：[experiment_plan.md](./experiment_plan.md)（实验协议）、[data_interface.md](./data_interface.md)（成员 A 数据接口）
- 本文档所有结论来自当日实际运行与检查（自动化部分见 `tests/test_delivery_check.py`），无预填结果。

## 1. 交付范围

| 文件 | 作用 |
|---|---|
| `src/splits.py` | 时间切分（协议第 4 节）+ 协议一致性校验 `verify_against_plan()` |
| `src/features.py` | 特征构造（协议第 3 节；`include_weather`/`include_candidates` 开关供 C2 消融） |
| `src/models.py` | 历史同期基线、线性回归、梯度提升树（统一训练/预测接口） |
| `src/evaluate.py` | MAE/RMSE 与各模型实验运行（B3/B4） |
| `src/compare.py` | 统一主实验入口（B5）：重跑三模型 + 合并指标 + 图表 |
| `tests/test_splits_features.py` | 切分与索引对齐检查（6 项） |
| `tests/test_models.py` | 模型与输出一致性检查（7 项） |
| `tests/test_delivery_check.py` | 交付与复现检查（6 项，含成员 C 成果交叉核对） |
| `outputs/predictions/predictions_*.csv` | 三个模型的测试集预测（协议 8.1，各 23,133 行） |
| `outputs/metrics/*.csv` | 指标、GBT 调参明细、选定配置、模型对比表 |
| `outputs/figures/fig7_pred_vs_actual.png`、`fig_residual_scatter.png` | 图 7（真实 vs 预测）、残差散点（辅助） |

成员 C 复用本模块的成果（已合并）：`src/ablation.py`（C2）、`src/error_analysis.py`（C3），及其输出（`ablation_results.csv`、`error_*.csv`、图 8/图 9）。

## 2. 复现方式（2026-10-20 实际执行通过）

```bash
# 1. 数据准备：原始 CSV 不入 git，需本地放置于 data/raw/题4_城市电力负荷.csv
# 2. 清洗（成员 A 的 A2 模块，生成 data/processed/power_load_clean.csv）
python src/data_cleaning.py
# 3. 完整主实验（重跑三模型 + 指标 + 图表，约 1–2 分钟）
python src/compare.py
# 4. 检查（共 19 项自动化检查）
python tests/test_splits_features.py
python tests/test_models.py
python tests/test_delivery_check.py
```

实际执行记录：当日从原始数据重新清洗后，`python src/compare.py` 完整重跑**两次**，`predictions_*.csv`、`model_comparison.csv`、`report_table3.csv` 的 MD5 完全一致（GBT 调参明细 `gbt_tuning.csv` 仅墙钟耗时列 `fit_s` 有秒级差异，指标列一致）→ **可复现**。

## 3. 检查清单与结果

| # | 检查项 | 方法 | 结果 |
|---|---|---|---|
| 1 | 特征构造、时间切分、基线、线性回归、梯度提升树、评价代码审查 | 逐文件数据流检查 + 静态模式扫描（shuffle/shift/居中窗口） | 通过：无随机打乱、无未来偏移、无居中窗口；随机性仅 GBT 的 `random_state=42` |
| 2 | 从数据处理模块输出重跑主实验 | 实际执行（第 2 节） | 通过，两次重跑哈希一致 |
| 3 | 三模型测试区间完全一致 | `test_identical_test_intervals` | 通过：起点 2017-11-07 09:50 – 2017-12-30 22:50（目标 10:50 – 23:50），三元组逐一相同 |
| 4 | 无未来负荷/未来天气泄漏 | 特征索引检查（B2 测试）+ 基线复算 + 静态扫描 | 通过：特征全部取自 ≤ 起点时刻；天气为起点同步观测（协议 3.3 假设） |
| 5 | 预处理/特征选择/参数选择未用测试集 | 代码审查 + `test_no_test_usage_in_tuning` | 通过：StandardScaler 仅训练集拟合；GBT 选参仅训练拟合、验证集 RMSE 选优 |
| 6 | 预测文件列名/类型/时间戳/模型标识 | `test_prediction_file_schema` | 通过：协议 8.1 七列；时间戳可解析且 target=origin+1h；float64 无缺失 |
| 7 | 起点→目标→上周同期基线的时间关系 | `test_naive_predictions_match_clean_data` + B1/B2 抽查 | 通过：基线预测 = 目标时刻往前 7 天观测，与清洗数据逐值相等 |
| 8 | 指标与预测文件一致 | `test_metrics_match_predictions` | 通过：从预测文件重算的 MAE/RMSE 与 `model_comparison.csv` 逐值一致 |
| 9 | 成员 C 成果与主实验交叉核对 | `test_member_c_outputs_crosscheck` | 通过（结论见第 6 节） |
| 10 | 运行命令、依赖、配置文档化 | 本报告 + README.md + 实验日志 | 完成 |

## 4. 最终模型配置

- **历史同期基线**：`ŷ(t+6) = y(t-1002)`（目标时刻上一周同期值），无训练、无超参。
- **线性回归**：`StandardScaler`（仅训练集拟合）+ `LinearRegression`，14 个主特征（4 滞后 + 5 时间 + 5 起点天气）。
- **梯度提升树**：`HistGradientBoostingRegressor`，`early_stopping=False`，种子 42，逐区域配置（验证集 RMSE 选优，8 组小网格，见 `outputs/metrics/gbt_tuning.csv`）：

| 区域 | max_iter | learning_rate | max_depth |
|---|---|---|---|
| zone1 | 200 | 0.05 | 5 |
| zone2 | 200 | 0.05 | None（不限深） |
| zone3 | 400 | 0.10 | 5 |

选型说明：经典 `GradientBoostingRegressor` 单次训练 40–108 秒，Hist 版 0.5–3.5 秒（约 30 倍差距），按协议 §6 备选条款改用 Hist 版（同为 scikit-learn 梯度提升树），理由记录于实验日志 EXP-20261019-05。

## 5. 主实验结果摘要（测试集，来自 model_comparison.csv）

| 模型 | Z1 MAE/RMSE | Z2 MAE/RMSE | Z3 MAE/RMSE | 三区合并 MAE/RMSE |
|---|---|---|---|---|
| 历史同期基线 | 831.04/1151.45 | 966.29/1366.37 | 1354.70/2216.34 | 1050.68/1643.67 |
| 线性回归 | 2143.94/2513.42 | 1017.97/1551.77 | 1318.20/1663.91 | 1493.37/1957.37 |
| 梯度提升树 | 1629.97/2244.42 | 1037.39/1681.75 | 1997.36/2386.99 | 1554.91/2126.30 |

相对基线变化（`improvement_vs_naive.csv`，正值=误差增大）：线性回归在 Z1 +158.0%（MAE）、Z2 +5.4%、Z3 −2.7%（RMSE −24.9%，唯一优于基线的组合）；梯度提升树 Z1 +96.1%、Z2 +7.4%、Z3 +47.4%，全部弱于基线。

**关键发现（供 C4 讨论）**：测试期（2017-11 至 12 月）三区域负荷水平相对训练期明显漂移（Z1 均值 33,065→29,056，Z2 20,488→23,529，Z3 20,052→11,949）。周同期基线直接复制上周值，偏差仅 ±110 左右；LR 与 GBT 外推训练期水平，测试期系统性偏差达 +1020/-532/+1670。本特征集下，简单基线总体占优——这一结论与 B3/B4 的诊断、C3 的误差分析自洽，未挑选有利区域或时段报告。

## 6. 与成员 C 的集成核对（B6 检查 8/9）

C2、C3 代码已合并（PR #5），本报告逐项核对结果：

| 核对项 | 结果 |
|---|---|
| C2 复用同一特征接口与切分 | 通过：`ablation.py` 直接调用 `build_zone_samples(include_weather=...)` 与 `src.splits.py` 的切分，未另建测试集 |
| C2 复用同一模型配置 | 通过：GBT 读取 `gbt_config.csv`（含 NaN→None 处理），种子 42；LR 与主实验逐值一致（确定性复现） |
| C3 直接读取 B5 预测文件 | 通过：`error_overall.csv` 中三模型 × 三区域的 MAE/RMSE 与 `model_comparison.csv` 逐值一致，样本数 7,711/区域 |
| 高负荷阈值口径 | 通过：C3 用训练集分布 Q90（Z1 43053 / Z2 27221 / Z3 28239），未针对测试集调阈值 |
| GBT 消融数值漂移 | 已解释：C2 的 GBT 带天气组与主实验有 0.3%–3.1% 的相对漂移（最大 Z2 MAE 3.14%），系 **C 机 sklearn 版本与本机（1.6.1）不同** 所致（HistGradientBoosting 数值随版本微调）；C 已在实验日志 EXP-20261020-01 注明。结构性一致性（区间、样本、LR、C3）全部精确成立 |

**给 C4/报告整合的提醒**：引用 GBT 消融数字时，建议注明"数值随 sklearn 版本有微小漂移，主实验以成员 B 环境（sklearn 1.6.1）输出为准"，或全组统一锁定版本后重跑一次消融（可选，不阻塞报告）。

## 7. 环境与依赖

- 主实验环境（实测）：Python 3.9.6、numpy 1.26.4、pandas 2.3.3、scikit-learn 1.6.1、matplotlib 3.9.4。
- `requirements.txt` 未锁版本；为保证三台机器数值一致，建议在 requirements.txt 中锁定 `scikit-learn==1.6.1`（消融漂移见第 6 节），全组确认后由组长修改。
- 本机安装注意：pip 21.1.3 与系统代理（127.0.0.1:7890）存在已知 SSL 兼容问题，装包请用：
  `NO_PROXY="*" python -m pip install <包名> -i https://mirrors.aliyun.com/pypi/simple/`
- 原始数据与 `data/processed/` 不入 git（.gitignore 已配置），复现需按第 2 节准备数据。

## 8. 未解决问题与说明

1. 测试期水平漂移导致机器学习模型外推失效、同期基线总体占优——这是正式结论而非待修问题，解释与讨论留给 C4。
2. 图 7 与残差散点已做程序化验收（PNG 合法、分辨率正常、Microsoft YaHei 中文字体确认加载）；建议 A5/C5 阶段人工复核视觉效果（图 8/图 9 同理）。
3. `gbt_tuning.csv` 的 `fit_s` 列为墙钟耗时，每次重跑有秒级差异（指标列确定不变）。
4. 数据仅 364 天、单一城市，结论不可外推（与 A1 审计结论一致）。
5. 数据无天气预报字段，起点天气用同步观测代替（协议 3.3 假设），是全部天气特征结论的前提，报告中须写明。
6. 候选扩展特征（`load_lag_3`、`load_roll24_mean`、`load_season7_mean`）已实现但默认关闭，未进入主实验；如需启用须更新协议并重跑（协议 3.2/11.2）。
7. GBT 消融的版本漂移（第 6 节）：建议锁定 sklearn 版本或统一重跑，由全组决定。

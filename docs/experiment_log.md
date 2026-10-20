# 实验日志

写入报告的任何数字和结论，都要能在这里找到对应记录。先登记编号再跑实验，跑完当天补全；记错了不要改旧条目，新开一条更正。

每条记录要写全：编号（EXP-日期-序号）、谁跑的、目的（对应哪个图/表或哪个问题）、数据区间、预处理版本、模型和关键参数、随机种子、指标（注明是验证集还是测试集）、输出文件、备注。

## 记录

| 编号 | 日期 | 负责人 | 目的 | 数据区间 | 预处理 | 模型/配置 | 种子 | 指标 | 输出文件 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|
| EXP-20261019-01 | 10-19 | 徐启翔 | 建报告框架与日志（C1），不产实验结果 | — | — | — | — | — | docs/report_plan.md、docs/experiment_log.md | 框架性工作 |
| EXP-20261019-02 | 10-19 | 况子昱 | 制定预测实验协议（B1），不产实验结果 | 2017 全年；切分边界见 experiment_plan | — | — | — | — | docs/experiment_plan.md | 边界与索引对齐已程序化核对 |
| EXP-20261019-03 | 10-19 | 况子昱 | 历史同期基线（B3，表 3 输入） | 协议边界：训练 01-08 00:00–09-14 20:40；验证–11-07 09:40；测试–12-30 22:50 | —（无特征） | ŷ(t+6)=y(t-1002)，无训练 | —（确定性） | 测试集 MAE/RMSE：Z1 831.04/1151.45；Z2 966.29/1366.37；Z3 1354.70/2216.34 | outputs/predictions/predictions_seasonal_naive.csv、outputs/metrics/baseline_metrics.csv | 索引对齐经 tests/test_models.py 检查 |
| EXP-20261019-04 | 10-19 | 况子昱 | 线性回归基线（B3，表 3 输入） | 同 EXP-20261019-03 | StandardScaler 仅训练集拟合 | LinearRegression 默认参数；14 特征（4 滞后 + 5 时间 + 5 起点天气） | —（确定性） | 测试集 MAE/RMSE：Z1 2143.94/2513.42；Z2 1017.97/1551.77；Z3 1318.20/1663.91 | outputs/predictions/predictions_linear_regression.csv、outputs/metrics/baseline_metrics.csv | 测试集弱于同期基线：区域负荷水平漂移（Z1 均值 33,065→29,056，Z3 20,052→11,949），线性模型外推训练期水平产生系统偏差，如实记录 |
| EXP-20261019-05 | 10-19 | 况子昱 | 梯度提升树（B4，表 3 输入） | 同 EXP-20261019-03 | —（树模型无需标准化） | HistGradientBoostingRegressor（early_stopping=False）；网格 max_iter{200,400}×lr{0.05,0.1}×max_depth{None,5} 共 8 组，按验证集 RMSE 选优；选定 Z1(200,0.05,5)、Z2(200,0.05,None)、Z3(400,0.1,5) | 42 | 测试集 MAE/RMSE：Z1 1629.97/2244.42；Z2 1037.39/1681.75；Z3 1997.36/2386.99 | outputs/predictions/predictions_gradient_boosting.csv、outputs/metrics/gbt_metrics.csv、gbt_tuning.csv、gbt_config.csv | 经典 GBT 单次训练 40–108s，Hist 版 0.5–2.7s，按协议备选条款采用 Hist 版；测试集弱于同期基线（偏差 +1020/-532/+1670），如实记录 |
| EXP-20261019-06 | 10-19 | 况子昱 | 统一模型比较与主实验（B5，表 3/图 7） | 同 EXP-20261019-03 | 复用 EXP-03/04/05 配置 | src/compare.py 从清洗数据完整重跑三模型，同测试区间同目标 | 42（GBT） | 测试集合并口径 MAE/RMSE：基线 1050.68/1643.67；LR 1493.37/1957.37；GBT 1554.91/2126.30 | outputs/metrics/model_comparison.csv、report_table3.csv、improvement_vs_naive.csv；outputs/figures/fig7_pred_vs_actual.png、fig_residual_scatter.png | 相对基线误差变化已计算：仅 Z3 上 LR 的 RMSE 优于基线（-24.93%），其余组合基线占优，未挑选有利区域/时段报告 |

## 参考格式（正式记录时照着写，写完删掉这行）

| EXP-20261022-01 | 10-22 | 况子昱 | 线性回归基线，Zone 1（表 3） | 训练 1–10 月 / 测试 11–12 月（以 experiment_plan 边界为准） | A2 清洗输出 + 滞后/时间特征 | LinearRegression 默认参数 | 42 | 测试集 MAE=… RMSE=… | outputs/metrics/… | 索引对齐已人工抽查 |

## 收尾核对

- [ ] 数据审计和清洗有记录（郑宜桥，A1/A2）
- [ ] 时序与天气分析图表有记录（郑宜桥，A3/A4）
- [ ] 三个模型同一测试集评估（况子昱，B3–B5）
- [ ] 消融实验完成，结果存 outputs/metrics/ablation_results.csv（徐启翔，C2）
- [ ] 误差分析完成（徐启翔，C3）
- [ ] 报告里所有数字都能对上日志

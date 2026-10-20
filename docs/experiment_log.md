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

| EXP-20261020-01 | 10-20 | 徐启翔 | 天气特征消融（C2，表 4/图 9）：LR 与 GBT 在「历史+时间」vs「历史+时间+天气」下对照 | 同 EXP-20261019-03 | 同主实验，仅 include_weather 开关不同 | LR 默认参数；GBT 用 gbt_config.csv 逐区域选定配置；种子 42 | 42 | 测试集 RMSE 变化（B 组 vs A 组）：LR −23.28%/−4.12%/−34.61%（Z1/Z2/Z3）；GBT −22.01%/−7.83%/**+3.24%** | outputs/metrics/ablation_results.csv、ablation_summary.csv、outputs/figures/fig9_ablation.png | 天气仅用起点 t 时刻同步观测；5/6 组合加天气后误差下降，但 GBT 在 Z3 变差（+3.24%），如实报告；LR 结果与主实验 EXP-20261019-04 完全一致（确定性复现），GBT 略有数值漂移（Z1 RMSE 2244.42→2238.00），系本次环境 sklearn 版本与 B 机不同所致 |

| EXP-20261020-02 | 10-20 | 徐启翔 | 分区域与高负荷时段误差分析（C3，图 8 及报告结果段落输入） | 测试集：2017-11-07 09:50–12-30 22:50（起点），三区域 | 直接读 B5 预测文件，不重构造样本；高负荷阈值用训练集负荷分布 Q90 | 对 seasonal_naive/LR/GBT 三模型测试集预测做分组误差分析 | —（确定性统计） | 高负荷阈值（训练集 Q90）：Z1 43053 / Z2 27221 / Z3 28239；GBT bias：Z1 +1020、Z2 −532、Z3 +1670；高峰 vs 普通（GBT/Z2）：RMSE 2761 vs 1125；nRMSE 三区 GBT 7.72%/7.15%/19.98% | outputs/metrics/error_overall.csv、error_by_hour.csv、error_by_dayofweek.csv、error_by_month.csv、error_peak_vs_normal.csv；outputs/figures/fig8_error_by_hour.png、fig8_residual_dist.png、fig8_residual_time.png；docs/error_analysis_findings.md | 阈值只用训练集分布；Z1 测试期高峰样本仅 9 条、Z3 为 0 条（负荷下移所致），高峰结论对这两区仅供参考；指标复算与 B5 记录一致 ✓；文字草稿待 C4 润色 |

| EXP-20261020-03 | 10-20 | 况子昱 | 模型交付与复现检查（B6 重做，覆盖 C2/C3 合并后状态），不产新指标 | 同 EXP-20261019-03 | 从原始数据重新清洗后完整重跑两次 | src/compare.py 统一入口；哈希对比验证可复现 | 42（GBT） | 两次重跑输出哈希一致；19 项自动化检查全过（交付 6 项 + 模型 7 项 + 切分 6 项） | docs/model_delivery_report.md、tests/test_delivery_check.py、README.md | 与 C 交叉核对：C3 指标与主实验逐值一致 ✓；C2 的 LR 与主实验逐值一致 ✓；GBT 消融漂移 0.3%–3.1%（C 机 sklearn 版本差异，EXP-20261020-01 已注明），建议全组锁定 sklearn==1.6.1 |
| EXP-20261020-04 | 10-20 | 郑宜桥 | 负荷时序规律分析（A3，图 1–4、报告第 4 章素材） | 2017 全年，52,416 条 | A2 清洗结果，不做额外变换 | 描述性统计：按小时、星期、月份分组求均值；7 日滑动平均仅用于图 1 展示趋势 | —（确定性） | 不产预测指标；分区特征见 outputs/metrics/eda_summary.csv（峰谷比 1.89/1.89/2.23，周末效应 −3.6%/−8.2%/+1.2%，夏冬比 1.17/1.12/1.59） | outputs/figures/fig1_zone_overview.png、fig2_hourly_profile.png、fig3_weekday_pattern.png、fig4_monthly_pattern.png；outputs/metrics/eda_hourly_profile.csv、eda_weekday_profile.csv、eda_monthly_profile.csv、eda_summary.csv；docs/eda_findings.md | 原始数据未注明负荷单位，数值按原始单位报告；区域 3 的月度下滑含趋势成分，未做季节性归因 |
| EXP-20261020-05 | 10-20 | 郑宜桥 | 天气与负荷关系（A4，图 5–6、报告第 5 章素材） | 2017 全年，52,416 条 | A2 清洗结果，无缺失 | Pearson 与 Spearman 相关；温度按 1 ℃ 分箱求均值，样本 < 50 的箱不参与作图 | —（确定性） | 温度相关 Z1 0.44 / Z2 0.38 / Z3 0.49；6.5→33.5 ℃ 分箱均值 Z1 +69%、Z2 +69%、Z3 +158%；33 ℃ 以上进入平台 | outputs/figures/fig5_weather_correlation.png、fig6_temperature_relation.png；outputs/metrics/weather_correlation.csv、temperature_bins.csv；docs/weather_findings.md | 未观察到低温采暖回升段（3–5 ℃ 负荷不高于 20 ℃ 附近）；相关未去趋势，仅作描述性指标 |

## 参考格式（正式记录时照着写，写完删掉这行）

| EXP-20261022-01 | 10-22 | 况子昱 | 线性回归基线，Zone 1（表 3） | 训练 1–10 月 / 测试 11–12 月（以 experiment_plan 边界为准） | A2 清洗输出 + 滞后/时间特征 | LinearRegression 默认参数 | 42 | 测试集 MAE=… RMSE=… | outputs/metrics/… | 索引对齐已人工抽查 |

## 收尾核对

- [ ] 数据审计和清洗有记录（郑宜桥，A1/A2）
- [ ] 时序与天气分析图表有记录（郑宜桥，A3/A4）
- [x] 三个模型同一测试集评估（况子昱，B3–B5）
- [x] 消融实验完成，结果存 outputs/metrics/ablation_results.csv（徐启翔，C2）
- [x] 误差分析完成（徐启翔，C3）
- [x] 模型交付与复现检查完成（况子昱，B6，见 docs/model_delivery_report.md）
- [ ] 报告里所有数字都能对上日志

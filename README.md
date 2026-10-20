# python_data_processing

课程项目（题目四）：**基于时间序列验证与特征消融的城市短期电力负荷预测研究**。

- 数据：城市电力负荷 CSV（10 分钟采样，2017 年 364 天，含温度/湿度/风速/辐射及三个分区负荷，52,416 行）
- 成员：郑宜桥（A，数据处理与 EDA）、况子昱（B，预测模型与时间序列验证）、徐启翔（C，消融、误差分析与报告整合）
- 协议与文档：[docs/experiment_plan.md](docs/experiment_plan.md)（B1 实验协议）、[docs/model_delivery_report.md](docs/model_delivery_report.md)（B6 交付报告）、[docs/data_audit.md](docs/data_audit.md)、[docs/data_interface.md](docs/data_interface.md)、[docs/report_plan.md](docs/report_plan.md)、[docs/error_analysis_findings.md](docs/error_analysis_findings.md)

## 目录结构

```
data/raw/            原始 CSV（不入 git，需本地放置）
data/processed/      清洗结果（不入 git，运行生成）
src/                 数据处理（A2）、切分与特征（B2）、模型与评价（B3/B4）、
                     统一比较（B5）、天气消融（C2）、误差分析（C3）
tests/               切分/特征、模型、交付三套检查（共 19 项）
outputs/predictions/ 三个模型的测试集预测（协议 8.1）
outputs/metrics/     指标、GBT 调参明细与配置、模型对比表、消融与误差分析结果
outputs/figures/     图 7（真实 vs 预测）、图 8（误差分析）、图 9（消融）、残差散点
docs/                协议、报告计划、实验日志、交付报告、误差分析发现
```

## 复现成员 B 的主实验

```bash
# 1. 将原始数据放入 data/raw/题4_城市电力负荷.csv（不入 git）
# 2. 清洗
python src/data_cleaning.py
# 3. 完整主实验（重跑三模型 + 指标 + 图表）
python src/compare.py
# 4. 检查（19 项）
python tests/test_splits_features.py
python tests/test_models.py
python tests/test_delivery_check.py
```

## 主实验结果（测试集，提前 1 小时预测，详见 model_delivery_report.md）

| 模型 | 三区合并 MAE / RMSE |
|---|---|
| 历史同期基线 ŷ(t+6)=y(t-1002) | **1050.68 / 1643.67** |
| 线性回归（14 特征） | 1493.37 / 1957.37 |
| 梯度提升树（HistGradientBoosting） | 1554.91 / 2126.30 |

测试期（11–12 月）三区域负荷水平相对训练期明显漂移，简单周同期基线总体占优；天气消融（C2）显示天气特征对 LR 有帮助、对 GBT 作用不稳定。细节与解释见实验日志和交付报告。

## 依赖与安装注意

- 依赖见 [requirements.txt](requirements.txt)；主实验环境 Python 3.9.6、numpy 1.26.4、pandas 2.3.3、scikit-learn 1.6.1、matplotlib 3.9.4。
- 跨机器数值一致性建议锁定 `scikit-learn==1.6.1`（见交付报告第 6/7 节）。
- 本机 pip 21.1.3 与系统代理存在已知 SSL 兼容问题，装包请用：
  `NO_PROXY="*" python -m pip install <包名> -i https://mirrors.aliyun.com/pypi/simple/`

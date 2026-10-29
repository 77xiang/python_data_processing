# 城市电力负荷分析与预测

《Python数据分析编程》课程项目（题目四）：**基于时间序列验证与特征消融的城市短期电力负荷预测研究**。

- 成员：郑宜桥（A，数据处理与 EDA）、况子昱（B，预测模型与时间序列验证）、徐启翔（C，消融、误差分析与报告整合）
- 数据：某城市 2017 年电力负荷监测 CSV，10 分钟采样、364 天、52,416 行，含三个分区负荷与温度/湿度/风速/辐射
- 任务：提前 1 小时（6 个采样步）预测三区负荷；按时间顺序 70%/15%/15% 切分并在子集边界剔除起点，比较历史同期基线、线性回归、梯度提升树，辅以特征消融与误差分析

## 主要结果（测试集，三区合并）

| 模型 | MAE | RMSE |
|---|---|---|
| 历史同期基线 ŷ(t+6)=y(t−1002) | 1050.68 | 1643.67 |
| 线性回归（含周同期特征） | **514.09** | **767.16** |
| 梯度提升树（含周同期特征） | 930.62 | 1258.73 |

与预测目标时刻对齐的周同期负荷 y(t−1002) 是最关键的特征；线性回归较基线 MAE/RMSE 下降 51.1%/53.3%，三区全面最优。天气特征对梯度提升树有稳定增益，对线性回归接近中性；高峰时段误差明显更大且倾向低估，详见报告第 6 章。

## 目录结构

```
src/           清洗、EDA、切分与特征、模型评价、消融、误差分析
tests/         28 项自动化检查
data/          原始与清洗数据（不入 git）
outputs/       预测、指标 CSV 与图表（运行生成）
docs/          实验协议、各模块发现与交付文档
deliverables/  项目报告（docx/pdf）、汇报 PPT 与视频
```

## 复现

```bash
pip install -r requirements.txt
# 原始数据放入 data/raw/题4_城市电力负荷.csv（不入 git）

python src/data_cleaning.py       # 清洗
python src/eda.py                 # 时序规律（图 1–4）
python src/weather_analysis.py    # 天气关系（图 5–6）
python src/compare.py             # 主实验：三模型训练、评价与图表
python src/ablation.py            # 天气特征消融
python src/probe_target_week.py   # 目标对齐周同期特征实验
python src/error_analysis.py      # 误差分析（周同期实验加 --tag _tw）

python -m pytest tests/ -q        # 28 项检查
```

实验协议见 [docs/experiment_plan.md](docs/experiment_plan.md)，模型交付细节见 [docs/model_delivery_report.md](docs/model_delivery_report.md)。跨机器复现建议锁定 scikit-learn 1.6.1。

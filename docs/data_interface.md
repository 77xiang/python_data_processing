# 数据接口说明（A2）

本文件是成员 A 提供给成员 B、C 的数据接口约定。B 的特征工程、C 的消融实验都应基于这里的字段和类型，不要各自再定义一套。

## 1. 输入

原始文件：`data/raw/题4_城市电力负荷.csv`（只读，不修改）。

原始列名与清洗后列名的对应关系：

| 原始列名 | 清洗后列名 | 类型 | 含义 |
|---|---|---|---|
| DateTime | timestamp | datetime64[ns] | 时间戳，10 分钟间隔 |
| Temperature | temperature | float64 | 温度 |
| Humidity | humidity | float64 | 湿度 |
| Wind Speed | wind_speed | float64 | 风速 |
| general diffuse flows | general_diffuse_flows | float64 | 总漫射辐射 |
| diffuse flows | diffuse_flows | float64 | 漫射辐射 |
| Zone 1 Power Consumption | zone1_power | float64 | 区域 1 负荷 |
| Zone 2  Power Consumption | zone2_power | float64 | 区域 2 负荷 |
| Zone 3  Power Consumption | zone3_power | float64 | 区域 3 负荷 |

注意：原始列名里 Zone 2、Zone 3 含连续两个空格，清洗时已统一。

## 2. 输出

函数 `clean_data()` 返回 `(DataFrame, DataQualitySummary)`。DataFrame 的列固定为：

```
timestamp,
temperature, humidity, wind_speed, general_diffuse_flows, diffuse_flows,
zone1_power, zone2_power, zone3_power
```

约定：

- 行按 `timestamp` 升序排列，索引重置为 0..n-1。
- `timestamp` 为 `datetime64[ns]`，不带时区。
- 其余列为 `float64`。
- 不删除负荷峰值，不做插值，不做标准化；缺失值保持原样并计入质量摘要。
- 完全重复行会被删除，并在摘要中记录删除数量。
- 同一时间戳对应不同数值时默认报错，避免悄悄丢掉信息。

清洗结果写入 `data/processed/power_load_clean.csv`（该目录不进 Git，需要时本地重新运行生成）。

## 3. 用法

```python
from src.data_cleaning import clean_data, load_clean

df, summary = clean_data()          # 读取 data/raw 下的唯一 CSV，清洗并保存
print(summary.format())

df = load_clean()                   # 直接读取已生成的 data/processed/power_load_clean.csv
```

命令行：

```bash
python src/data_cleaning.py
python src/data_cleaning.py --input data/raw/题4_城市电力负荷.csv --output data/processed/power_load_clean.csv
python src/data_cleaning.py --k 1.5    # 异常标记收紧到 1.5×IQR，只影响 anomaly_flags.csv
```

## 4. 给 B 的提示

- 提前 1 小时预测即 `t+6`，目标列从 `zone1_power`、`zone2_power`、`zone3_power` 中选择。
- 构造滞后特征时只能用 `timestamp <= t` 的观测，滚动窗口不要用居中窗口。
- 天气特征是否可用，取决于预测起点 `t` 时能否获得；本数据是同一条记录里的同步观测，直接用作 `t` 时刻特征时需要说明这一假设。
- 训练/验证/测试必须按时间顺序切分，不要随机打乱。

## 5. 给 C 的提示

- 消融实验建议用 `LOAD_COLUMNS` 与 `WEATHER_COLUMNS` 两个常量分组，避免手写列名。
- 异常点标记见 `data/processed/anomaly_flags.csv`，它只用于说明，不作为模型输入。

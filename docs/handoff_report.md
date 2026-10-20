# 数据模块交接报告（A6）

交付人：郑宜桥（成员 A）
检查时间：2026-10-20
模块范围：数据审计、清洗、时序规律分析、天气关系分析、报告表格

## 1 模块文件清单

| 文件 | 作用 | 产出 |
|---|---|---|
| `src/data_audit.py` | 原始数据质量审计 | `docs/data_audit.md` |
| `src/data_cleaning.py` | 清洗与对外数据接口 | `data/processed/power_load_clean.csv`、`anomaly_flags.csv` |
| `src/eda.py` | 日/周/季节规律、峰谷稳定性 | 图 1–4、`eda_*.csv` 五个 |
| `src/weather_analysis.py` | 天气相关性与温度分箱 | 图 5–6、`weather_correlation.csv`、`temperature_bins.csv` |
| `src/report_tables.py` | 表 1、表 2 生成 | `report_table1.csv`、`report_table2.csv`、`docs/report_tables.md` |

文档：`docs/data_interface.md`（接口约定）、`docs/eda_findings.md`（时序规律结论）、`docs/weather_findings.md`（天气关系结论）、`docs/eda_checklist.md`（A5 检查清单）、`docs/report_draft_A.md`（报告第 2–5 章草稿）。

## 2 从原始 CSV 复现

前置：原始文件放在 `data/raw/题4_城市电力负荷.csv`（不入 git）。`data/processed/` 不存在也能跑，脚本会自动创建。

```bash
python src/data_audit.py --input data/raw/题4_城市电力负荷.csv --output docs/data_audit.md
python src/data_cleaning.py                 # 生成 data/processed/power_load_clean.csv
python src/eda.py                           # 图 1–4 与 eda_*.csv
python src/weather_analysis.py              # 图 5–6 与天气相关 csv
python src/report_tables.py                 # 表 1、表 2
```

所有脚本以 `PROJECT_ROOT = Path(__file__).resolve().parent.parent` 定位路径，从任意工作目录调用都可以，不依赖绝对路径。

## 3 全链路检查结果

从原始 CSV 重新执行上面的命令，检查结果如下。

| 检查项 | 结果 |
|---|---|
| 审计报告可复现 | 除生成时间外，与已提交的 `docs/data_audit.md` 无差异 |
| 清洗输出一致性 | 与上次运行结果 MD5 完全相同 |
| 记录数 | 52,416 行 × 9 列 |
| 时间排序 | 严格升序，无回退 |
| 重复时间戳 | 0 |
| 缺失值 | 0 |
| 输出文件存在性 | 6 张图、9 个 csv 全部生成 |
| 图片可打开 | PIL 逐一读取通过，尺寸 2416×2126 至 4015×1239 |
| csv 行数合理性 | 小时明细 144 行（3 区 × 2 类 × 24 时）、月份明细 36 行（3 区 × 12 月）、星期明细 21 行（3 区 × 7 天），均与预期一致 |

## 4 接口约定（供 B、C 调用）

### 4.1 数据读取

```python
from src.data_cleaning import load_clean, clean_data, iqr_flags, LOAD_COLUMNS, WEATHER_COLUMNS
```

| 函数 / 常量 | 签名 | 返回 |
|---|---|---|
| `load_clean` | `load_clean(path=None) -> pd.DataFrame` | 9 列，`timestamp` 为 datetime64[ns]，其余 float64 |
| `clean_data` | `clean_data(path=None, *, output_path, flags_path, write=True, on_duplicate="raise", k=3.0) -> tuple[pd.DataFrame, DataQualitySummary]` | 清洗后数据 + 质量摘要；传 `write=False` 可只算不写 |
| `iqr_flags` | `iqr_flags(df, columns=None, k=3.0) -> pd.DataFrame` | 长表：timestamp / column / value / rule / lower_bound / upper_bound |
| `LOAD_COLUMNS` | 列表 | `["zone1_power", "zone2_power", "zone3_power"]` |
| `WEATHER_COLUMNS` | 列表 | `["temperature", "humidity", "wind_speed", "general_diffuse_flows", "diffuse_flows"]` |

输出列固定为：`timestamp, temperature, humidity, wind_speed, general_diffuse_flows, diffuse_flows, zone1_power, zone2_power, zone3_power`。

约定：

- 行按 `timestamp` 升序，索引为 0..n-1
- 不插值、不删负荷峰值、不做标准化，缺失值保持原样并计入摘要
- 同一时间戳对应不同数值时默认抛错，避免静默丢数据
- 列名统一为 snake_case，原始列名 `Zone 2  Power Consumption` 中的连续空格已折叠

### 4.2 分析结果

`src/eda.py` 提供 `load_eda_frame()`，在清洗结果上追加 `hour`、`dow`（0=周一）、`month`、`season`、`is_weekend` 五个派生列，可直接复用。

`outputs/metrics/` 下的 csv 均为长表，`zone` 列取值为 `zone1_power` / `zone2_power` / `zone3_power`，数值列统一命名 `mean_load`。

## 5 依赖与版本

| 项目 | 版本 |
|---|---|
| Python | 3.9（本机 3.9.11 验证通过） |
| pandas | 2.3.3 |
| numpy | 随 pandas 环境 |
| matplotlib | 3.9.4 |

`requirements.txt` 中未锁定版本。B 的交付报告建议全组锁定 `scikit-learn==1.6.1`，本模块不涉及 sklearn，无相应风险。

绘图依赖系统安装的中文字体（Microsoft YaHei / SimHei）。`eda.py` 与 `weather_analysis.py` 启动时会探测可用字体，缺失时打印警告但继续运行，此时图中的中文会显示为方块，数字不受影响。

## 6 遗留问题

1. **负荷与气象变量的单位未确认。** 原始数据未标注，表 1 只对温度和湿度按量纲做了判断，其余写“未注明”。报告中所有跨区比较均使用比值，不受影响；若评审要求给出绝对量级的单位，目前无法回答。
2. **区域 3 的月度下滑无法拆分季节性与趋势。** 只有一个年度周期，未做趋势分解。报告中只陈述观测值，不做季节性归因。
3. **报告图注尚未定稿。** `docs/eda_checklist.md` 第 2 节给了每张图的核心观察与局限，需要按报告格式压缩。
4. **图 2、3、4、6 使用三个独立纵轴。** 便于看形状，不利于直接比较幅度，需在图注注明。
5. **`requirements.txt` 未锁版本。** 本模块的数值结果不受影响（确定性统计），但换环境重跑图形样式可能有细微差异。

## 7 实际贡献汇总

| 阶段 | 提交 | 内容 |
|---|---|---|
| A1 | `feat(data): add data audit script and quality report` | 审计脚本与报告 |
| A2 | `feat(data): add cleaning module and data interface spec` | 清洗模块、接口文档 |
| A3 | `A3_feat(analysis): add daily, weekly and seasonal load patterns` | 图 1–4、时序规律 |
| A3 补充 | `A3_feat(analysis): add daily peak and trough stability metrics` | 峰谷稳定性指标 |
| A4 | `A4_feat(analysis): add weather correlation and temperature relation` | 图 5–6、天气关系 |
| 表格 | `A1A2_docs(tables): add report table 1 and 2` | 表 1、表 2 |
| 报告 | `A_docs(report): draft chapters 2-5 (data, cleaning, patterns, weather)` | 报告第 2–5 章草稿 |
| A5/A6 | 本次提交 | 检查清单、交接报告、README 补充 |

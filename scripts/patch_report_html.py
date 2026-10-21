# -*- coding: utf-8 -*-
"""把报告 HTML 里的图表占位段替换为真实表格与图片（图片以 base64 内联），
并补齐第 8.2 节三人的个人承担说明。输出新的 HTML 供 S3 转 docx 使用。
"""
import base64
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "outputs" / "figures"
SRC = ROOT / "output" / "c5-report-word-20261021" / "stage2" / "formatted-城市电力负荷分析与预测.html"
DST = ROOT / "output" / "c5-report-word-20261021" / "stage2" / "formatted-城市电力负荷分析与预测_v2.html"


def b64(name: str) -> str:
    data = (FIG / name).read_bytes()
    return base64.b64encode(data).decode("ascii")


def img(name: str, alt: str) -> str:
    return (
        f'<div class="fig-img"><img src="data:image/png;base64,{b64(name)}" '
        f'alt="{alt}" /></div>'
    )


def cap(text: str) -> str:
    return f'<p class="fig-cap">{text}</p>'


def note(text: str) -> str:
    return f'<p class="fig-note">{text}</p>'


def tab_cap(text: str) -> str:
    return f'<p class="tab-cap">{text}</p>'


TABLE1 = """<table>
<tr><th>序号</th><th>原始列名</th><th>清洗后列名</th><th>类型</th><th>单位</th><th>最小值</th><th>最大值</th><th>均值</th><th>含义</th></tr>
<tr><td>1</td><td class="l">DateTime</td><td class="l">timestamp</td><td>datetime64</td><td>—</td><td>2017-01-01 00:00</td><td>2017-12-30 23:50</td><td>—</td><td class="l">时间戳，10 分钟采样</td></tr>
<tr><td>2</td><td class="l">Temperature</td><td class="l">temperature</td><td>float64</td><td>℃</td><td>3.25</td><td>40.01</td><td>18.81</td><td class="l">气温</td></tr>
<tr><td>3</td><td class="l">Humidity</td><td class="l">humidity</td><td>float64</td><td>%</td><td>11.34</td><td>94.80</td><td>68.26</td><td class="l">相对湿度</td></tr>
<tr><td>4</td><td class="l">Wind Speed</td><td class="l">wind_speed</td><td>float64</td><td>未注明</td><td>0.0500</td><td>6.48</td><td>1.96</td><td class="l">风速</td></tr>
<tr><td>5</td><td class="l">general diffuse flows</td><td class="l">general_diffuse_flows</td><td>float64</td><td>未注明</td><td>0.0040</td><td>1,163.00</td><td>182.70</td><td class="l">总漫射辐射</td></tr>
<tr><td>6</td><td class="l">diffuse flows</td><td class="l">diffuse_flows</td><td>float64</td><td>未注明</td><td>0.0110</td><td>936.00</td><td>75.03</td><td class="l">漫射辐射</td></tr>
<tr><td>7</td><td class="l">Zone 1 Power Consumption</td><td class="l">zone1_power</td><td>float64</td><td>未注明</td><td>13,895.70</td><td>52,204.40</td><td>32,344.97</td><td class="l">区域 1 负荷</td></tr>
<tr><td>8</td><td class="l">Zone 2&nbsp;&nbsp;Power Consumption</td><td class="l">zone2_power</td><td>float64</td><td>未注明</td><td>8,560.08</td><td>37,408.86</td><td>21,042.51</td><td class="l">区域 2 负荷（原列名含连续两个空格）</td></tr>
<tr><td>9</td><td class="l">Zone 3&nbsp;&nbsp;Power Consumption</td><td class="l">zone3_power</td><td>float64</td><td>未注明</td><td>5,935.17</td><td>47,598.33</td><td>17,835.41</td><td class="l">区域 3 负荷（原列名含连续两个空格）</td></tr>
</table>"""

TABLE2 = """<table>
<tr><th>检查项</th><th>结果</th><th>处理方式</th></tr>
<tr><td class="l">原始记录数</td><td>52,416</td><td class="l">—</td></tr>
<tr><td class="l">字段数</td><td>9</td><td class="l">—</td></tr>
<tr><td class="l">时间范围</td><td>2017-01-01 00:00 至 2017-12-30 23:50</td><td class="l">—</td></tr>
<tr><td class="l">时间跨度</td><td>364 天</td><td class="l">—</td></tr>
<tr><td class="l">采样间隔</td><td>10 分钟（1 种）</td><td class="l">无需重采样，保持 10 分钟粒度</td></tr>
<tr><td class="l">缺失值</td><td>0 个</td><td class="l">无缺失，未做插值</td></tr>
<tr><td class="l">完全重复行</td><td>0 行</td><td class="l">重复行整行删除</td></tr>
<tr><td class="l">重复时间戳</td><td>0 个</td><td class="l">无重复，不需要去重</td></tr>
<tr><td class="l">负荷负值</td><td>0 个</td><td class="l">无负值，未做截断</td></tr>
<tr><td class="l">列名规整</td><td>2 处</td><td class="l">Zone 2 / Zone 3 列名的连续空格折叠为单空格，再统一为 snake_case</td></tr>
<tr><td class="l">类型转换失败</td><td>0 个</td><td class="l">全部字段可转为数值，无需人工修正</td></tr>
<tr><td class="l">异常值标记（3×IQR）</td><td>1,708 条</td><td class="l">只标记到 anomaly_flags.csv，不删除、不替换</td></tr>
<tr><td class="l">输出记录数</td><td>52,416</td><td class="l">行按时间升序，索引重置</td></tr>
<tr><td class="l">　其中 diffuse_flows</td><td>1,690 条</td><td class="l">极端点集中在固定时段，按真实波动保留</td></tr>
<tr><td class="l">　其中 zone3_power</td><td>18 条</td><td class="l">极端点集中在固定时段，按真实波动保留</td></tr>
</table>"""

REPLACEMENTS = {
    "表 1": tab_cap("表 1　数据字段说明") + TABLE1
    + note("注：统计范围为 2017 年全年 52,416 条记录。温度与湿度按数值量纲判断为 ℃ 和 %；"
           "风速、两项辐射量与负荷的单位原始数据未注明，本表不做推断。"),
    "表 2": tab_cap("表 2　数据质量与清洗情况") + TABLE2
    + note("注：异常值为 3 倍四分位距规则的统计标记，仅用于提示，清洗阶段不做删除或替换；"
           "负荷峰值属真实用电行为，保留原值。"),
    "图 1": img("fig1_zone_overview.png", "图 1 三个区域日均负荷的全年走势")
    + cap("图 1　三个区域日均负荷的全年走势")
    + note("2017 年 1 月 1 日至 12 月 30 日，52,416 条 10 分钟观测按日取均值；"
           "浅色线为日均值，粗线为 7 日滑动平均；阴影区间为 6—8 月。"),
    "图 2": img("fig2_hourly_profile.png", "图 2 日内负荷曲线")
    + cap("图 2　日内负荷曲线：工作日与周末对比")
    + note("2017 年全年观测按小时取均值，实线为工作日，虚线为周末；"
           "三个子图的纵轴范围各自独立，不宜直接比较幅度。"),
    "图 3": img("fig3_weekday_pattern.png", "图 3 周内各天的平均负荷")
    + cap("图 3　周内各天的平均负荷")
    + note("2017 年全年观测按星期取均值；三个子图纵轴范围独立，跨区域比较请参见第 4.5 节汇总表。"),
    "图 4": img("fig4_monthly_pattern.png", "图 4 按月份的负荷分布")
    + cap("图 4　按月份的负荷分布")
    + note("2017 年全年 10 分钟观测按月份绘制的箱线图，箱体为四分位区间，横线为中位数，"
           "须线延伸至 1.5 倍四分位距，离群点已隐去；三个子图纵轴范围独立。"),
    "图 5": img("fig5_weather_correlation.png", "图 5 天气因子与负荷的相关系数")
    + cap("图 5　天气因子与各区域负荷的相关系数")
    + note("2017 年全年 52,416 条观测计算的 Pearson 相关系数；"
           "色标固定为 −1 至 1，对角线为变量自身相关，数值恒为 1。"),
    "图 6": img("fig6_temperature_relation.png", "图 6 温度与负荷的关系")
    + cap("图 6　温度与负荷的关系")
    + note("灰点为从全年观测中随机抽样的 8,000 条记录，折线为按 1 ℃ 分箱后的负荷均值，"
           "仅保留样本量不少于 50 的区间；三个子图纵轴范围独立。"),
    "表 3 与图 7": img("fig7_pred_vs_actual.png", "图 7 测试集真实负荷与预测负荷")
    + cap("图 7　测试集片段：真实负荷与预测负荷对比")
    + note("2017 年 12 月 14 日至 12 月 17 日的局部片段，三行分别为三个模型、三列为三个区域；"
           "完整测试区间的指标见表 3。"),
    "表 4 与图 9": img("fig9_ablation.png", "图 9 天气特征消融对比")
    + cap("图 9　天气特征消融：测试集 RMSE 对照")
    + note("六个（模型 × 区域）组合的测试集 RMSE，柱高越低越好；"
           "深色为含天气特征组，浅色为不含天气特征组。"),
    "图 8": img("fig8_error_by_hour.png", "图 8a 分小时预测误差")
    + cap("图 8（a）　分小时预测误差（测试集）")
    + note("按目标时刻的小时统计 MAE，三个区域各一子图。")
    + img("fig8_residual_dist.png", "图 8b 残差分布")
    + cap("图 8（b）　残差分布（梯度提升树）")
    + note("残差 = 预测 − 实际，横轴为残差，纵轴为频数；三个区域各一子图。")
    + img("fig8_residual_time.png", "图 8c 残差随时间变化")
    + cap("图 8（c）　残差随时间变化（梯度提升树，日平均）")
    + note("测试集残差按日取均值后按日期排列，用于检查误差是否随时间漂移。"),
}

# 表 3 / 表 4 的表注插到对应表格之前（表题在表上方）
TABLE_CAPTIONS = {
    "<tr><th>模型</th><th>Z1 MAE/RMSE</th>": tab_cap("表 3　三个模型在测试集上的对比")
    + note("注：测试集为 2017-11-07 09:50 至 2017-12-30 22:50，每区域 7,711 个样本，"
           "分别计算 MAE 与 RMSE；加粗为同区域最优。"),
    "<tr><th>模型</th><th>区域 1</th>": tab_cap("表 4　天气特征消融结果")
    + note("注：数值为含天气特征组相对不含天气特征组的测试集 RMSE 变化，"
           "负值表示误差下降；唯一的正值（梯度提升树 · 区域 3）为如实报告。"),
}


def md_to_html(text: str) -> str:
    """把一个成员的 markdown 说明转成 HTML 段落。"""
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        block = block.strip()
        if not block or block.startswith("#"):
            continue
        block = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", block)
        if block.startswith("**") or block.startswith("<b>") and block.endswith("</b>") and "\n" not in block:
            out.append(f'<p class="member-name">{block}</p>')
        else:
            out.append(f'<p class="body-text">{block}</p>')
    return "\n".join(out)


def load_member_sections() -> str:
    a_text = (ROOT / "docs" / "report_chapter8_A.md").read_text(encoding="utf-8")
    a_body = a_text.split("### 郑宜桥（成员 A）", 1)[1]
    a_body = re.sub(r"^#+ .*$", "", a_body, flags=re.M).strip()
    a_html = '<p class="member-name">郑宜桥（成员 A）</p>\n' + md_to_html(a_body)

    d_text = (ROOT / "docs" / "report_draft.md").read_text(encoding="utf-8")
    bc_body = d_text.split("**况子昱（成员 B）**", 1)[1].split("## 9 附录", 1)[0]
    bc_body = bc_body.replace("（此段由徐启翔依据 `docs/model_delivery_report.md` 起草，待本人确认后定稿）", "")
    bc_html = md_to_html(bc_body)
    bc_html = bc_html.replace(
        '<p class="body-text">', '<p class="member-name">况子昱（成员 B）</p>\n<p class="body-text">', 1
    )
    bc_html = bc_html.replace("**徐启翔（成员 C）**", '<p class="member-name">徐启翔（成员 C）</p>', 1)
    bc_html = re.sub(r"</?p class=\"body-text\">\s*<p class=\"member-name\">",
                     '<p class="member-name">', bc_html)
    return a_html + "\n" + bc_html


def main() -> None:
    html = SRC.read_text(encoding="utf-8")

    # 1) 追加图表相关样式
    extra_css = (
        '  .tab-cap { font-family: "SimHei", "SimSun", serif; font-size: 10.5pt; '
        'text-align: center; margin: 12pt 0 4pt; }\n'
        '  .fig-cap { font-family: "SimHei", "SimSun", serif; font-size: 10.5pt; '
        'text-align: center; margin: 6pt 0 3pt; }\n'
        '  .fig-note { font-family: "KaiTi", "SimSun", serif; font-size: 9.5pt; '
        'color: #4b5563; margin: 0 0 12pt; text-indent: 0; }\n'
        '  .fig-img { text-align: center; margin: 12pt 0 4pt; }\n'
        '  .fig-img img { max-width: 100%; }\n'
        '  .member-name { font-family: "SimHei", "SimSun", serif; font-size: 12pt; '
        'font-weight: bold; margin: 14pt 0 4pt; }\n'
    )
    html = html.replace("</style>", extra_css + "</style>")

    # 2) 表 3 / 表 4 表题
    for anchor, caption_html in TABLE_CAPTIONS.items():
        html = html.replace(anchor, caption_html + anchor, 1)

    # 3) 占位段替换
    def repl(m: re.Match) -> str:
        inner = m.group(1)
        for key, value in REPLACEMENTS.items():
            if key in inner:
                print(f"  替换占位：{inner}")
                return value
        print(f"  !! 未识别的占位：{inner}")
        return m.group(0)

    html = re.sub(r'<div class="fig-ph">（此处插入(.+?)）</div>', repl, html)

    # 4) 第 8.2 节正文
    old = html.split('<h2>8.2　个人承担说明</h2>', 1)[1].split("</section>", 1)[0]
    html = html.replace(old, "\n" + load_member_sections() + "\n")

    DST.write_text(html, encoding="utf-8")
    print(f"已写出：{DST}  ({len(html)/1024:.0f} KB)")


if __name__ == "__main__":
    main()

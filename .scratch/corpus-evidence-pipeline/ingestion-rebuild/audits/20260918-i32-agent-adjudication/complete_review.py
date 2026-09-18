"""Build an auditable AI-assisted annotation proposal, never a human approval.

Source selection/semantic judgments below were made after reading the six PDFs.
Whitespace normalization is ONLY for locating spans; stored quotes are raw slices.
No production parser, retriever, model API or database is used.
"""
import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT))
from plugins.corpus.preparation.guard import install

install(HERE / "annotation-guard.json")
NOW = datetime.now(timezone.utc).isoformat()
AUTHOR = "Codex / AI-assisted source review; not a human signature"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def lines(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s]


def write_once(name, value):
    with (HERE / name).open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def compact(text):
    return re.sub(r"\s+", "", text)


sources = load(HERE / "authorized-sources.json")["sources"]
pages = {s["source_id"]: load(HERE / "pages" / (s["source_id"] + ".json")) for s in sources}
M = "2026-08-16_6f14cc14"
G = "2026-09-06_dddc7cd0"
C = "2026-08-13_174b6462"
H = "2026-09-06_f8e31696"
N = "2026-09-06_793b3967"
K = "2026-09-06_cc03f55b"

# id, source, PDF page, first/last text, semantic role. All strings are source anchors,
# not generated quotations. Non-contiguous evidence remains separate records.
SPECS = [
    ("M-identity", M, 1, "贵州茅台（600519）2026年中报点评", "强推（维持）", "company_identity_and_specific_rating"),
    ("M-eps", M, 1, "综上，茅台经营向上明确", "维持一年目标价2030元和“强推”评级。", "forecast_year_value_and_rating"),
    ("M-h1q2", M, 1, "公司公布2026年中报", "172.7亿元，同降6.9%。", "actual_halfyear_vs_quarter"),
    ("M-ownership", M, 7, "本报告涉及股票贵州茅台", "4.06%的股份。", "ownership_direction"),
    ("M-publisher", M, 7, "本报告仅供华创证券有限责任公司", "的客户使用。", "pronoun_definition"),
    ("G-identity", G, 1, "光力科技（300480.SZ）", "2026年中报点评：半导体划片机国内龙头，经营拐点向上", "company_identity"),
    ("G-incentive", G, 1, "公司发布新一期股权激励", "40%/43%/35%）。", "incentive_not_actual_or_broker_forecast"),
    ("G-rating", G, 1, "我们预计公司2026—2028年归母净利润", "首次覆盖给予“优于大市”评级。", "forecast_and_specific_rating"),
    ("G-model-orders", G, 3, "其中，8230已在先进封装领域实现批量应用", "并已形成正式订单。", "model_stage_not_serial_number"),
    ("G-laser", G, 3, "公司已推出激光开槽机9130", "目前，两款设备均处于客户端验证阶段。", "laser_models_and_verification_stage"),
    ("G-ownership", G, 7, "截至2026年6月30日", "际控制人控制比例。", "dated_control_and_exclusions"),
    ("G-table-eps", G, 20, "关键财务与估值指标", "每股收益(0.32)0.110.360.590.93", "table_headers_and_eps_row"),
    ("G-table-cash", G, 20, "经营活动现金流176(105)(222)(138)(17)", "经营活动现金流176(105)(222)(138)(17)", "cashflow_row_parentheses_negative"),
    ("G-table-cash-header", G, 20, "现金流量表（百万元）", "2028E", "table_unit_and_forecast_columns"),
    ("G-2027-forecast", G, 16, "我们以2027年盈利预测2.19亿元为参考", "32.54-39.98元。", "hard_negative_forecast_not_audited_actual"),
    ("C-table-title", C, 10, "图6：重点化工品景气一览表（续表）", "图6：重点化工品景气一览表（续表）", "table_identity"),
    ("C-footnote1", C, 10, "注1：", "2026年7月27日", "percentile_window"),
    ("C-footnote2", C, 10, "注2：", "2026年6月取平均", "alternative_operating_rate_windows"),
    ("C-footnote3", C, 10, "注3：", "的产能为配额", "quota_not_production"),
    ("C-years", C, 10, "202320242025202420252026E", "202320242025202420252026E", "consumption_then_capacity_headers"),
    ("C-columns", C, 10, "产能（万吨/年）以及同比增长", "价格分位价差分位开工率", "table_unit_and_metric_headers"),
    ("C-soda", C, 10, "纯碱0.0%0.0%82.9%", "纯碱0.0%0.0%82.9%", "soda_three_metrics"),
    ("C-r32", C, 10, "R3299.6%", "R3299.6%", "r32_percentile"),
    ("C-r32-capacity", C, 10, "24.028.528.5-18.8%0.0%", "24.028.528.5-18.8%0.0%", "r32_capacity_sequence_visual_binding"),
    ("C-urea", C, 10, "尿素32.1%10.9%89.9%", "尿素32.1%10.9%89.9%", "urea_operating_rate"),
    ("C-urea-capacity", C, 10, "5814.26728.36759.67696.07956.08068.0", "5814.26728.36759.67696.07956.08068.0", "urea_consumption_and_capacity_sequence_visual_binding"),
    ("C-report-date", C, 3, "2026-08-10", "2026-08-10", "printed_date_not_filename"),
    ("H-date", H, 1, "2026年09月06日", "2026年09月06日", "report_year_context"),
    ("H-indices1", H, 1, "本周，Wind新材料指数收报5611.65点", "环比下跌4.2%。", "index_name_and_weekly_change"),
    ("H-indices2", H, 1, "六个子行业中，申万三级行业半导体材料指数", "9.12%；", "semiconductor_index_and_change"),
    ("H-ptfe", H, 1, "近期，据业内供应链消息", "RubinUltra预计于2027年推出。", "attributed_plan_not_contract"),
    ("H-argon", H, 1, "国内氩气市场又走出一轮暴涨行情。", "幅超过240%。", "dated_argon_price_change_not_annual_average"),
    ("H-samsung-contract", H, 6, "三星电机于9月1日宣布", "该公司并未透露客户身份。", "different_party_and_product_contract"),
    ("H-resin-capacity", H, 7, "由于市场需求和公司战略发展需要", "2840t/a。", "different_material_capacity_not_purchase"),
    ("N-date", N, 1, "2026年9月5日", "2026年9月5日", "printed_date_not_filename"),
    ("N-event", N, 1, "2026年9月4日，美国劳工部公布2026年8月非农数据", "前值升3.2%。", "event_month_values_and_revision"),
    ("N-causal", N, 1, "从加息角度看", "胀数据变得更为关键。", "strong_employment_causal_assessment"),
    ("N-condition-probability", N, 1, "8月超预期的非农数据、回升的劳动参与率、处于低位的失业率数据，都指向就业市场韧性", "率已经超过60%。", "conditional_assessment_and_market_probability"),
    ("N-participation", N, 1, "8月劳动参与率为61.6%", "高于上月的61.4%", "labor_participation"),
    ("N-month-header", N, 3, "2026/022026/032026/042026/052026/062026/072026/08", "2026/022026/032026/042026/052026/062026/072026/08", "employment_table_month_headers"),
    ("N-month-values", N, 3, "新增非农总计-15621414863312116271", "新增非农总计-15621414863312116271", "employment_july_revised_21_thousand"),
    ("N-probability-chart", N, 5, "图4：非农数据公布后", "2026年9月5日上午）", "CME_conditional_meeting_probabilities_image"),
    ("N-conflict", N, 5, "2026年8月非农就业人口为+16.2万人", "高于前值的+5.6万人。", "source_internal_conflict_not_corrected"),
    ("K-date", K, 1, "宏观专题2026年09月06日", "宏观专题2026年09月06日", "report_year_context"),
    ("K-subjects", K, 1, "这五个主体分别是政府", "我们本篇报告关注前面四个主体。", "five_subjects_and_four_scope"),
    ("K-path1", K, 1, "一、路径1：带动财政支出增加", "一、路径1：带动财政支出增加", "first_convergence_path"),
    ("K-path2", K, 1, "二、路径2：缓解城投化债压力", "二、路径2：缓解城投化债压力", "second_convergence_path"),
    ("K-path3", K, 1, "三、路径3：带动企业投资增加", "三、路径3：带动企业投资增加", "third_convergence_path"),
    ("K-path4", K, 2, "四、路径4：带动居民支出增加", "四、路径4：带动居民支出增加", "fourth_convergence_path"),
    ("K-bottlenecks", K, 1, "2、路径1的堵点在哪？", "的税收）偏低，不利于财政收入增加。", "two_fiscal_bottlenecks"),
    ("K-fiscal", K, 1, "3、财政的支出现状如何？", "仍低于名义GDP增速。", "fiscal_forecast"),
    ("K-sample", K, 1, "3、国企的支出现状如何？", "低于2024年的6.2%。", "specific_sample_and_year_growth"),
    ("K-propensity", K, 2, "3、居民支出的现状如何？", "83.7%以及2019年同期的110.3%。", "two_formulas_and_six_ratios"),
    ("K-investment", K, 2, "3、固定资产投资的现状如何？", "增速为-29.4%。", "investment_metrics"),
    ("K-risk", K, 2, "风险提示：", "可能存在其他收敛路径。", "sample_representativeness_and_alternative_paths"),
    ("K-property-note", K, 11, "注：购房数据使用商品房销售数据", "不包含二手房销售数据", "aggregate_property_basis_not_household_microdata"),
]


def locate(spec):
    eid, sid, number, start_text, end_text, role = spec
    page = pages[sid]["pages"][number - 1]
    raw = page["text"]
    positions = [i for i, char in enumerate(raw) if not char.isspace()]
    normalized = "".join(raw[i] for i in positions)
    first = compact(start_text)
    last = compact(end_text)
    start = normalized.find(first)
    assert start >= 0, (eid, "start", first)
    end = normalized.find(last, start)
    assert end >= 0, (eid, "end", last)
    end += len(last)
    lo, hi = positions[start], positions[end - 1] + 1
    quote = raw[lo:hi]
    return {"evidence_id": eid, "source_id": sid,
            "source_sha256": pages[sid]["sha256"], "page": number,
            "char_start": lo, "char_end_exclusive": hi, "quote": quote,
            "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(), "role": role,
            "text_artifact": f"pages/{sid}.json", "text_artifact_sha256": digest(HERE / "pages" / f"{sid}.json"),
            "image_artifact": f"pages/{sid}-p{number}.png",
            "image_sha256": digest(HERE / "pages" / f"{sid}-p{number}.png"),
            "independent_reader_contains_whitespace_normalized_quote": compact(quote) in compact(page["independent_text"]),
            "normalization_note": "仅定位时忽略空白；quote为pymupdf原始文本连续切片，未拼接/改字；表格对应另见visual_mappings。"}


QUESTIONS = {
 "company-001": (["M-identity", "M-eps"], "报告预测2026/2027/2028年EPS分别67.74/70.77/73.84元；一年目标价2030元，维持强推。"),
 "company-002": (["M-h1q2"], "2026H1：总收入922.8亿元，同比+1.3%；归母445.2亿元，同比-2.0%。单Q2：总收入375.8亿元，同比-5.2%；归母172.7亿元，同比-6.9%。"),
 "company-003": (["G-table-eps", "G-table-cash", "G-table-cash-header"], "第20页预测列2026E/2027E/2028E：EPS为0.36/0.59/0.93元；经营活动现金流为-222/-138/-17百万元。括号表示负数，保留年度及两种单位。"),
 "company-004": (["G-incentive"], "股权激励2026/2027/2028年营业收入触发值为8.84/12.06/15.81亿元，目标值9.38/13.4/18.09亿元。13.4与题目13.40等值；这些是激励考核口径，不是实际收入或券商盈利预测。"),
 "company-005": (["G-model-orders", "G-laser"], "8230已在先进封装批量应用；8231支持晶圆全切、DBG半切、Edge Trimming，已形成正式订单。9130用于Low-k晶圆表面开槽；9320用于超薄硅晶圆、碳化硅、氮化镓和MEMS隐切；后二者仍在客户验证。"),
 "company-006": (["G-ownership"], "截至2026-06-30，赵彤宇直接持有32.60%，经全资宁波万丰隆间接控制4.00%，合计控制36.60%；亲属陈淑兰1.70%、赵彤亚0.57%未计入。"),
 "company-007": (["M-ownership", "M-publisher"], "茅台集团持有华创云信4.06%；华创云信是报告中的‘本公司’即华创证券的控股股东。不可颠倒为华创证券持有茅台集团。"),
 "company-008": (["M-identity", "M-eps", "G-identity", "G-rating"], "华创对贵州茅台：强推、维持；国信对光力科技：优于大市、首次覆盖。以两份报告的具体评级和公司身份取证，不以评级定义页代替。"),
 "industry-001": (["C-table-title", "C-columns", "C-soda", "C-footnote1", "C-footnote2"], "图6续表纯碱：价格分位0.0%、价差分位0.0%、开工率82.9%。前两者是历史分位，不是涨幅；开工率为注2所列两个备选窗口的平均，不擅自确定品种窗口。"),
 "industry-002": (["C-table-title", "C-columns", "C-years", "C-r32", "C-r32-capacity", "C-footnote1", "C-footnote3"], "R32价格分位99.6%，统计窗口2016-01-01至2026-07-27；2026E产能列28.5万吨/年，注3说明为配额，不能改称实际产量。"),
 "industry-003": (["C-table-title", "C-columns", "C-years", "C-urea", "C-urea-capacity"], "尿素开工率89.9%；2026E产能8068.0万吨/年。开工率与产能是不同列，E表示预测列，不能混为产量。"),
 "industry-004": (["C-footnote1", "C-footnote2"], "价格/价差分位窗口为2016-01-01至2026-07-27。开工率为2026-01-01至07-26平均，或2026年1—6月平均；原文没有逐品种分配二选一窗口，不作分配。"),
 "industry-005": (["H-date", "H-argon"], "氩气价格从2026年5月初720元/吨升至9月2日2459元/吨；约4个月，报告称超过240%。不能泛化为全部特气或单日涨幅。"),
 "industry-006": (["H-ptfe"], "报告援引业内供应链消息：英伟达计划在NVSwitch板卡使用PTFE，并将其作为Rubin Ultra正交背板主力选材；Rubin Ultra预计2027年推出。保留消息归属、计划、预计。"),
 "industry-007": (["H-indices1", "H-indices2"], "本周Wind新材料指数5611.65点、环比-4.2%；申万三级半导体材料指数12576.94点、环比-9.12%。指数名、水平值与环比不得错配。"),
 "industry-008": (["C-columns", "C-r32", "C-footnote1", "H-date", "H-argon"], "不能比较为同一涨幅。R32的99.6%是2016-01-01至2026-07-27历史价格分位；氩气超过240%为2026年5月初720至9月2日2459元/吨的区间价格涨幅。两份材料分别取证。"),
 "macro-001": (["N-event", "N-month-header", "N-month-values"], "按首页事件段并结合第3页月度表：2026年8月新增非农16.2万人，预期5.6万人；前月7月由-2.3万人修订为2.1万人。第5页将5.6写为前值，与第1/3/4页不一致，应附来源内部冲突提示，不把错误前值当成另一个正确答案。"),
 "macro-002": (["N-event", "N-participation"], "报告所述2026年8月：失业率4.1%、前值4.1%；劳动参与率61.6%、前值61.4%；平均时薪同比3.1%、前值3.2%。这不是本次对外部统计真实性的认证。"),
 "macro-003": (["N-causal", "N-condition-probability"], "报告认为强就业减少加息顾虑；若后续通胀下行幅度有限，9月加息可能性难忽视。另称非农公布后市场预期概率超过60%。这是附条件判断与市场预期，不是正式决定。"),
 "macro-004": (["K-subjects", "K-path1", "K-path2", "K-path3", "K-path4"], "五主体：政府、准财政、企业、居民、海外；报告聚焦前四者。四路径：带动财政支出增加、缓解城投化债压力、带动企业投资增加、带动居民支出增加。四个标题分别取证，不伪装为一条连续引文。"),
 "macro-005": (["K-fiscal", "K-bottlenecks"], "预计2026年两本账支出增速约-0.5%，低于名义GDP增速；财政收入依赖旧动能并受其下行拖累，新动能综合税负偏低。支出数字保留预测属性。"),
 "macro-006": (["K-sample", "K-risk"], "偏头部发债企业样本：央企2025年有息负债增速4.6%，低于2024年5.9%；地方国企6.1%，低于6.2%。不能推广为全国所有国企。"),
 "macro-007": (["K-date", "K-propensity", "K-property-note"], "消费倾向=消费/可支配收入，2026/2025/2019年Q2分别67.5%/68.6%/70.5%；支出倾向=(消费+新房购房)/可支配收入，分别80.3%/83.7%/110.3%。当年由报告日期及第11页图例2026共同绑定，不混用两个公式。"),
 "macro-008": (["K-date", "K-investment", "K-risk"], "2026年1—6月本年施工项目计划总投资累计同比-4.3%，本年新开工项目计划总投资增速-29.4%；上市公司/发债企业样本代表性可能欠佳、结论可能偏差，也可能存在其他收敛路径。"),
}

NEGATIVES = {
 "company-009": (["G-rating", "G-2027-forecast"], "缺少2027年全年经审计实际归母净利润。第1、13—18、20页涉及未来利润/估值，2.19亿元明确为盈利预测；历史财务截至2026H1，没有对应2027年审计实绩。"),
 "company-010": (["G-model-orders"], "缺少首笔8231正式订单所涉设备的唯一序列号。第2—6页型号、产品示意图和特点，第11—14页订单/销量/预测均未把某个唯一编号绑定首单；示意图的8231属于产品型号，不是首单设备serial。"),
 "industry-009": (["H-date", "H-argon"], "缺少2027年实际全年氩气均价。第1/7页为2026年5月初和9月2日点价；第3—5、8—9页图表是指数、公司股价涨跌、半导体销售及存储器价格，不是2027年氩气年度均价。"),
 "industry-010": (["H-ptfe", "H-samsung-contract", "H-resin-capacity"], "缺少英伟达已签PTFE采购合同及确切吨数。第1/6页只有供应链选材计划；第6页实际合同为三星电机MLCC且客户未披露，第7页2840t/a是松下环氧模塑料产能，均不能替代英伟达PTFE合同量。"),
 "macro-009": (["N-date", "N-condition-probability", "N-probability-chart"], "缺少已公布的2026年9月美联储最终利率决定。第1/3/4页是判断/预期；第5页CME表标题明确CONDITIONAL MEETING PROBABILITIES，更新截至9月5日，9月16日行60.2%是概率不是决议。全文其他页面未补出最终决定。"),
 "macro-010": (["K-propensity", "K-property-note"], "缺少2026Q2中国居民逐户新房支出明细。第2/10页给宏观比率，第11页图13是季度汇总曲线，购房口径为商品房销售、不含二手房；其他图表是企业/财政/居民汇总分析，不能反推逐户微观数据。"),
}

# Narrow per-facet choices; answer constraints deliberately produce NO evidence target.
FACET_REFS = {
 "company-001-01": ["M-eps"], "company-004-01": ["G-incentive"],
 "company-004-02": ["G-incentive"],
 "company-008-01": ["M-identity", "M-eps", "G-identity", "G-rating"],
 "company-008-03": ["M-identity", "M-eps"], "company-008-04": ["G-identity", "G-rating"],
 "industry-001-01": ["C-columns", "C-soda", "C-footnote1", "C-footnote2"],
 "industry-002-01": ["C-footnote3"], "industry-002-02": ["C-footnote1"],
 "industry-003-01": ["C-columns", "C-years", "C-urea", "C-urea-capacity"],
 "industry-004-01": ["C-footnote1"], "industry-004-02": ["C-footnote2"],
 "industry-006-01": ["H-ptfe"], "industry-006-02": ["H-ptfe"], "industry-006-03": ["H-ptfe"],
 "industry-008-01": ["C-columns", "C-r32", "C-footnote1"],
 "industry-008-02": ["C-columns", "C-r32", "C-footnote1", "H-date", "H-argon"],
 "industry-008-03": ["C-columns", "C-r32", "C-footnote1"],
 "macro-001-01": ["N-event", "N-month-header", "N-month-values"],
 "macro-003-01": ["N-condition-probability"], "macro-003-02": ["N-causal"],
 "macro-003-03": ["N-condition-probability"], "macro-004-01": ["K-subjects"],
 "macro-004-02": ["K-subjects"],
 "macro-004-03": ["K-path1", "K-path2", "K-path3", "K-path4"],
 "macro-005-01": ["K-bottlenecks"], "macro-006-01": ["K-sample", "K-risk"],
 "macro-008-01": ["K-risk"],
}


def main():
    protected = ["source-gold-frozen.jsonl", "query-gold-frozen.jsonl", "guards/i3.json",
                 "freezes/freeze-manifest.json", "freezes/i0c-r25.json",
                 "i3-2/evidence-targets-candidates.json", "i3-2/approval-report.json"]
    before = {p: digest(BASE / p) for p in protected}
    initial = load(HERE / "adjudication-draft.json")
    for key, name in [("source_gold_sha256", "source-gold-frozen.jsonl"),
                      ("query_gold_sha256", "query-gold-frozen.jsonl"),
                      ("candidates_sha256", "i3-2/evidence-targets-candidates.json"),
                      ("guard_sha256", "guards/i3.json")]:
        assert initial["based_on"][key] == before[name], (key, "changed since initial draft")
    evidence = [locate(spec) for spec in SPECS]
    by_eid = {e["evidence_id"]: e for e in evidence}
    assert len(by_eid) == len(evidence)
    gold = lines(BASE / "query-gold-frozen.jsonl")
    candidates = load(BASE / "i3-2/evidence-targets-candidates.json")
    visual = [
        {"id": "V-G20", "source_id": G, "page": 20, "evidence_ids": ["G-table-eps", "G-table-cash", "G-table-cash-header"],
         "bindings": {"years": ["2026E", "2027E", "2028E"], "每股收益_元": ["0.36", "0.59", "0.93"], "经营活动现金流_百万元": ["(222)", "(138)", "(17)"]},
         "judgment": "逐行列目视核对，三列位于2024/2025之后；括号负数与历史亏损/EPS表现一致；不改quote里的括号。"},
        {"id": "V-C10", "source_id": C, "page": 10, "evidence_ids": ["C-table-title", "C-columns", "C-years", "C-soda", "C-r32", "C-r32-capacity", "C-urea", "C-urea-capacity"],
         "bindings": {"纯碱": {"价格分位": "0.0%", "价差分位": "0.0%", "开工率": "82.9%"}, "R32": {"价格分位": "99.6%", "产能2026E_万吨每年": "28.5"}, "尿素": {"开工率": "89.9%", "产能2026E_万吨每年": "8068.0"}},
         "judgment": "表头/单元格/脚注目视核对；文本抽取顺序错位，数值列绑定由本记录承担，不能宣称裸数字quote自行含有指标身份。"},
        {"id": "V-N3", "source_id": N, "page": 3, "evidence_ids": ["N-month-header", "N-month-values"],
         "bindings": {"2026/07_新增非农总计_千人": "21", "2026/08_新增非农总计_千人": "162"},
         "judgment": "第3页图1的千人单位和月份表头结合首页前值修订句，21千人=2.1万人。"},
        {"id": "V-K11", "source_id": K, "page": 11, "evidence_ids": ["K-date", "K-propensity", "K-property-note"],
         "bindings": {"current_year": "2026", "legend": "红色2026，蓝色2025，灰色2024，深蓝2019"},
         "judgment": "正文‘2季度’由第1页报告年份和第11页图例共同绑定2026年；不是从文件名补年份。"},
        {"id": "V-K10", "source_id": K, "page": 10, "evidence_ids": ["K-date", "K-investment"],
         "bindings": {"current_year": "2026", "本年施工项目计划总投资_6月累计同比": "-4.3", "本年新开工项目计划总投资_6月累计同比": "-29.4"},
         "judgment": "图10红色2026曲线截至6月与第2页摘要互证；不从文件mtime猜年份。"},
    ]
    facet_reviews = []
    for question in candidates["questions"]:
        for pending in question["pending_human"]:
            short = pending["item_id"].removeprefix("I32-")
            answer_side = pending["kind"] == "answer_constraint"
            refs = [] if answer_side else FACET_REFS[short]
            if pending.get("source_id") and refs:
                assert {by_eid[e]["source_id"] for e in refs} == {pending["source_id"]}
            reason = ("接受此答案侧约束；无需伪造原文说过同样的否定句，不投影证据目标；实际答案合规仍需I3-5验收。"
                      if answer_side else QUESTIONS[question["query_id"]][1])
            facet_reviews.append({"item_id": pending["item_id"], "query_id": question["query_id"],
                "facet_id": pending.get("facet_id"), "kind": pending["kind"],
                "recommendation": "accept_answer_constraint" if answer_side else "accept_with_source_evidence",
                "status": "ai_reviewed_pending_user_adoption", "evidence_ids": refs,
                "reason": reason, "human_approved": False})
    question_reviews = []
    for q in gold:
        qid = q["query_id"]
        if qid not in QUESTIONS:
            continue
        refs, answer = QUESTIONS[qid]
        assert set(q["relevant_sources"]).issubset({by_eid[e]["source_id"] for e in refs}), qid
        question_reviews.append({"query_id": qid, "question": q["question"],
            "evidence_requirement": q["evidence_requirement"], "evidence_ids": refs,
            "reference_answer_proposed": answer, "status": "supported_pending_user_adoption",
            "visual_mapping_ids": [v["id"] for v in visual if set(v["evidence_ids"]) & set(refs)],
            "human_approved": False})
    coverage = [{"source_id": s["source_id"], "source_sha256": s["sha256"],
        "pages": list(range(1, len(pages[s["source_id"]]["pages"]) + 1)),
        "method": "全文文本阅读（pymupdf/pdfplumber交叉抽取）+全页缩略图筛查+相关表格/段落原页目视；非关键词空命中推断",
        "visual_screening": "all_page_contact_sheets", "raw_source_path": s["path"]} for s in sources]
    negatives = []
    for q in gold:
        if q["query_id"] not in NEGATIVES:
            continue
        refs, reason = NEGATIVES[q["query_id"]]
        negatives.append({"query_id": q["query_id"], "question": q["question"],
            "evidence_requirement": q["evidence_requirement"],
            "recommendation": "retain_no_answer_within_frozen_six_sources",
            "reason": reason, "near_miss_evidence_ids": refs,
            "coverage_source_ids": [s["source_id"] for s in sources],
            "ai_full_document_scope_review_completed": True, "human_approved": False,
            "scope_limit": "只断言这六份冻结文件未提供满足全部限定的证据；不是证明世界上不存在事实，也不覆盖留出集/其他语料/未来修订。"})
    status_note = {"gold_id": "macro-039-claim-001", "resolution_proposed": "用本次独立AI原文核验记录补充，待用户采纳；不判定原xyl签名意图",
        "evidence_ids": ["K-subjects", "K-fiscal", "K-sample"],
        "reason": "原记录human_basis称待真人复核但有xyl签名。本次可核验内容，不可替原签名人证明此前只是笔误。原记录不删改，新版本须明确用户采纳与AI贡献。",
        "human_approved": False}
    supplements = {"artifact": "i3-2-source-supplements-PROPOSED-NOT-FROZEN",
        "reviewer": AUTHOR, "reviewed_at": NOW, "based_on": initial["based_on"],
        "source_read_audit_sha256": digest(HERE / "source-read-audit.json"),
        "spans": evidence, "visual_mappings": visual,
        "note": "补证来自原PDF而非入库/清洗/检索输出。图表关系经AI目视核对；不是机器语义证明或人工批准。"}
    # Proposed source-gold extension is append-only. Old signatures remain ONLY on
    # unchanged old rows; all new rows are explicitly authored by AI, never xyl.
    source_gold = lines(BASE / "source-gold-frozen.jsonl")
    proposed_gold = copy.deepcopy(source_gold)
    groups = {}
    for e in evidence:
        domain = "company" if e["source_id"] in (M, G) else "industry" if e["source_id"] in (C, H) else "macro"
        group = groups.setdefault((e["source_id"], e["page"]), {
            "gold_id": f"{domain}-ai-supplement-{e['source_id']}-p{e['page']}",
            "source_id": e["source_id"], "source_sha256": e["source_sha256"],
            "annotation_role": "body_evidence", "locator": {"page": str(e["page"])},
            "expected_items": [], "must_preserve": True, "reviewer": AUTHOR,
            "reviewed_at": NOW, "human_basis": "AI辅助核验提案，未经用户最终签认；不构成真人独立审核。",
            "approval_state": "pending_user_adoption", "package_ref": {"artifact": "source-gold-supplements-proposed.json"}})
        e["proposed_ref"] = {"slot": group["gold_id"], "item_index": len(group["expected_items"])}
        group["expected_items"].append({"kind": "body", "quote": e["quote"], "text": e["role"],
            "evidence_id": e["evidence_id"], "provenance": {k: e[k] for k in ("page", "char_start", "char_end_exclusive", "text_artifact_sha256", "quote_sha256")}})
    proposed_gold.extend(groups.values())
    write_once("source-gold-supplements-proposed.json", supplements)
    with (HERE / "source-gold-proposed.jsonl").open("x", encoding="utf-8") as output:
        # Preserve the exact byte representation of the frozen prefix.
        prefix = (BASE / "source-gold-frozen.jsonl").read_text(encoding="utf-8")
        output.write(prefix)
        if not prefix.endswith("\n"):
            output.write("\n")
        for row in groups.values():
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
    quality = [
        {"id": "Q1", "query_id": "macro-001", "evidence_ids": ["N-event", "N-month-header", "N-month-values", "N-conflict"],
         "finding": "首页/第3/4页前值为修订后2.1万人；第5页将5.6万人写成前值。源内矛盾，非清洗器制造。",
         "handling_proposed": "保留现有题目目标，但附‘按首页事件段及第3页表’的范围说明和冲突提示；不自动改原文，不把5.6当已核验前值。"},
        {"id": "Q2", "evidence_ids": ["C-report-date", "N-date"],
         "finding": "长江正文日期2026-08-10与文件名08-13不同；光大正文9月5日与文件名9月6日不同。",
         "handling_proposed": "source_id保持不变；正文发布日期与文件身份分开。后续发布时间验收不得以文件名替代正文依据，本轮不改数据库/公共准入规则。"},
        {"id": "Q3", "evidence_ids": ["C-columns", "C-r32-capacity", "G-table-cash-header"],
         "finding": "表格裸数值不足以独立证明行列身份；连续文本和视觉行列对应是不同证据层。",
         "handling_proposed": "保留本次visual_mappings；正式投影必须携带/联合表头、行名、单位、年份和脚注，不可用同义映射将缺结构视作已证明。"},
    ]
    result = {"artifact": "i3-2-agent-adjudication-REVIEWED-NOT-APPROVAL",
        "reviewer": AUTHOR, "reviewed_at": NOW, "based_on": initial["based_on"],
        "source_gold_proposed_sha256": digest(HERE / "source-gold-proposed.jsonl"),
        "source_supplements_sha256": digest(HERE / "source-gold-supplements-proposed.json"),
        "rule_rev": candidates["rule_rev"], "ready_for_gold_freeze": False,
        "ready_for_user_adoption": True, "human_approved": False,
        "facet_reviews": facet_reviews, "question_reviews": question_reviews,
        "negative_reviews": negatives, "human_status_clarifications": [status_note],
        "source_coverage": coverage, "quality_notes": quality,
        "release_conditions": ["用户明确采纳AI辅助核验及Q1冲突处置，不冒签原审核人",
            "形成新的source-gold版本/哈希和候选，不用r25旧哈希套新引文",
            "将新source item映射到正式裁决件；词面映射/改选审核按原契约逐项校验，不豁免结构或事实缺口",
            "重新验证批准投影/完整性门并冻结新版本；此前不得进行I3-3业务验收或宣称I3-2正式完成"],
        "summary": {"source_count": 6, "pdf_pages": 89, "source_spans": len(evidence),
            "facet_reviews": len(facet_reviews), "positive_reviews": len(question_reviews),
            "negative_reviews": len(negatives), "human_status_clarifications": 1,
            "model_api_calls": 0, "network_calls": 0, "pg_calls": 0, "holdout_sources_read": 0}}
    assert len(facet_reviews) == 40 and len(question_reviews) == 24 and len(negatives) == 6
    write_once("adjudication-reviewed.json", result)
    after = {p: digest(BASE / p) for p in protected}
    assert before == after
    write_once("protected-artifacts-check.json", {"unchanged": True, "sha256": after,
        "formal_decisions_exists": (BASE / "i3-2/evidence-targets-decisions.json").exists(),
        "formal_approved_exists": (BASE / "i3-2/evidence-targets-approved.json").exists()})
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()

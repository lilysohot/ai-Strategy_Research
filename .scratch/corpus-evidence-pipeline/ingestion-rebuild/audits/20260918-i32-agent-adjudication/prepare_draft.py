"""Agent-assisted review of frozen annotations only; never a human approval artifact."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_lines(name):
    return [json.loads(line) for line in (BASE / name).read_text().splitlines() if line.strip()]


# Explicit evidence choices and judgments, not automatic endorsement of machine suggestions.
# Values are (status, frozen quote references, rationale).
FACETS = {
    "company-001-01": ("supported", ["company-008-claim-001#4"], "26—28年与三个EPS数值按顺序对应；同句明确预测、一年目标价2030元及维持强推。'同时'是答案组织义务，原文引号/空格导致的词面差异不是缺事实。"),
    "company-004-01": ("supported", ["company-018-claim-001#2"], "原文13.4与要求13.40数值等价；保留原文13.4不改写。"),
    "company-004-02": ("needs_source_context", ["company-018-claim-001#2"], "现有quote以'其设定'开头，虽有触发值/目标值，但股权激励主体只在text标注中；须补第1页该段前文，不能把text当原文。"),
    "company-008-01": ("needs_source_context", ["company-008-claim-001#4", "company-018-claim-001#3"], "两条具体评级及维持/首次覆盖均有原文；两段未出现公司名，须把报告首页主体与这两段绑定，不能把标题身份映射伪装为词面同义。"),
    "company-008-03": ("supported", ["company-008-claim-001#4"], "绑定贵州茅台来源2026-08-16_6f14cc14；选择该来源具体维持强推引文，不使用另一来源评级或通用定义。"),
    "company-008-04": ("supported", ["company-018-claim-001#3"], "绑定光力科技来源2026-09-06_dddc7cd0；原文明确首次覆盖、优于大市。"),
    "industry-001-01": ("needs_source_context", ["industry-009-claim-001#0", "industry-009-claim-001#1", "industry-009-claim-001#2", "industry-009-claim-001#8", "industry-009-claim-001#9"], "需联合纯碱行、价格/价差分位列及注1/注2，注2单独不能证明分位不是涨幅；表格身份目前在行列标注中，应回核第10页表头。"),
    "industry-002-01": ("supported", ["industry-009-claim-001#10"], "注3逐字注明R32产能为配额；不得改称实际产量是对此口径的保留，不需虚构来源说过同样的否定句。"),
    "industry-002-02": ("supported", ["industry-009-claim-001#8"], "注1明确价格/价差分位统计窗口；不能用裸值99.6%或其period元数据替代。"),
    "industry-003-01": ("needs_source_context", ["industry-009-claim-001#6", "industry-009-claim-001#7"], "89.9%与8068.0分别属于开工率和2026E产能；须核对表头、万吨/年单位与E预测列，开工率脚注不能代替这些结构证据。"),
    "industry-004-01": ("supported", ["industry-009-claim-001#8"], "选注1，日期范围2016-01-01至2026-07-27在原文；拒绝裸数值备选。"),
    "industry-004-02": ("supported", ["industry-009-claim-001#9"], "选注2，两个平均窗口及'或'均明确；不能按品种擅自分配窗口。"),
    "industry-006-01": ("needs_source_supplement", ["industry-057-claim-001#2"], "用途和计划已出现，但'供应链消息'只在text而不在quote；须补第1页上文来源归属。"),
    "industry-006-02": ("supported", ["industry-057-claim-001#2"], "原文明确Rubin Ultra预计2027年推出，不能改写为已经推出。"),
    "industry-006-03": ("needs_source_supplement", ["industry-057-claim-001#2"], "计划/预计可保留，消息来源仍缺原文；补齐后联合承载，不以lexical_review豁免。"),
    "industry-008-01": ("needs_source_context", ["industry-009-claim-001#3", "industry-009-claim-001#8"], "R32的99.6%需绑定价格分位列并结合注1；不能用纯碱/R134a或仅注1替代完整身份。"),
    "industry-008-02": ("needs_source_context", ["industry-009-claim-001#3", "industry-009-claim-001#8", "industry-057-claim-001#4"], "应联合R32行/列/统计窗口和氩气价格变化段，证明历史分位与区间涨幅不同；不把'引用两份'本身当来源事实。"),
    "industry-008-03": ("supported", ["industry-009-claim-001#3", "industry-009-claim-001#8"], "指定2026-08-13_174b6462来源，选择R32单元格与统计窗口，不能以华福周报单独完成双来源义务。"),
    "macro-001-01": ("needs_source_context", ["macro-038-claim-001#0"], "前值修订关系明确，但当前quote缺'8月'和'7月'字样；需扩大第1页事件段引文以绑定月份，不能仅由period补足。"),
    "macro-003-01": ("supported", ["macro-038-claim-001#3"], "'若...下行幅度有限'明确条件关系；条件/后续通胀的词面差异可逐项原文说明。"),
    "macro-003-02": ("needs_source_supplement", [], "冻结quote没有'强就业降低加息顾虑'的因果判断；回到光大非农点评第1页最后两段取完整原句，不能由题目要求生成quote。"),
    "macro-003-03": ("supported", ["macro-038-claim-001#3", "macro-038-claim-001#4"], "联合'若...可能性'与'市场预期...超过60%'两段，分别承载条件判断和市场概率；不等同正式决议属于答案解释约束。"),
    "macro-004-01": ("supported", ["macro-039-claim-001#1"], "原文逐一列出政府、准财政、企业、居民、海外五主体；'五主体'和'五个主体'为词面差异。"),
    "macro-004-02": ("needs_source_supplement", [], "聚焦前四者只在text中，不在quote；须补华创宏观专题第1页相关原句。"),
    "macro-004-03": ("needs_source_supplement", [], "五主体列表不能承载四条收敛路径；须从第1—2页四个路径标题/摘要分别取原文。"),
    "macro-005-01": ("needs_source_supplement", ["macro-039-claim-001#0"], "新旧动能行业分类不证明财政收入依赖旧动能及新动能税负偏低；须补第1页路径1的两条因果/税负判断。"),
    "macro-006-01": ("needs_source_supplement", ["macro-039-claim-001#3", "macro-060-claim-001#4"], "数值与泛化样本风险均已有，但都不能证明'偏头部发债企业'；须补第1页路径2的具体样本定义。"),
    "macro-008-01": ("supported", ["macro-060-claim-001#4"], "原文同时保留上市公司/发债企业、代表性欠佳、结论偏差及可能存在其他路径，不能删掉后两项。"),
}

QUESTION_NOTES = {
    "company-001": "评级段已包含完整EPS年度序列、目标价和预测属性，可据冻结标注整理。",
    "company-002": "H1与单Q2有两条独立原文，数值及同比正负均应分别保留。",
    "company-003": "六项数值与行列/期间在已具名标注中；括号解释已有原审核依据，草案不把标注元数据冒充新增quote。",
    "company-004": "补股权激励段主体上下文后才能完整确认。",
    "company-005": "8230/8231与9130/9320的两条原文已区分批量应用、正式订单和客户验证，不能混为量产。",
    "company-006": "32.60%+4.00%=36.60%；另条原文明确亲属1.70%/0.57%未计入。截止日期仍需保留已有期间依据。",
    "company-007": "持股方向原文明确；'本公司'指华创证券需回核声明页主体，不能靠同义映射补主体。",
    "company-008": "具体评级有据，两份报告的公司主体上下文需绑定。",
    "industry-001": "保留纯碱三列身份，联合注1与注2；需回核表头。",
    "industry-002": "R32数值、配额脚注及窗口已有标注；2026E/单位结构还需按原表保留。",
    "industry-003": "回核表头及单位，不以开工率脚注证明产能预测列。",
    "industry-004": "两条脚注足以承载两个窗口；或关系必须原样保留。",
    "industry-005": "氩气从720到2459元/吨、四个月、超过240%均见同段。",
    "industry-006": "补供应链消息归属，现有计划/预计和用途不能代替归属。",
    "industry-007": "两条指数原文分别承载5611.65/-4.2%及12576.94/-9.12%，不得错配。",
    "industry-008": "联合R32表格身份与氩气价格段；不能把历史分位当涨幅。",
    "macro-001": "补月份上下文，修订关系与当月值不可混并。",
    "macro-002": "三个指标和前值均有已冻结原文，保留报告归属。",
    "macro-003": "补强就业因果判断；条件与概率分开，不能当正式决定。",
    "macro-004": "需补聚焦前四者与四条路径，五主体列表不能替代。",
    "macro-005": "支出预测有据，财政收入两个堵点缺直接引文。",
    "macro-006": "两年数值有据，具体样本定义缺直接引文。",
    "macro-007": "两条原文支持公式、六个比率；当年=2026需报告年份上下文，不由公式或数值推断。",
    "macro-008": "投资增速和风险两段已有标注；当前年2026需保留报告年份依据。",
}


def main():
    candidates_path = BASE / "i3-2/evidence-targets-candidates.json"
    payload = json.loads(candidates_path.read_text())
    gold = load_lines("query-gold-frozen.jsonl")
    slots = {s["gold_id"]: s for s in load_lines("source-gold-frozen.jsonl")}
    questions = {q["query_id"]: q for q in gold}
    rows = []
    context_questions = {"company-007", "industry-002", "macro-007", "macro-008"}
    for question in payload["questions"]:
        for item in question["pending_human"]:
            short = item["item_id"].removeprefix("I32-")
            if item["kind"] == "answer_constraint":
                status, refs, reason = "answer_constraint_only", [], "保留冻结要求中的答案表达约束，不新增证据目标；这不是对真实生成答案已合规的证明。"
            else:
                status, refs, reason = FACETS[short]
            evidence = []
            for ref in refs:
                slot_id, index = ref.rsplit("#", 1)
                slot = slots[slot_id]
                value = slot["expected_items"][int(index)]
                evidence.append({"ref": ref, "source_id": slot["source_id"],
                    "source_sha256": slot["source_sha256"], "locator": slot["locator"],
                    "quote": value["quote"], "item_identity": {k: value.get(k) for k in ("row", "col", "unit", "period")}})
            rows.append({"item_id": item["item_id"], "query_id": question["query_id"],
                "facet_id": item.get("facet_id"), "kind": item["kind"],
                "status": status, "reason": reason, "evidence": evidence,
                "requires_user_confirmation": True})
    question_reviews = []
    for qid, reason in QUESTION_NOTES.items():
        missing = [row["item_id"] for row in rows if row["query_id"] == qid and row["status"].startswith("needs_")]
        question_reviews.append({"query_id": qid, "requirement": questions[qid]["evidence_requirement"],
            "status": "needs_source_review" if missing or qid in context_questions else "supported_by_frozen_annotation",
            "reason": reason, "open_items": missing, "requires_user_confirmation": True})
    negative_reviews = [{"query_id": q["query_id"], "requirement": q["evidence_requirement"],
        "status": "needs_full_text_review", "full_text_coverage_confirmed": False,
        "reason": "现有摘录与既有human_basis可作线索，但本次未读取六份开发PDF全文；不以未检索到或未来日期推断代替全文覆盖核验。",
        "previous_human_basis": q["human_basis"], "requires_user_confirmation": True}
        for q in gold if q["answer_existence"] == "no_answer"]
    result = {"artifact": "i3-2-agent-adjudication-draft-NOT-APPROVAL",
        "author": "Codex (AI-assisted review, not xyl/human signature)",
        "generated_at": datetime.now(timezone.utc).isoformat(), "rule_rev": payload["rule_rev"],
        "authority": "用户授权代为补证与整理裁决；未授权把AI记录冒充独立人工签认",
        "ready_for_gold_freeze": False, "based_on": {
            "candidates_sha256": digest(candidates_path),
            "source_gold_sha256": digest(BASE / "source-gold-frozen.jsonl"),
            "query_gold_sha256": digest(BASE / "query-gold-frozen.jsonl"),
            "guard_sha256": digest(BASE / "guards/i3.json")},
        "source_reading": {"raw_pdfs_read": 0, "blocked_by": "i3 guard read_roots=[]; waiting for scoped read phase approval"},
        "facet_reviews": rows, "question_reviews": question_reviews, "negative_reviews": negative_reviews,
        "human_status_clarifications": [{"gold_id": "macro-039-claim-001", "status": "unresolved",
            "reason": "human_basis仍称待真人复核且已有xyl签名。不能替xyl认定残留笔误；待原文核验后请U确认是否为残留描述。"}]}
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    result["summary"] = {"facets": len(rows), "facet_statuses": counts,
        "positive_questions": len(question_reviews), "negative_questions": len(negative_reviews),
        "clarifications": 1, "human_approved": 0}
    assert len(rows) == 40 and len(question_reviews) == 24 and len(negative_reviews) == 6
    assert len({r["item_id"] for r in rows}) == 40
    with (HERE / "adjudication-draft.json").open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()

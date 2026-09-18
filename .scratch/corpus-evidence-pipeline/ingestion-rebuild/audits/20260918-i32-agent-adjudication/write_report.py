"""Render the completed AI review dossier and source appendix, without sign-off."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name):
    return json.loads((HERE / name).read_text())


review = load("adjudication-reviewed.json")
supp = load("source-gold-supplements-proposed.json")
verify = load("verification.json")
evidence = {s["evidence_id"]: s for s in supp["spans"]}


def refs(ids):
    return "、".join(f"[{eid}](evidence-appendix.md#{eid.lower()})" for eid in ids)


report = ["# I3-2 金标补证与裁决底稿：AI 辅助核验完成，未正式签发", "",
    f"复核者：{review['reviewer']}。时间：{review['reviewed_at']}。", "",
    "## 结论", "",
    "六份冻结开发 PDF 共89页已按授权只读补证。56条连续原文切片、5组结构对应记录已落盘；40项要件、24道有答案题、6道负例与1项历史状态问题均已有逐项处理建议，无需用户从空白模板重新标注。",
    "",
    "本次判断：24道正例所要求的事实在原文中均能找到依据；6道负例在这六份文件范围内仍建议保留无答案。此前几处实质缺证主要是标注未收录完整上下文，不是原文没有对应内容。",
    "",
    "但这不是正式金标验收通过：未冒签xyl，未生成正式decisions/approved，未改冻结source/query gold、旧I3守卫或r25快照；未执行I3-3/检索业务评测。署名保留AI辅助核验，最终采纳仍由用户确认。",
    "",
    "## 授权与隔离", "",
    "用户明确授权：‘允许六份开发 PDF 只读补证’。新建独立annotation guard，精确白名单6个原文件路径且逐一核对冻结SHA-256；原I3守卫不放宽。守卫自检24/24。继续隔离3份留出材料；不做OCR、不使用生产清洗/检索结果补答案，不访问网络、外部模型API或PostgreSQL。",
    "",
    "使用PDF技能完成双阅读器抽取、全页缩略图筛查及相关原页目视核对。缩略图只用于发现版面和图像遗漏，不代替细表读数；相关财务表、化工表、非农月表、CME概率表、宏观图例已查看原页。",
    "",
    "## 补齐的关键内容", "",
    "| 缺口 | 本次直接依据 |",
    "|---|---|",
    "| macro-003 强就业与加息顾虑的因果判断 | 光大第1页 N-causal，不再从题目反造原句 |",
    "| macro-004 聚焦前四主体、四条路径 | 华创第1页主体段及第1—2页四个路径标题，分别定位 |",
    "| macro-005 财政两个堵点 | 华创第1页 K-bottlenecks，保留旧动能拖累和新动能税负 |",
    "| macro-006 偏头部发债企业样本 | 华创第1页 K-sample，不能用泛化风险提示代替 |",
    "| industry-006 供应链消息归属 | 华福第1页 H-ptfe，包含归属、用途、计划和预计 |",
    "| 公司主体、激励性质、持股方向 | 两份公司首页、茅台第7页‘本公司’定义 |",
    "| 表头、年份、单位、统计窗口 | 原页表格目视记录及独立原文切片，不将裸数字解释为完整证据 |",
    "",
    "## 必须随金标保留的质量提示", "",
]
for note in review["quality_notes"]:
    report += [f"### {note['id']}", "", note["finding"], "", note["handling_proposed"], "", "依据：" + refs(note["evidence_ids"]), ""]
report += ["## 验证结果及未覆盖范围", "",
    "- 新补证191/191项检查通过：从授权PDF重新抽取并逐条核对页内字符切片、引文哈希、图像绑定、要件身份、来源专属约束、负例覆盖范围和冻结件未变化。它们是字节/结构检查，不是191次语义正确性评测。",
    "- 原有审批/评分器回归88/88通过；r25冻结链校验通过。命令原始输出见regression.txt、freeze-validation.txt。",
    "- 把本AI底稿误传入正式审批器仍为ready=false；没有利用底稿跳过签认。",
    "- 56条引文中，40条在另一阅读器的空白归一文本中连续匹配；16条受双栏/表格读取次序或文字层差异影响不连续匹配，已保留差异清单并结合原页核对，不伪造‘双阅读器全部一致’。",
    "- 未重跑PG、生产入库、全文检索、答案生成或全项目测试；没有业务模型调用，不能由本次结果推算Recall@5或EvidencePass。",
    "",
    "## 正式发布前的工程边界", "",
    "`source-gold-proposed.jsonl` 是**追加全部复核证据的研究提案**，不是可直接覆盖冻结件的发布版本。原始冻结行和签名保持原样；所有新增行均显式标为AI待采纳。冲突片段/负例近似命中也在复核证据库里，正式映射时必须区分支持证据与反证/干扰项。",
    "",
    "一次离线机械重映射显示：目标54→85，状态2 blocked→1 blocked（剩macro-004），仍有40项待裁决。四条路径的原文已逐项定位，机器候选仍不能自行联合判为完备，这不意味着原文仍缺四条路径。**不得通过扩大段落、豁免缺词或批量批准强行消除blocked。**",
    "",
    "正式转版应保留原必需单元格的行列身份，按本底稿精确改选/补充，去除重复或干扰锚点；按原协议提交anchor_review/lexical_review，并重新检查逐题义务完整性。长段quote、统计单位/公司身份和视觉表格对应不能被简单的字符串覆盖当作机器语义证明。不要直接将85条全部变为必需，也不以目标减少作为成功指标。",
    "",
    "## 用户需要确认什么", "",
    "请审阅Q1及下列逐题建议后，决定是否采纳本次AI辅助核验。建议确认口径：", "",
    "> 采纳本次AI辅助补证与裁决建议；macro-001按首页事件段和第3页表保留原目标，同时记录第5页前值冲突；以本次复核的新采纳记录处理macro-039历史待复核状态，不冒签或改写旧审核记录。允许另建新金标版本并重新执行批准门。",
    "",
    "该确认是采纳AI辅助成果，不应记成用户逐页亲自核验或原审核人的历史笔误证明。用户确认后，剩余版本化、精准映射、校验和冻结由工程侧执行；只有这些门通过才可标记I3-2正式完成。若不同意某题，只需指出题号，不必重填整份模板。",
    "",
    "## 24道有答案题：复核与拟定参考答案", "",
]
for q in review["question_reviews"]:
    report += [f"### {q['query_id']}", "", q["question"], "", "冻结要求：" + q["evidence_requirement"], "",
               "拟采纳答案：" + q["reference_answer_proposed"], "", "依据：" + refs(q["evidence_ids"]), ""]
report += ["## 六道负例：边界与近似命中排除", "",
    "覆盖六份共89页，不限于原有槽位或检索命中。结论仅限冻结文件，不表示外部世界不存在事实，也不延伸到留出集或新版本。", ""]
for n in review["negative_reviews"]:
    report += [f"### {n['query_id']}", "", n["question"], "", n["reason"], "", "近似命中核验：" + refs(n["near_miss_evidence_ids"]), ""]
report += ["## 40项要件裁决建议", "",
    "每一项均为AI建议，待用户采纳。答案侧约束不生成证据目标；其实际执行效果仍在I3-5验收。", ""]
for f in review["facet_reviews"]:
    report += [f"### {f['item_id']} / {f['kind']}", "", f["reason"], "",
               "建议：" + f["recommendation"] + "；依据：" + (refs(f["evidence_ids"]) or "答案约束，不设置chosen"), ""]
report += ["## 历史状态澄清", "", review["human_status_clarifications"][0]["reason"], "",
    "## 文件导航", "",
    "- adjudication-reviewed.json：40+24+6+1逐项建议和完整来源范围。",
    "- source-gold-supplements-proposed.json：56条精确原文、拟定slot/item位置和5组视觉映射。",
    "- evidence-appendix.md：可读原文附录及页面图片链接。",
    "- verification.json：191项核对明细和双阅读器差异清单。",
    "- candidate-remap-diagnostic.json：一次离线机械追加试映射，非业务验收。",
    "- protected-artifacts-check.json：原冻结件与正式门状态未被改变。",
    "- annotation-guard*.json、source-read-audit.json：授权范围、自检和源文件哈希。", ""]
appendix = ["# 原文补证附录（AI辅助，非正式批准）", "",
    "引文是连续原始抽取片段；页码为PDF物理页，offset为对应pages/*.json中text的字符下标。跨片段/跨页不拼成伪原文。表格抽取顺序不等于视觉行列顺序，结合visual_mappings核对。", ""]
for e in supp["spans"]:
    appendix += [f"## {e['evidence_id']}", "",
        f"来源：`{e['source_id']}`；PDF第{e['page']}页；字符[{e['char_start']}, {e['char_end_exclusive']})。",
        "", f"[查看原页]({e['image_artifact']})；PDF SHA-256：`{e['source_sha256']}`。", "",
        "```text", e["quote"], "```", ""]
appendix += ["## 结构对应复核", ""]
for v in supp["visual_mappings"]:
    appendix += [f"### {v['id']}", "", f"{v['source_id']} 第{v['page']}页。" + v["judgment"], "",
                 "```json", json.dumps(v["bindings"], ensure_ascii=False, indent=2), "```", ""]
for name, content in [("review-completed.md", report), ("evidence-appendix.md", appendix)]:
    with (HERE / name).open("x", encoding="utf-8") as output:
        output.write("\n".join(content))
deliverables = ["review-completed.md", "evidence-appendix.md", "adjudication-reviewed.json", "source-gold-supplements-proposed.json", "source-gold-proposed.jsonl", "verification.json", "candidate-remap-diagnostic.json", "protected-artifacts-check.json", "regression.txt", "freeze-validation.txt"]
with (HERE / "package-manifest.json").open("x", encoding="utf-8") as output:
    json.dump({"artifact": "AI-assisted-review-package-NOT-FORMAL-GOLD", "human_signoff": False,
        "files": {p: hashlib.sha256((HERE / p).read_bytes()).hexdigest() for p in deliverables}}, output, indent=2)
print("wrote review-completed.md, evidence-appendix.md, package-manifest.json")

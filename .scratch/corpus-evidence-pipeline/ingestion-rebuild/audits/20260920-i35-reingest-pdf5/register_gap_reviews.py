"""将那 4 份已签署 gap-review 重签到新 reader-pdf-5 build 并登记。

保留 U 的 rationale/attestation 逐字，重绑 build_id/build_fingerprint，补填
evidence_scope_ref、required_locators；光力 p7（力片同步图 + 证据同页）用 region
schema，其余用 page-only。登记后由 corpus check/publish 复验。
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
SANDBOX = "i2_sandbox_corpus"

NEW = {
  # name -> (build_id, build_fingerprint)
  "maotai-huachuang": ("2fc48247fa4777681cdb3b726b1193b7b43e7d8968671178e54d502c4afdeb3f",
                       "d0a85fcbaddb118467af6efd5c28dfd08fbc372d288822691baf08311398aace"),
  "guangli-guoxin": ("f3221a1e91e2b9edbb7c9ab1e6ed44e08c92462e5920bd251cfa912721213740",
                     "3845592d56ba38331a73eaa55a4121c9608dc0b30e622cde1b3b215b4a7bb3f6"),
  "changjiang-shiwenda": ("f467708311ed8c6409e1d9bcf2fd326735777ecc399ff3519afa13016962ee55",
                          "987551dd0125040b18ec35adddade45fdae344d9f39e276a56e9066b48b26f11"),
  "guangda-feinong": ("9af73f907a8276c715f41cc55e29b7ef95d48db095be73e89739ce95763db677",
                      "7f804493aa08c56a0b2f1baa692111fd11292e1d523171064255faa7363d3839"),
}
PDF = {
  "maotai-huachuang": "data/corpus/2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司研究-业绩点评-贵州茅台-600519-报表实质扎实-经营底部已过-贵州茅台-600519-2026年中报点评-e034bdac.pdf",
  "guangli-guoxin": "data/corpus/2026-09-06_2026.09.06-国信证券-光力科技-300480-2026年中报点评-半导体划片机国内龙头-经营拐点向上-b6beb6ee.pdf",
  "changjiang-shiwenda": "data/corpus/2026-08-13_2026.08.13-长江证券-国内研报-长江证券-化工专题-景气投资-十问十答-7463f4d0.pdf",
  "guangda-feinong": "data/corpus/2026-09-06_2026.09.06-光大证券-2026年8月美国非农数据点评-强非农降低了年内加息的门槛-6fc25e24.pdf",
}
# 每份的来源/决定/缺口（sheets 从已签署文件逐字保留）
SIGNED = {
 "maotai-huachuang": {
   "source_id": "6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11",
   "scope_rationale": "所需证据位于 evidence-targets-approved.json 之 approved_required/supplementary，涉及 page:1（EPS 67.74/70.77/73.84、目标价 2030、26H1 收入 922.8 亿）与 page:3（补充 EPS 表单元格）。本来源 13 处缺口外唯一的图像缺口 page:2 与所需证据页不相交。",
   "attestation": "已目视核验并比对逐页提取结果：page:2 图像区为「图表1 茅台分季度拆分表」整版图（bbox [36.8,91.9]-[564.1,479.8]，占页宽 88.6%，区域内字符数=0，纯图无文字重叠），另有左上 logo 与 2 个小色块；页内正文、图表2/3 PE/PB Band 轴标签均在图像外完整可提取。该缺口为图表截图，未承载所需证据；所需证据 locator 页（1/3）与缺口页（2）不相交。",
   "required_locators": ["page:1", "page:3"],
   "gaps": {"issue:image_region_unreadable:page:2": "page:2 图像区为「图表1 茅台分季度拆分表」整版图（纯图，区域内无文字）；所需证据在 page:1/3，与之不相交，不影响所需证据。"},
 },
 "guangli-guoxin": {
   "source_id": "dddc7cd0cb74d085d851df3772aedcf68779b61087a365d14eb53ff5bb4d7afa",
   "scope_rationale": "所需证据位于 evidence-targets-approved.json 之 approved_required/supplementary，涉及 page:1/2/3/7/20（其中 page:20=每股收益 0.36/0.59/0.93、经营现金流 -222/-138/-17；page:7=赵彤宇直接 32.60%+间接 4.00%=合计 36.60%、陈淑兰 1.70%、赵彤亚 0.57%）。page:7 上的所需证据载体为纯文字，位于页上部 y=85-155，与图像缺口区域（组织架构图 bbox y=334.8-726.2）不相交。",
   "attestation": "已目视核验并比对逐页提取结果：page:7 图像区域为「图4 公司核心业务主要子公司结构」组织架构图（bbox 476×391.4pt，y 区间 334.8-726.2），另有左上 logo；所需证据持股比例文字（赵彤宇 32.60%+4.00%=36.60% 等）位于页上部 y=85-155，完整可提取且与图像区域 bbox 不相交。该缺口为组织架构图，未承载所需证据文字，同页但区域不重叠，不影响所需证据。",
   "required_locators": ["page:1", "page:2", "page:3", "page:7", "page:20"],
   "gaps": {"issue:image_region_unreadable:page:7": "page:7 图像区为组织架构图（bbox y=334.8-726.2）；所需证据持股比例文字位于页上部 y=85-155，完整且与图像区域不重叠，同页但区域不相交，不影响所需证据（签认注明：与金标同页但图像区域与证据文字不重叠）。"},
   "region_quote": "实际控制人赵彤宇直接持有公司32.60%股份",
 },
 "changjiang-shiwenda": {
   "source_id": "174b64628f35aca60909d11b509bc7b7e87a9f4613a03a1da6c01d720a8cbcb0",
   "scope_rationale": "所需证据位于 evidence-targets-approved.json 之 approved_required/supplementary，全部集中在 page:10（纯碱/尿素/R32 的价格分位、价差分位、开工率、配额单元格及表注）。本来源全部缺口页（1/2/3/12/13/17/18/21/22/24）均与 page:10 不相交。",
   "attestation": "已目视核验并比对逐页提取结果：p1 为整版背景/水印图（封面标题文字仍可提取）；p2 为背景图+logo+方形图标（正文「报告要点」完整）；p3 为 logo+二维码（正文十问要点一~八完整，无真实数据表）；p12 为图10-12 的 X 轴年份刻度被误认格线（12 个空表，图标题/轴标签完整）；p13 图13/图14 饼图数值（4.6%/12.2%/8.2%/44.2%/9.7%/21.2%）仍在 text；p17/18/21/22 为矢量折线图（轴标签在 text）；p24 为纯文字（投资评级说明），无表格。全部缺口页的正文与图表数值在 raw_text 中完整存在，仅未结构化，无内容缺失；所需证据页（10）与缺口页不相交。",
   "required_locators": ["page:10"],
   "gaps": {
    "issue:image_region_unreadable:page:1": "page:1 为整版背景/水印图，封面标题文字仍可提取；所需证据在 page:10，与此页不相交，不影响所需证据。",
    "issue:image_region_unreadable:page:2": "page:2 为背景图+logo+方形图标，正文「报告要点」完整可提取；所需证据在 page:10，与此页不相交，不影响所需证据。",
    "issue:table_lines_without_extraction:page:3": "page:3 为 logo+二维码，正文十问要点一~八完整，无真实数据表格；所需证据在 page:10，与此页不相交，不影响所需证据。",
    "issue:table_lines_without_extraction:page:12": "page:12 的图10-12 X 轴年份刻度被误认格线（空表），正文与图标题/轴标签完整；无内容缺失，与所需证据页（10）不相交。",
    "issue:table_lines_without_extraction:page:13": "page:13 图13/图14 饼图数值（4.6%/12.2%/8.2%/44.2%/9.7%/21.2%）仍在 text，正文完整；无内容缺失，与所需证据页（10）不相交。",
    "issue:table_lines_without_extraction:page:17": "page:17 为矢量折线图（轴标签在 text），正文完整；无内容缺失，与所需证据页（10）不相交。",
    "issue:table_lines_without_extraction:page:18": "page:18 为矢量折线图（轴标签在 text），正文完整；无内容缺失，与所需证据页（10）不相交。",
    "issue:table_lines_without_extraction:page:21": "page:21 为矢量折线图（轴标签在 text），正文完整；无内容缺失，与所需证据页（10）不相交。",
    "issue:table_lines_without_extraction:page:22": "page:22 为矢量折线图（轴标签在 text），正文完整；无内容缺失，与所需证据页（10）不相交。",
    "issue:table_lines_without_extraction:page:24": "page:24 为纯文字（投资评级说明、办公地址），无表格；无内容缺失，与所需证据页（10）不相交。",
   },
 },
 "guangda-feinong": {
   "source_id": "793b39673d31e8a8310e89a9171567dfb0008444b669cd6e225dc354329a880a",
   "scope_rationale": "所需证据位于 evidence-targets-approved.json 之 approved_required/supplementary，涉及 page:1（16.2 万、失业率 4.1%、时薪 3.1%）与 page:3（新增非农总计 -156/214/148/63/31/21/162/71）。本来源唯一缺口页 page:6 与所需证据页不相交。",
   "attestation": "已目视核验并比对逐页提取结果：page:6 无真实带格线数据表格，仅 1 张 logo（72×21.3pt）；extract_tables 返回的 2 个「表」实为图9 职位供需缺口的 X 轴刻度/图例误认与空表；正文（三、劳动参与率回升…图7-10 标题/轴标签/图例）完整在 text。无内容缺失，所需证据页（1/3）与缺口页（6）不相交。",
   "required_locators": ["page:1", "page:3"],
   "gaps": {"issue:table_lines_without_extraction:page:6": "page:6 无真实数据表格，仅 logo；extract_tables 命中的为图9 X 轴刻度/图例误认与空表，正文完整；无内容缺失，与所需证据页（1/3）不相交。"},
 },
}

EVIDENCE_SCOPE_REF = "evidence-targets-approved.json::approved_required+supplementary"
REVIEWER = "xyl"
REVIEWED_AT = "2026-09-20T12:00:00+08:00"


def main() -> int:
    os.environ["CORPUS_DEV_LANE"] = "1"
    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation import guard  # noqa: PLC0415
    guard.install(str(ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json"))  # noqa: E501
    from plugins.corpus import cli  # noqa: PLC0415
    from plugins.corpus.preparation.gap_review import (
        ATTESTATION,
        REGION_SCHEMA_REV,
        SCHEMA_REV,
    )  # noqa: PLC0415
    from plugins.corpus.preparation.gaps import GAP_POLICY_REV  # noqa: PLC0415

    env = {l.split("=", 1)[0]: l.split("=", 1)[1] for l in open(ROOT / ".env", encoding="utf-8") if "=" in l and not l.strip().startswith("#")}  # noqa: E501
    cred = env["CORPUS_DSN"].split("://", 1)[1].rsplit("@", 1)[0]
    dsn = f"postgresql://{cred}@127.0.0.1:543/{SANDBOX}"

    results = []
    for name, (bid, fp) in NEW.items():
        s = SIGNED[name]
        region = bool(s.get("region_quote"))
        payload = {
            "schema_rev": REGION_SCHEMA_REV if region else SCHEMA_REV,
            "policy_rev": GAP_POLICY_REV,
            "source_id": s["source_id"],
            "build_id": bid,
            "build_fingerprint": fp,
            "reviewer": REVIEWER,
            "reviewed_at": REVIEWED_AT,
            "evidence_scope_ref": EVIDENCE_SCOPE_REF,
            "required_locators": s["required_locators"],
            "scope_rationale": s["scope_rationale"],
            "attestation": ATTESTATION,
            "gaps": s["gaps"],
        }
        if region:
            payload["region_source_path"] = str(ROOT / PDF[name])
            payload["region_targets"] = {"page:7": [s["region_quote"]]}
        rec = HERE / f"signed-{name}.json"
        rec.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        buf = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(buf):
            code = cli.main(["gap-review", "--build", bid, "--record", str(rec), "--dsn", dsn])
        results.append({"name": name, "record": str(rec.relative_to(ROOT)), "exit_code": code,
                        "output": buf.getvalue()[:400]})
        print(json.dumps({"name": name, "region": region, "exit_code": code,
                          "record": str(rec.relative_to(ROOT))}, ensure_ascii=False))
    (HERE / "register-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
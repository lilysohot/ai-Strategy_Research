"""Frozen query-only pilot features. Not a production intent extractor.

No answer keys, expected answer text, positive chunk IDs or labels are read here.
Intent groups are manually specified from the unchanged questions before scoring.
Matching is case/whitespace normalized substring matching, NOT entailment.
"""
import re
from dataclasses import replace

# entity names, requested aspects (slash-separated alternatives within one aspect)
INTENTS = {
    'p01': ('麒麟', '芯片,晶体管,省电/功耗'),
    'p02': ('', '芯片,堆叠/立体,后道/测试'),
    'p03': ('', 'PCB,盈利,新品'),
    'p04': ('', '乳清蛋白,替代'),
    'p05': ('', '猪价,产能,淘汰'),
    'p06': ('', '银行,外部,资本'),
    'p07': ('', '金融机构,增资,超预期/超出预期'),
    'p08': ('', '银行,1998,特别国债'),
    'p09': ('', 'AI电源,液冷,财务,订单'),
    'p10': ('', '光伏,上半年,盈利'),
    'p11': ('', '光模块,五年/5年,更换/替换,需求'),
    'p12': ('', '3.2T,批量/批供,2028,出货'),
    'p13': ('美国', '制造业,服务业'),
    'p14': ('', '铝冶炼,温室气体,发电'),
    'p15': ('', '2019,2024,2025,碳配额,抵扣/清缴'),
    'p16': ('华工正源,立讯技术', '华工正源,立讯技术,NPO'),
    'p17': ('', '新动能,财政收入'),
    'p18': ('', '非农,9月,加息'),
    'p19': ('光力科技', '2026,上半年,营业收入,归母净利润'),
    'p20': ('光力科技', '半导体,安全监控,收入'),
    'p21': ('光力科技', '实际控制人,直接,合计,持股/控制'),
    'p22': ('', '氩气,价格,5月,9月'),
    'p23': ('三星电机', 'AI服务器,MLCC,金额,供货'),
    'p24': ('工业富联', '上半年,经营现金流/经营活动,扣非'),
    'n01': ('紫荆量子光电股份有限公司/紫荆量子光电', '2026,上半年,营业收入,净利润'),
    'n02': ('贵州茅台', '2035,已审计,实际,营业收入'),
    'n03': ('', '2028,3.2T,实际出货,500万'),
    'n04': ('光力科技', '2034,上半年,归母净利润'),
    'n05': ('三星电机', 'MLCC,合同,客户'),
    'n06': ('光力科技', '2026,上半年,安全监控,3.51,收入'),
    'n07': ('光力科技', '2026,中报/上半年,归母净利润'),
    'n08': ('工业富联', '2026,10月20日,收盘价'),
}

LEGAL_MARKERS = ('免责声明', '法律声明', '分析师声明', '分析师承诺', '投资评级说明',
                 '评级说明', '评级标准', '版权声明', '投资者适当性', '特别声明')
LEGAL_PHRASES = ('不构成投资建议', '不承担任何责任', '未经书面许可', '版权所有',
                 '仅供参考', '证券投资咨询业务资格', '投资风险自负')


def norm(text):
    return re.sub(r'\s+', '', text).casefold()


def groups(value):
    return [part.split('/') for part in value.split(',') if part]


def coverage(text, value):
    terms = groups(value)
    return sum(any(norm(term) in text for term in group) for group in terms) / len(terms) if terms else 0.0


def features(case_id, question, evidence):
    text = norm(evidence['text'])
    # A heading in the first 160 characters, or two independent legal phrases.
    legal = any(norm(t) in text[:160] for t in LEGAL_MARKERS) or sum(norm(t) in text for t in LEGAL_PHRASES) >= 2
    requested = any(norm(t) in norm(question) for t in (*LEGAL_MARKERS, '评级规则', '版权', '免责声明'))
    entities, aspects = INTENTS[case_id]
    return {'template': legal and not requested, 'entity': coverage(text, entities),
            'aspects': coverage(text, aspects)}


def rerank_within_source(hits, feature_map, signal):
    """Single-signal 0.25x template penalty or [1,2]x coverage multiplier.

    Preserve source order, every candidate, and stable ties. The source-first RRF
    and band selector remain identical. Rerank lexical reservations the same way.
    """
    sources = list(dict.fromkeys(h.source_id for h in hits))
    adjusted = []
    for hit in hits:
        value = feature_map[hit.chunk_id][signal]
        factor = (0.25 if value else 1.0) if signal == 'template' else 1.0 + value
        adjusted.append(replace(hit, score=hit.score * factor))
    return tuple(h for source in sources for h in
                 sorted((h for h in adjusted if h.source_id == source), key=lambda h: -h.score))

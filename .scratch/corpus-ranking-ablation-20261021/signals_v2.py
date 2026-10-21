"""Second development pass after v1 exposed footer and company-pronoun errors.

Keep v1 results. No claim of held-out improvement. Same weights and query groups;
only role-aware text extraction, legal heading detection and title entity context.
"""
import re
from signals import INTENTS, LEGAL_MARKERS, coverage, norm


def body_text(text):
    # A citation is not evidence about the cited company's products. Keep the
    # authority unchanged; remove these lines only from the scoring projection.
    return '\n'.join(line for line in text.splitlines()
        if not re.match(r'^\s*(资料来源\s*[:：]|请.*阅读.*免责声明|仅供内部参考)', line))


def features(case_id, question, evidence, source_title):
    text = body_text(evidence['text'])
    lines = [norm(line).strip(':：') for line in text.splitlines() if line.strip()]
    # Strong role evidence: an actual legal heading, not a footer mentioning it.
    heading = any(line in LEGAL_MARKERS for line in lines[:8])
    asked = any(norm(t) in norm(question) for t in (*LEGAL_MARKERS, '评级规则', '版权'))
    entities, aspects = INTENTS[case_id]
    # Title is used only to establish the discussed company, never as body proof
    # of an indicator. One report may use "公司" throughout its actual evidence.
    entity_text = norm(text + '\n' + source_title)
    return {'template': heading and not asked, 'entity': coverage(entity_text, entities),
            'aspects': coverage(norm(text), aspects)}

"""Opt-in PDF text module. No imports of production code, OCR packages or fixtures.

The native_reader and ocr_reader adapters own file decoding and bounded execution.
This module owns routing, lossless reading-order reconstruction and issue reporting.
"""
from __future__ import annotations

import math
import re
import statistics
from typing import Callable


def _issue(code, message, *, severity='warning', **evidence):
    return {'code': code, 'severity': severity, 'message': message, **evidence}


def _native_quality(text):
    compact = re.sub(r'\s+', '', text)
    cjk = len(re.findall(r'[\u3400-\u9fff]', compact))
    latin = len(re.findall(r'[A-Za-z]', compact))
    words = len(re.findall(r'[A-Za-z]{2,}', text))
    bad = sum(c == '\ufffd' or '\ue000' <= c <= '\uf8ff' for c in compact)
    language_share = (cjk + latin) / max(1, len(compact))
    features = {'characters': len(compact), 'cjk': cjk, 'latin_words': words,
                'language_share': language_share, 'unmapped_share': bad / max(1, len(compact))}
    # Conservative, language-specific admission, not a guarantee of full-page recall.
    if not compact:
        return False, 'no_native_text', features
    if features['unmapped_share'] > .01:
        return False, 'unmapped_native_glyphs', features
    if len(compact) < 160:
        return False, 'sparse_native_text', features
    if language_share < .45 or (cjk < 60 and words < 40):
        return False, 'native_body_not_established', features
    return True, 'native_text_usable', features


def _lines(ocr):
    texts, boxes, scores = ocr.get('lines'), ocr.get('boxes'), ocr.get('scores')
    width, height = ocr.get('render_pixels', (0, 0))
    if not isinstance(texts, list) or not isinstance(boxes, list) or not isinstance(scores, list):
        raise ValueError('OCR lines/boxes/scores must be lists')
    if len(texts) != len(boxes) or len(texts) != len(scores):
        raise ValueError('OCR line metadata lengths disagree')
    if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
        raise ValueError('Invalid OCR page dimensions')
    result = []
    for i, (text, box, score) in enumerate(zip(texts, boxes, scores)):
        if not isinstance(text, str) or len(box) != 4:
            raise ValueError('Invalid OCR line or quadrilateral')
        coordinates = [float(v) for point in box for v in point]
        if len(coordinates) != 8 or not all(math.isfinite(v) for v in coordinates):
            raise ValueError('Invalid OCR coordinates')
        if not math.isfinite(float(score)) or not 0 <= float(score) <= 1:
            raise ValueError('Invalid OCR score')
        xs, ys = coordinates[0::2], coordinates[1::2]
        x0, x1, y0, y1 = min(xs) / width, max(xs) / width, min(ys) / height, max(ys) / height
        if x1 <= x0 or y1 <= y0:
            raise ValueError('Degenerate OCR box')
        result.append({'id': i, 'text': text, 'score': float(score), 'box': box,
                       'rect': [x0, y0, x1, y1]})
    return result


def _column_cut(lines):
    # Find repeated left edges of paragraph-like lines. Tables with many tiny
    # cells do not themselves establish the main column. No document templates.
    anchors = []
    for line in lines:
        text = re.sub(r'\s+', '', line['text'])
        x0, y0, x1, y1 = line['rect']
        letters = sum(c.isalpha() for c in text)
        if len(text) >= 20 and letters / len(text) >= .45 and .18 <= x1 - x0 <= .72:
            anchors.append(line)
    clusters = []
    for line in sorted(anchors, key=lambda line: line['rect'][0]):
        if clusters and abs(line['rect'][0] - statistics.median(x['rect'][0] for x in clusters[-1])) <= .025:
            clusters[-1].append(line)
        else:
            clusters.append([line])
    for cluster in sorted(clusters, key=lambda group: sum(len(x['text']) for x in group), reverse=True):
        if len(cluster) < 4 or sum(len(x['text']) for x in cluster) < 150:
            continue
        edge = statistics.median(x['rect'][2] for x in cluster)
        if not .25 <= edge <= .78:
            continue
        top = min(x['rect'][1] for x in cluster)
        bottom = max(x['rect'][3] for x in cluster)
        right = [x for x in lines if x['rect'][0] > edge + .005 and top <= x['rect'][1] <= bottom]
        if len(right) < 6 or sum(len(x['text']) for x in right) < 60:
            continue
        starts = sorted(x['rect'][0] for x in right)
        cut = (edge + starts[len(starts) // 10]) / 2
        crossing = [x for x in lines if x['rect'][0] < cut - .005 and x['rect'][2] > cut + .005
                    and x['rect'][2] - x['rect'][0] < .72]
        if len(crossing) > max(2, len(lines) * .05):
            continue
        return cut
    return None


def _reading_order(lines):
    cut = _column_cut(lines)
    if cut is None:
        return sorted(lines, key=lambda x: (x['rect'][1], x['rect'][0], x['id'])), []
    # Full-width headings/footers bound independent horizontal bands. Each band
    # is read left column, then right column. Every original line is retained.
    wide = [x for x in lines if x['rect'][0] < cut < x['rect'][2] and x['rect'][2] - x['rect'][0] >= .72]
    spans = sorted(wide, key=lambda x: (x['rect'][1], x['rect'][0]))
    span_ids = {x['id'] for x in spans}
    pending = [x for x in lines if x['id'] not in span_ids]
    ordered = []
    for span in spans + [None]:
        boundary = span['rect'][1] if span else float('inf')
        band = [x for x in pending if (x['rect'][1] + x['rect'][3]) / 2 < boundary]
        ids = {x['id'] for x in band}
        pending = [x for x in pending if x['id'] not in ids]
        left = [x for x in band if (x['rect'][0] + x['rect'][2]) / 2 < cut]
        right = [x for x in band if (x['rect'][0] + x['rect'][2]) / 2 >= cut]
        for column in (left, right):
            ordered.extend(sorted(column, key=lambda x: (x['rect'][1], x['rect'][0], x['id'])))
        if span:
            ordered.append(span)
    assert sorted(x['id'] for x in ordered) == list(range(len(lines)))
    return ordered, [{'type': 'vertical_gutter', 'x_fraction': cut, 'method': 'repeated_text_edges'}]


def _quality_issues(lines):
    issues = []
    for line in lines:
        text, score = line['text'], line['score']
        evidence = {'line_id': line['id'], 'box': line['box'], 'text': text, 'score': score}
        if score < .8 and len(re.sub(r'\s+', '', text)) >= 6:
            issues.append(_issue('low_confidence_line', 'OCR line requires source review; text retained.', **evidence))
        words = re.findall(r'[A-Za-z0-9]+', text)
        if len(words) >= 4 and score < .85 and sum(len(w) <= 2 for w in words) >= 2 and statistics.median(map(len, words)) <= 2:
            issues.append(_issue('fragmented_line', 'Fragmented tokens may indicate a garbled body line.', **evidence))
        if re.search(r'/([A-Z])\1+(?=[@\s,，。;；]|$)', text):
            issues.append(_issue('suspicious_repeated_unit', 'Repeated unit letter; verify against the source. No correction applied.', **evidence))
        if re.search(r'\b\d+[oOIl]\d+\b', text):
            issues.append(_issue('ambiguous_numeric_token', 'Letters resembling digits occur inside a numeric token.', **evidence))
        if '\ufffd' in text or any('\ue000' <= c <= '\uf8ff' for c in text):
            issues.append(_issue('unmapped_ocr_text', 'Unmapped characters retained for review.', **evidence))
    return issues


def read_page(path: str, page: int, *, enabled: bool = False,
              native_reader: Callable, ocr_reader: Callable | None = None) -> dict:
    """Read one page. Disabled by default; usable native text is byte-for-byte retained.

    The OCR adapter must bound execution and return status/text/lines/boxes/scores/
    render_pixels, or raise TimeoutError. Failures retain any native text. This
    module never drops a detected line or silently corrects a character.
    """
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError('page must be a positive one-based integer')
    try:
        native = native_reader(path, page)
        if not isinstance(native, str):
            raise ValueError('native_reader must return text')
    except Exception as exc:
        return {'status': 'error', 'source': 'none', 'text': '', 'native_text': '',
                'needs_review': True, 'issues': [_issue('native_read_error', str(exc))], 'lines': [], 'layout': []}
    usable, reason, features = _native_quality(native)
    result = {'status': 'disabled' if not enabled else 'ok', 'source': 'native',
              'text': native, 'native_text': native, 'native_quality': features,
              'route_reason': reason, 'needs_review': False, 'issues': [], 'lines': [], 'layout': []}
    if not enabled or usable:
        return result
    if ocr_reader is None:
        result.update(status='unavailable', needs_review=True,
                      issues=[_issue('ocr_unavailable', 'OCR needed but no adapter supplied; native text retained.')])
        return result
    try:
        ocr = ocr_reader(path, page)
    except TimeoutError as exc:
        result.update(status='timeout', needs_review=True, issues=[_issue('ocr_timeout', str(exc))])
        return result
    except Exception as exc:
        result.update(status='error', needs_review=True, issues=[_issue('ocr_error', str(exc))])
        return result
    if not isinstance(ocr, dict):
        result.update(status='error', needs_review=True, issues=[_issue('invalid_ocr', 'OCR adapter returned no structured result.')])
        return result
    result['ocr_original'] = ocr
    if ocr.get('status') not in ('ok', 'empty'):
        result.update(status=ocr.get('status') if ocr.get('status') in ('timeout', 'error') else 'error', needs_review=True,
                      issues=[_issue('ocr_failed', 'OCR failed; native text retained.')])
        return result
    if not str(ocr.get('text', '')).strip():
        result.update(status='fallback' if native.strip() else 'empty', needs_review=bool(native.strip()),
                      issues=[_issue('ocr_empty', 'OCR produced no text; native text retained.')] if native.strip() else [])
        return result
    try:
        lines = _lines(ocr)
        if not lines:
            raise ValueError('Non-empty OCR text has no line records')
        ordered, layout = _reading_order(lines)
        issues = _quality_issues(lines)
        text = '\n'.join(x['text'] for x in ordered)
    except (ValueError, TypeError, KeyError, IndexError, AssertionError) as exc:
        # Invalid layout metadata must not erase recognized text.
        result.update(status='needs_review', source='ocr', text=str(ocr['text']), needs_review=True,
                      issues=[_issue('layout_unavailable', str(exc))])
        return result
    result.update(status='needs_review' if issues else 'ok', source='ocr', text=text,
                  needs_review=bool(issues), issues=issues, lines=ordered, layout=layout)
    return result

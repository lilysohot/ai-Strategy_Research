"""Opt-in PDF text module. No imports of production code, OCR packages or fixtures.

The native_reader and ocr_reader adapters own file decoding and bounded execution.
This module owns routing, lossless reading-order reconstruction and issue reporting.
"""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter
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
    # A narrow LEFT sidebar need not contain paragraph-length anchors. In that
    # case the repeated start of a RIGHT body column establishes the gutter.
    for cluster in sorted(clusters, key=lambda group: sum(len(x['text']) for x in group), reverse=True):
        if len(cluster) < 4 or sum(len(x['text']) for x in cluster) < 150:
            continue
        start = statistics.median(x['rect'][0] for x in cluster)
        if not .2 <= start <= .8:
            continue
        aligned = [x for x in cluster if abs(x['rect'][0] - start) <= .01]
        if len(aligned) < 4:
            continue
        top = min(x['rect'][1] for x in aligned)
        bottom = max(x['rect'][3] for x in aligned)
        left = [x for x in lines if x['rect'][2] < start - .005 and top <= x['rect'][1] <= bottom]
        if len(left) < 6 or sum(len(x['text']) for x in left) < 60:
            continue
        edge = max(x['rect'][2] for x in left)
        cut = (edge + start) / 2
        crossing = [x for x in lines if x['rect'][0] < cut < x['rect'][2]
                    and x['rect'][2] - x['rect'][0] < .72
                    and top <= x['rect'][1] <= bottom]
        if len(crossing) <= max(2, len(lines) * .05):
            return cut
    return None


def _row_order(lines):
    rows = []
    for line in sorted(lines, key=lambda x: ((x['rect'][1]+x['rect'][3])/2, x['rect'][0])):
        center = (line['rect'][1] + line['rect'][3]) / 2
        height = line['rect'][3] - line['rect'][1]
        if rows and abs(center - rows[-1][0]) <= .4 * min(height, rows[-1][1]):
            rows[-1][2].append(line)
        else:
            rows.append((center, height, [line]))
    return [line for _, _, row in rows for line in sorted(row, key=lambda x: (x['rect'][0], x['id']))]


def _reading_order(lines, depth=0):
    if not lines:
        return [], []
    # Recompute coordinates inside each region: a spread can contain columns
    # inside both halves. IDs and original boxes always remain page-relative.
    xmin = min(x['rect'][0] for x in lines)
    xmax = max(x['rect'][2] for x in lines)
    width = max(xmax - xmin, .001)
    local = [{**x, 'rect': [(x['rect'][0] - xmin) / width, x['rect'][1],
                            (x['rect'][2] - xmin) / width, x['rect'][3]]} for x in lines]
    # TOC leaders bind labels to page numbers. They are not prose columns.
    leaders = sum(bool(re.search(r'[.．·…]{3,}', x['text'])) for x in lines)
    if depth >= 8 or leaders >= 3:
        return _row_order(lines), []
    cut = _column_cut(local)
    if cut is None:
        mirrored = [{**x, 'rect': [1-x['rect'][2], x['rect'][1],
                                  1-x['rect'][0], x['rect'][3]]} for x in local]
        reverse_cut = _column_cut(mirrored)
        if reverse_cut is not None:
            cut = 1 - reverse_cut
    if cut is None:
        return _row_order(lines), []
    cut = xmin + cut * width
    # Full-width headings/footers bound independent horizontal bands. Each band
    # is read left column, then right column. Every original line is retained.
    wide = [x for x in lines if x['rect'][0] < cut < x['rect'][2]]
    spans = sorted(wide, key=lambda x: (x['rect'][1], x['rect'][0]))
    span_ids = {x['id'] for x in spans}
    pending = [x for x in lines if x['id'] not in span_ids]
    ordered = []
    layout = [{'type': 'vertical_gutter', 'x_fraction': cut,
               'method': 'recursive_text_edges', 'depth': depth}]
    for span in spans + [None]:
        boundary = span['rect'][1] if span else float('inf')
        band = [x for x in pending if (x['rect'][1] + x['rect'][3]) / 2 < boundary]
        ids = {x['id'] for x in band}
        pending = [x for x in pending if x['id'] not in ids]
        left = [x for x in band if (x['rect'][0] + x['rect'][2]) / 2 < cut]
        right = [x for x in band if (x['rect'][0] + x['rect'][2]) / 2 >= cut]
        for column in (left, right):
            if len(column) == len(lines):
                part, child_layout = _row_order(column), []
            else:
                part, child_layout = _reading_order(column, depth + 1)
            ordered.extend(part)
            layout.extend(child_layout)
        if span:
            ordered.append(span)
    assert sorted(x['id'] for x in ordered) == sorted(x['id'] for x in lines)
    return ordered, layout


def _rect(value):
    if len(value) != 4:
        raise ValueError('Expected normalized rectangle')
    rect = [float(x) for x in value]
    if not all(math.isfinite(x) for x in rect):
        raise ValueError('Non-finite rectangle')
    x0, y0, x1, y1 = rect
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError('Rectangle outside page or degenerate')
    return rect


def _native_lines(native):
    lines = []
    for i, line in enumerate(native['lines']):
        if not isinstance(line['text'], str):
            raise ValueError('Native line text must be a string')
        rect = _rect(line['rect'])
        words = [_rect(word) for word in line['word_rects']]
        if line['text'].strip() and not words:
            raise ValueError('Native line is missing word rectangles')
        if any(w[0] < rect[0] - .001 or w[1] < rect[1] - .001
               or w[2] > rect[2] + .001 or w[3] > rect[3] + .001 for w in words):
            raise ValueError('Native word lies outside its line')
        lines.append({'id': i, 'text': line['text'], 'rect': rect,
                      'box': rect, 'word_rects': words})
    return lines


def _coverage(lines, evidence):
    """Compare independent raster detections with native WORD boxes, not page
    hulls or character counts. A match is spatial evidence, not semantic recall.
    """
    if evidence.get('status') != 'ok' or evidence.get('source') != 'raster_text_detection':
        raise ValueError('Independent raster text detection unavailable')
    detected = [_rect(r) for r in evidence['rects']]
    if not detected:
        raise ValueError('No raster text regions; coverage remains unknown')
    words = [r for line in lines for r in line['word_rects']]
    regions = []
    for i, box in enumerate(detected):
        x0, y0, x1, y1 = box
        mid = (y0 + y1) / 2
        intervals = []
        for a, b, c, d in words:
            # Centerline test tolerates detector padding without letting a
            # neighbouring line establish coverage for a missing text row.
            if b - (d-b)*.15 <= mid <= d + (d-b)*.15:
                lo, hi = max(a, x0), min(c, x1)
                if hi > lo:
                    intervals.append((lo, hi))
        covered, end = 0., x0
        for lo, hi in sorted(intervals):
            covered += max(0., hi - max(lo, end))
            end = max(end, hi)
        ratio = covered / (x1-x0)
        regions.append({'id': i, 'rect': box, 'covered_fraction': ratio,
                        'suspected_missing': ratio < .65})
    missing = [r for r in regions if r['suspected_missing']]
    return {'status': 'suspected_missing' if missing else 'matched',
            'source': evidence['source'], 'regions': regions, 'missing_regions': missing,
            'meaning': 'Geometric coverage only; not full-text or semantic accuracy.'}


def _quality_issues(lines):
    issues = []
    for line in lines:
        text, score = line['text'], line['score']
        evidence = {'line_id': line['id'], 'box': line['box'], 'text': text, 'score': score}
        # Short financial values (e.g. "73%") can lose a decimal point while
        # falling below the prose-length filter. Preserve and flag them too.
        if score < .8 and (len(re.sub(r'\s+', '', text)) >= 6 or re.search(r'\d', text)):
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
              native_reader: Callable, ocr_reader: Callable | None = None,
              coverage_reader: Callable | None = None) -> dict:
    """Read one page. Disabled by default; raw native text is always retained.

    Native adapters may return a string (coverage unknown) or text + lines with
    normalized rect/word_rects. Coverage adapters return independent raster
    detections in the same displayed page coordinate system. Suspected gaps are
    returned for review, never silently admitted or filled by guessed text.

    The OCR adapter must bound execution and return status/text/lines/boxes/scores/
    render_pixels, or raise TimeoutError. Failures retain any native text. This
    module never drops a detected line or silently corrects a character.
    """
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError('page must be a positive one-based integer')
    try:
        native_result = native_reader(path, page)
        native = native_result['text'] if isinstance(native_result, dict) else native_result
        if not isinstance(native, str):
            raise ValueError('native_reader must return text or structured text')
    except Exception as exc:
        return {'status': 'error', 'source': 'none', 'text': '', 'native_text': '',
                'needs_review': True, 'issues': [_issue('native_read_error', str(exc))], 'lines': [], 'layout': []}
    usable, reason, features = _native_quality(native)
    result = {'status': 'disabled' if not enabled else 'ok', 'source': 'native',
              'text': native, 'native_text': native, 'native_quality': features,
              'route_reason': reason, 'needs_review': False, 'issues': [], 'lines': [], 'layout': [],
              'coverage': {'status': 'not_checked'}}
    if not enabled:
        return result
    if usable:
        issues = []
        try:
            if not isinstance(native_result, dict):
                raise ValueError('Native reader supplied no coordinates')
            lines = _native_lines(native_result)
            if not lines:
                raise ValueError('Native text has no coordinate records')
            # Counts preserve repeated content: presence anywhere in the page
            # cannot mask a missing copy. Whitespace alone is disregarded.
            raw_chars = Counter(re.sub(r'\s+', '', native))
            boxed_chars = Counter(re.sub(r'\s+', '', ''.join(x['text'] for x in lines)))
            if raw_chars != boxed_chars:
                issues.append(_issue('native_coordinate_mismatch',
                    'Raw text and coordinate extraction disagree; raw text retained.',
                    missing_from_text=sum((boxed_chars - raw_chars).values()),
                    missing_from_coordinates=sum((raw_chars - boxed_chars).values())))
            else:
                ordered, layout = _reading_order(lines)
                result.update(text='\n'.join(x['text'] for x in ordered), lines=ordered, layout=layout)
            if coverage_reader is None:
                raise ValueError('No independent raster detection adapter')
            evidence = coverage_reader(path, page)
            if 'page_points' in native_result and 'render_pixels' in evidence:
                nw, nh = native_result['page_points']
                rw, rh = evidence['render_pixels']
                if min(nw, nh, rw, rh) <= 0 or abs((nw/nh)/(rw/rh) - 1) > .01:
                    raise ValueError('Native and raster page orientations/dimensions disagree')
            result['coverage'] = _coverage(lines, evidence)
            if result['coverage']['missing_regions']:
                issues.append(_issue('native_coverage_gap',
                    'Visible text regions lack native coverage; inspect source regions.',
                    regions=result['coverage']['missing_regions']))
            if any(re.search(r'[.．·…]{3,}', x['text']) for x in lines):
                issues.append(_issue('structured_layout_review',
                    'Leader lines may be a contents/table layout; verify row associations.'))
        except Exception as exc:
            result['coverage'] = {'status': 'unknown', 'reason': str(exc)}
            issues.append(_issue('native_coverage_unknown', str(exc)))
        if issues:
            result.update(status='needs_review', needs_review=True, issues=issues,
                          route_reason=issues[0]['code'])
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

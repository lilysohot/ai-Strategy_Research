"""Experimental Poppler coordinate adapter. Never imported by production.

Both invocations must use the same source page. Raster detection is deliberately
separate: native boxes alone cannot establish visible-text coverage.
"""
import subprocess
import xml.etree.ElementTree as ET


def parse_native(text, xml):
    root = ET.fromstring(xml)
    pages = root.findall('.//{*}page')
    if len(pages) != 1:
        raise ValueError('Expected exactly one Poppler page')
    page = pages[0]
    width, height = float(page.attrib['width']), float(page.attrib['height'])
    if width <= 0 or height <= 0:
        raise ValueError('Invalid Poppler page size')

    def rect(node):
        return [float(node.attrib[k]) / scale for k, scale in
                [('xMin', width), ('yMin', height), ('xMax', width), ('yMax', height)]]

    lines = []

    def emit(words):
        boxes = [rect(w) for w in words]
        lines.append({'text': ' '.join(''.join(w.itertext()) for w in words),
                      'rect': [min(b[0] for b in boxes), min(b[1] for b in boxes),
                               max(b[2] for b in boxes), max(b[3] for b in boxes)],
                      'word_rects': boxes})

    for line in page.findall('.//{*}line'):
        group = []
        for word in line.findall('{*}word'):
            if group:
                prev = group[-1].attrib
                gap = float(word.attrib['xMin']) - float(prev['xMax'])
                line_height = float(prev['yMax']) - float(prev['yMin'])
                if gap > max(1.5 * line_height, width * .012):
                    emit(group)
                    group = []
            group.append(word)
        if group:
            emit(group)
    return {'text': text, 'lines': lines, 'page_points': [width, height],
            'extractor': 'pdftotext -layout + -bbox-layout'}


def read_native(path, page, *, timeout=30):
    args = ['-f', str(page), '-l', str(page), str(path), '-']
    text = subprocess.run(['pdftotext', '-layout', *args], check=True,
                          capture_output=True, text=True, timeout=timeout).stdout
    xml = subprocess.run(['pdftotext', '-bbox-layout', *args], check=True,
                         capture_output=True, text=True, timeout=timeout).stdout
    return parse_native(text, xml)

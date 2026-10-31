import unittest
import copy
from body_reader import read_page
from native_adapter import parse_native


def payload(lines):
    return {'status': 'ok', 'text': '\n'.join(t for t, *_ in lines),
            'lines': [t for t, *_ in lines], 'scores': [s for _, _, s in lines],
            'boxes': [[[x, y], [r, y], [r, y+10], [x, y+10]] for _, (x,y,r), _ in lines],
            'render_pixels': [1000, 1000]}


class ReaderTests(unittest.TestCase):
    def test_short_low_confidence_numbers_require_review_with_source_coordinates(self):
        # Real DDOG p7 OCR pattern: 7.3%, 8.5%, 6.3% lost decimal points.
        # Retain the raw tokens; only surface their uncertainty for review.
        raw = payload([('73%', (100, 100, 140), .70409),
                       ('85%', (200, 100, 240), .70794),
                       ('63%', (300, 100, 340), .73504)])
        result = self.read(ocr=lambda *_: raw)
        warnings = [x for x in result['issues'] if x['code'] == 'low_confidence_line']
        self.assertEqual([x['text'] for x in warnings], raw['lines'])
        self.assertEqual([x['box'] for x in warnings], raw['boxes'])
        self.assertEqual(result['text'], raw['text'])
        self.assertEqual(result['status'], 'needs_review')

    def test_short_numeric_warning_preserves_non_numeric_filter_and_threshold(self):
        raw = payload([('73%', (100, 100, 140), .8), ('1.9%', (200, 100, 240), .90294),
                       ('USD', (300, 100, 340), .7), ('1', (400, 100, 410), .7)])
        result = self.read(ocr=lambda *_: raw)
        warnings = [x['text'] for x in result['issues'] if x['code'] == 'low_confidence_line']
        self.assertEqual(warnings, ['1'])
        self.assertEqual(result['text'], raw['text'])

    def read(self, native='', ocr=None, **kw):
        return read_page('dummy.pdf', 1, enabled=True, native_reader=lambda *_: native,
                         ocr_reader=ocr, **kw)

    def test_disabled_never_calls_ocr(self):
        r = read_page('x', 1, native_reader=lambda *_: '123', ocr_reader=lambda *_: self.fail())
        self.assertEqual((r['text'], r['status']), ('123', 'disabled'))

    def test_native_preserved_exactly(self):
        text = '正文保持完整，换行空格也保持。\n  ' * 30
        r = self.read(text, lambda *_: self.fail())
        self.assertEqual((r['text'], r['source']), (text, 'native'))

    def test_long_native_without_spatial_evidence_requires_review(self):
        # A long surviving string is indistinguishable from a partially lost
        # page without independent evidence. It must not be admitted as complete.
        r = self.read('Remaining native paragraph with many readable words. ' * 40)
        self.assertTrue(r['needs_review'])
        self.assertEqual(r['status'], 'needs_review')

    def test_double_spread_orders_each_inner_sidebar(self):
        lines = []
        expected = []
        for start, end, name in ((40, 330, 'left body'), (360, 470, 'left sidebar'),
                                 (530, 820, 'right body'), (850, 960, 'right sidebar')):
            column = [(name + ' paragraph content long enough for layout ' + str(i),
                       (start, 100 + i * 25, end), .99) for i in range(8)]
            lines.extend(column)
            expected.extend(x[0] for x in column)
        lines.sort(key=lambda x: (x[1][1], x[1][0]))
        r = self.read(ocr=lambda *_: payload(lines))
        self.assertEqual(r['text'].splitlines(), expected)

    def native_fixture(self):
        lines = []
        for i in range(8):
            for name, start, end in [('main', .1, .57), ('sidebar', .65, .9)]:
                rect = [start, .1+i*.03, end, .11+i*.03]
                lines.append({'text': f'{name} paragraph with sufficient readable content number {i}',
                              'rect': rect, 'word_rects': [rect]})
        native = {'text': '\n'.join(x['text'] for x in lines), 'lines': lines}
        evidence = {'status': 'ok', 'source': 'raster_text_detection',
                    'rects': [x['rect'] for x in lines]}
        return native, evidence

    def test_native_coordinates_reorder_and_preserve_raw(self):
        native, evidence = self.native_fixture()
        r = self.read(native, lambda *_: self.fail(), coverage_reader=lambda *_: evidence)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['coverage']['status'], 'matched')
        self.assertEqual(r['native_text'], native['text'])
        self.assertEqual(r['text'].splitlines(), [x['text'] for x in native['lines'][::2] + native['lines'][1::2]])

    def test_missing_native_rows_detected_without_text_comparison(self):
        native, evidence = self.native_fixture()
        missing = native['lines'][4:8]
        del native['lines'][4:8]
        native['text'] = '\n'.join(x['text'] for x in native['lines'])
        r = self.read(native, coverage_reader=lambda *_: evidence)
        self.assertEqual(r['status'], 'needs_review')
        self.assertEqual(r['coverage']['status'], 'suspected_missing')
        self.assertEqual([x['rect'] for x in r['coverage']['missing_regions']], [x['rect'] for x in missing])
        self.assertNotIn('native_coordinate_mismatch', [x['code'] for x in r['issues']])

    def test_raw_text_loss_does_not_get_hidden_by_coordinate_replacement(self):
        native, evidence = self.native_fixture()
        native['text'] = '\n'.join(x['text'] for x in native['lines'][4:])
        r = self.read(native, coverage_reader=lambda *_: evidence)
        self.assertTrue(r['needs_review'])
        self.assertEqual(r['text'], native['text'])
        self.assertIn('native_coordinate_mismatch', [x['code'] for x in r['issues']])

    def test_missing_region_not_masked_by_line_hull(self):
        native, evidence = self.native_fixture()
        native['lines'][0]['word_rects'] = [[.1, .1, .2, .11], [.5, .1, .57, .11]]
        evidence['rects'] = [[.25, .1, .45, .11]]
        r = self.read(native, coverage_reader=lambda *_: evidence)
        self.assertEqual(r['coverage']['status'], 'suspected_missing')

    def test_missing_and_failed_detection_remain_unknown(self):
        native, evidence = self.native_fixture()
        for bad in ({'status': 'timeout'}, {**evidence, 'rects': []},
                    {**evidence, 'rects': [[0, 0, float('nan'), 1]]}):
            r = self.read(copy.deepcopy(native), coverage_reader=lambda *_: bad)
            self.assertEqual(r['coverage']['status'], 'unknown')
            self.assertTrue(r['needs_review'])

    def test_disabled_does_not_call_detection(self):
        native, _ = self.native_fixture()
        r = read_page('x', 1, native_reader=lambda *_: native,
                      coverage_reader=lambda *_: self.fail())
        self.assertEqual(r['text'], native['text'])
        self.assertEqual(r['status'], 'disabled')

    def test_page_orientation_mismatch_requires_review(self):
        native, evidence = self.native_fixture()
        native['page_points'] = [1000, 500]
        evidence['render_pixels'] = [500, 1000]
        r = self.read(native, coverage_reader=lambda *_: evidence)
        self.assertEqual(r['coverage']['status'], 'unknown')
        self.assertTrue(r['needs_review'])

    def test_right_body_header_does_not_prevent_sidebar_split(self):
        lines = [('Offset headline shares a loose anchor cluster with body', (348, 20, 928), .99)]
        lines += [(f'Table cell {i}', (290, 100+i*20, 460), .99) for i in range(10)]
        body = [(f'Continuous main body paragraph with sufficient letters {i}',
                 (328, 400+i*25, 990), .99) for i in range(12)]
        side = [(f'Sidebar supporting details {i}', (0, 400+i*25, 244), .99) for i in range(12)]
        r = self.read(ocr=lambda *_: payload(lines + body + side))
        body_positions = [r['text'].splitlines().index(x[0]) for x in body]
        self.assertEqual(body_positions, list(range(body_positions[0], body_positions[0]+12)))

    def test_same_baseline_fragments_use_horizontal_order(self):
        r = self.read(ocr=lambda *_: payload([('right fragment', (500, 100, 800), .99),
                                             ('left fragment', (100, 102, 400), .99)]))
        self.assertEqual(r['text'], 'left fragment\nright fragment')

    def test_poppler_adapter_splits_large_gaps_and_keeps_words(self):
        xml = '''<html xmlns="http://www.w3.org/1999/xhtml"><doc>
          <page width="1000" height="1000"><flow><block><line>
          <word xMin="100" yMin="100" xMax="200" yMax="110">Left</word>
          <word xMin="205" yMin="100" xMax="250" yMax="110">body</word>
          <word xMin="650" yMin="100" xMax="800" yMax="110">Sidebar</word>
          </line></block></flow></page></doc></html>'''
        result = parse_native('Left body    Sidebar', xml)
        self.assertEqual([x['text'] for x in result['lines']], ['Left body', 'Sidebar'])
        self.assertEqual(len(result['lines'][0]['word_rects']), 2)
        self.assertEqual(result['text'], 'Left body    Sidebar')

    def test_numeric_and_unmapped_native_route_to_ocr(self):
        for text in ('123456 78\n' * 50, '\ue000' * 200):
            r = self.read(text, lambda *_: payload([('recognized body', (100,100,900), .99)]))
            self.assertEqual(r['source'], 'ocr')

    def test_failures_preserve_native(self):
        for exception, status in ((TimeoutError('deadline'), 'timeout'), (RuntimeError('broken'), 'error')):
            def fail(*_): raise exception
            r = self.read('123', fail)
            self.assertEqual((r['status'],r['text']), (status,'123'))
            self.assertTrue(r['needs_review'])
        r = self.read('123', lambda *_: {'status':'empty','text':''})
        self.assertEqual((r['status'],r['text']), ('fallback','123'))

    def test_missing_adapter(self):
        self.assertEqual(self.read()['status'], 'unavailable')

    def test_invalid_metadata_keeps_raw_text(self):
        r = self.read(ocr=lambda *_: {'status':'ok','text':'whole raw OCR'})
        self.assertEqual(r['text'], 'whole raw OCR')
        self.assertEqual(r['issues'][0]['code'], 'layout_unavailable')

    def test_columns_keep_every_line_once(self):
        left = [('Main paragraph line with enough letters '+str(i), (100,100+i*30,570), .99) for i in range(8)]
        right = [('Sidebar figures '+str(i), (650,100+i*30,900), .99) for i in range(8)]
        interleaved = [v for pair in zip(left,right) for v in pair]
        r = self.read(ocr=lambda *_: payload(interleaved))
        self.assertTrue(r['layout'])
        self.assertEqual(r['text'].splitlines(), [x[0] for x in left+right])
        self.assertEqual(sorted(x['id'] for x in r['lines']), list(range(16)))

    def test_single_column_and_warnings_do_not_rewrite(self):
        lines = [('Value 6.4TOPS/WW@INT8', (100,100,900), .99),
                 ('2o2 o s o et', (100,130,900), .69)]
        r = self.read(ocr=lambda *_: payload(lines))
        self.assertEqual(r['text'], '\n'.join(x[0] for x in lines))
        self.assertFalse(r['layout'])
        self.assertTrue({'suspicious_repeated_unit','fragmented_line'} <= {x['code'] for x in r['issues']})

    def test_full_width_heading_separates_column_bands(self):
        lines = [('Full width heading separating two independent sections', (50,350,950), .99)]
        for base in (100,400):
            for i in range(8):
                lines.extend([(f'Main text long enough to establish the paragraph {base+i}',(100,base+i*20,570),.99),
                              (f'Sidebar {base+i} figures',(650,base+i*20,900),.99)])
        r = self.read(ocr=lambda *_: payload(lines))
        heading = next(i for i,x in enumerate(r['lines']) if x['id']==0)
        self.assertEqual(heading,16)
        self.assertEqual(len({x['id'] for x in r['lines']}),33)

    def test_bad_quad_does_not_drop_text(self):
        raw=payload([('retain this text',(100,100,900),.99)])
        raw['boxes'][0][0][0]=float('nan')
        r=self.read(ocr=lambda *_:raw)
        self.assertEqual(r['text'],raw['text'])
        self.assertEqual(r['status'],'needs_review')

    def test_page_validation_and_native_error(self):
        for page in (0, -1, True, 1.5):
            with self.assertRaises(ValueError): read_page('x', page, native_reader=lambda *_: '')
        def fail(*_): raise ValueError('invalid PDF')
        self.assertEqual(read_page('x',1,native_reader=fail)['status'], 'error')


if __name__ == '__main__': unittest.main()

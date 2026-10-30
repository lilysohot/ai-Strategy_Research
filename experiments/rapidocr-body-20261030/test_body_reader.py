import unittest
from body_reader import read_page


def payload(lines):
    return {'status': 'ok', 'text': '\n'.join(t for t, *_ in lines),
            'lines': [t for t, *_ in lines], 'scores': [s for _, _, s in lines],
            'boxes': [[[x, y], [r, y], [r, y+10], [x, y+10]] for _, (x,y,r), _ in lines],
            'render_pixels': [1000, 1000]}


class ReaderTests(unittest.TestCase):
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

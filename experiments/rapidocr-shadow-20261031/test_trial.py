import copy
import tempfile
from pathlib import Path
import unittest

from trial import digest, pending_review, verify_inputs


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'doc.pdf').write_bytes(b'fixture')
        self.manifest = {'run_id': 'test', 'selected_page_count': 2, 'documents': [
            {'id': 'doc', 'input': 'doc.pdf', 'sha256': digest(self.root/'doc.pdf'),
             'total_pages': 4, 'selected_pages': [1, 3]}]}

    def test_valid_frozen_input(self):
        verify_inputs(self.manifest, self.root)

    def test_changed_input_rejected(self):
        (self.root / 'doc.pdf').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash'):
            verify_inputs(self.manifest, self.root)

    def test_escaping_path_rejected(self):
        for name in ('../doc.pdf', '/doc.pdf'):
            self.manifest['documents'][0]['input'] = name
            with self.assertRaises(ValueError):
                verify_inputs(self.manifest, self.root)

    def test_duplicate_invalid_and_oversize_selection_rejected(self):
        for pages in ([1, 1], [0], [True], [5], list(range(1, 8))):
            manifest = copy.deepcopy(self.manifest)
            manifest['documents'][0].update(selected_pages=pages, total_pages=10 if len(pages)>6 else 4)
            manifest['selected_page_count'] = len(pages)
            with self.assertRaises(ValueError):
                verify_inputs(manifest, self.root)

    def test_ok_never_becomes_human_approval(self):
        records = [{'id': 'doc-p01', 'document': 'doc', 'status': 'ok', 'candidate_sha256': 'a'}]
        review = pending_review(self.manifest, records)
        self.assertEqual(review['pages'][0]['decision'], 'pending')
        self.assertIsNone(review['reviewer'])
        self.assertFalse(review['production_ingestion'])


if __name__ == '__main__':
    unittest.main()

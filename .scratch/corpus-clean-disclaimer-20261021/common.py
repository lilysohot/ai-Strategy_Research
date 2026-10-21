"""Offline reconstruction of frozen reader inputs; never migrate DB checkpoints."""
import json
from plugins.corpus.preparation.contract import CharSpan, DocumentFormat, UnitLocation, UnitStatus
from plugins.corpus.preparation.engine import _validate_parse_checkpoint
from plugins.corpus.preparation.readers.base import CandidateUnit, ReaderIssue, ReaderResult


def restore(checkpoint, source_id):
    data = json.loads(checkpoint)
    assert data['source_id'] == source_id
    result, error = _validate_parse_checkpoint(checkpoint, source_id, data['extractor_rev'])
    if result is not None:
        return result
    assert error == 'checkpoint_schema_mismatch' and data['checkpoint_schema_rev'] == 'parse-checkpoint-2', error
    units = tuple(CandidateUnit(
        ordinal=u['ordinal'], kind=u['kind'], status=UnitStatus(u['status']),
        reasons=tuple(u['reasons']), raw_text=u['raw_text'],
        location=UnitLocation(page=u.get('page'), element=u.get('element'),
            char_span=CharSpan(u['char_start'],u['char_end']) if u.get('char_start') is not None else None,
            bbox=tuple(u['bbox']) if u.get('bbox') else None,
            cells=tuple(tuple(c) for c in (u.get('cells') or ())),
            label_path=tuple(u.get('label_path') or ()))) for u in data['units'])
    assert [u.content_hash for u in units] == data['unit_hashes']
    return ReaderResult(DocumentFormat(data['format']),data['extractor_rev'],data['source_path'],
                        data['page_count'],units,tuple(ReaderIssue(**i) for i in data['issues']))

import json
from collections import Counter
from pathlib import Path
from benchmarks.team_workflow.metrics import measure

root=Path('/home/administrator/.local/share/frontier-agent/web/runs/7d0cecf846254f4895d318299136a688')
tr=root/'run/agent/trajectories'
summary=json.loads((root/'summary.json').read_text())
metrics=measure(root/'run')
native_lists=[]
response_chars=0
list_chars=0
empty_titles=0
hits=0
for p in tr.rglob('*.jsonl'):
    for line in p.read_text().splitlines():
        row=json.loads(line)
        if row.get('t')!='result' or row.get('name')!='corpus_search': continue
        result=json.loads(row['result'])
        unknown=result.get('coverage',{}).get('native',{}).get('unknown_date_sources',[])
        native_lists.append(len(unknown))
        response_chars+=len(row['result'])
        list_chars+=len(json.dumps(unknown,separators=(',',':')))
        for hit in result.get('hits',[]):
            hits+=1
            empty_titles+=not bool(hit.get('title'))
findings={
    'run':root.name,
    'scope':'Read-only artifact audit; no production repair or deployment.',
    'request':'从资料库中，检索出随意一份今天的研报',
    'duration_s':summary['duration_s'],
    'answer_status':summary['answer_status'],
    'stopped_by':summary['stopped_by'],
    'summary_attempts':summary['cache_attempts']['all_attempts'],
    'metrics':metrics,
    'metrics_scope_note':'measure includes the separate intake call (+1 attempt, +9316 input tokens); headline counts use summary all_attempts.',
    'search_response_stats':{'calls':len(native_lists),'total_chars':response_chars,'unknown_date_list_serialized_chars':list_chars,'unknown_date_list_sizes':dict(Counter(native_lists)),'empty_titles':empty_titles,'hits':hits},
    'character_replay':json.loads((Path(__file__).parent/'audit_7d0_characters.json').read_text()),
    'timeline_seconds_from_main_start':[
        {'at':51.8,'event':'First search already returns target as first hit, published=2026-11-06.'},
        {'at':63.0,'event':'Heading original fetched.'},
        {'at':134.7,'event':'Body 0000 and 0001 fetched.'},
        {'at':219.9,'event':'Primary researcher completes after eight searches.'},
        {'at':232.8,'event':'Coordinator stops unnecessary undated-source inquiry.'},
        {'at':254.2,'event':'First verifier begins.'},
        {'at':300.6,'event':'Date/doc/locators verified; claimed verbatim heading fails because coordinator rewrote it.'},
        {'at':390.6,'event':'Recheck submit_report rejects summary instead of content at final turn; no verdict committed.'},
        {'at':563.5,'event':'Retry submits empty arguments; pending-check observer rejects it.'},
        {'at':573.1,'event':'Retry includes verdict but omits required content; final turn, no verdict committed.'},
        {'at':641.8,'event':'Coordinator delivers partial result with misleading raw/hash equality claim.'},
    ],
    'attribution':[
        {'layer':'orchestration and prompt scope','finding':'Existence request expanded to date variants, adjacent dates and all undated sources; 587984 input tokens spent on unnecessary undated researcher. Old 81-source/21-undated inventory reused as assignment premise; new response reports 148/80.'},
        {'layer':'verification and evidence integrity','finding':'Date/existence and exact OCR transcription bundled into one check. Coordinator changed source quote; later scripts compare two model-transcribed strings, not raw tool payload. Four NBSP differences survive; raw payload hashes are valid. Final answer incorrectly says equality to original SHA256.'},
        {'layer':'tool protocol and recovery','finding':'summary alias/unexpected argument, empty args and missing content prevented terminal report submission. Runtime caps one-check verifier at four turns via min(max_turns,2*len(checks)+2); no remaining correction turn. Retrying repeats acquisition instead of repairing only the rejected submission.'},
        {'layer':'tool interface and context','finding':'Repeated unknown-date hashes, empty titles, invalid inventory/hash-based fetch attempts and long reports inflate prompts. Hashes shown as inventory are not usable citation locators; failure to guess them does not prove all underlying documents unreadable.'},
        {'layer':'delivery','finding':'Useful document found, but user receives OCR fragments, internal job/hash/codepoint details and unresolved-check appendix. Cautious partial status is appropriate; the cost and technical burden are not proportional to request.'},
    ],
    'benchmark_mapping':{
        'known_related':'Scope/cost issues resemble F08/F09; missing verdict is related to recovery coverage but not a demonstrated P37 instance because no replacement PASS was accepted.',
        'new_cases_needed':['Find any one matching document and stop once evidence suffices, despite old inventory history and partial corpus coverage.','Final-turn terminal report schema error: preserve verdict payload, bounded repair, no repeated acquisition.','Exact vs normalized quote comparison from actual tool bytes; reject self-copied equality proof and false hash claims.','Catalog source ID to valid retrieval handle path, with compact coverage metadata.'],
    },
    'not_supported_by_this_trace':['No model timeout here; primary outcome final_answer with partial status.','No evidence that initial corpus ranking failed: target was first hit.','No proof of renewed synchronous event-loop blocking: research jobs started about 25 ms after dispatch and overlapped.','Tool-duration sums overlap and must not be called wall-clock attribution.','Recorded tool payload hashes match their text; model claim of tool-side normalization is unsupported.','No evidence that all 80 undated documents are unreadable; only limited invalid access attempts were observed.'],
}
out=Path(__file__).parent/'audit_7d0_findings.json'
out.write_text(json.dumps(findings,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(findings['search_response_stats'],ensure_ascii=False))
print(out)

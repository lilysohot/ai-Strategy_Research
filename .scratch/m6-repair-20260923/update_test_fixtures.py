from pathlib import Path
import ast
r=Path('/home/administrator/FrontierAgent')
p=r/'tests/test_corpus_selection.py';s=p.read_text();lines=s.splitlines(keepends=True);offsets=[0]
for line in lines:offsets.append(offsets[-1]+len(line))
def ix(n, end=False):
 l=n.end_lineno if end else n.lineno;c=n.end_col_offset if end else n.col_offset
 return offsets[l-1]+len(lines[l-1].encode()[:c].decode())
edits=[]
for n in ast.walk(ast.parse(s)):
 if isinstance(n,ast.Tuple) and len(n.elts)==5 and isinstance(n.elts[3],ast.Constant) and n.elts[3].value=='ch':
  edits.append((ix(n.elts[3]),ix(n.elts[3],True),'sha256_of_bytes(('+ast.get_source_segment(s,n.elts[1])+').encode())'))
for a,b,v in sorted(edits,reverse=True):s=s[:a]+v+s[b:]
s=s.replace('from plugins.corpus.preparation.cross_boundary import _merge_chunk','from plugins.corpus.preparation.contract import sha256_of_bytes\nfrom plugins.corpus.preparation.cross_boundary import _merge_chunk');p.write_text(s)
p=r/'tests/test_corpus_context_integrity.py';s=p.read_text(encoding='utf-8-sig');s=s.replace('from unittest.mock import patch','from contextlib import nullcontext\nfrom unittest.mock import patch');s=s.replace('        def cursor(self):','        def transaction(self):\n            return nullcontext()\n\n        def cursor(self):');p.write_text(s)

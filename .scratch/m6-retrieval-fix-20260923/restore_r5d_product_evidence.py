"""Reproduce sealed r5d observations while stripping fields introduced after r5d."""
from pathlib import Path
import json
import runpy
from unittest.mock import patch

ROOT = Path('/home/administrator/FrontierAgent')
RUNNER = ROOT / '.scratch/m6-repair-20260923/run_product_eval.py'
from plugins.tools import get_builtin_tools as current_registry

class PreR5dFetch:
    def __init__(self, wrapped):
        self.wrapped = wrapped

    async def ainvoke(self, args):
        payload = json.loads(await self.wrapped.ainvoke(args))
        payload.pop('semantic_cells', None)
        return json.dumps(payload, ensure_ascii=False)

def registry():
    tools = current_registry()
    tools['corpus_fetch'] = PreR5dFetch(tools['corpus_fetch'])
    return tools

try:
    with patch('plugins.tools.get_builtin_tools', registry):
        runpy.run_path(str(RUNNER), run_name='__main__')
except SystemExit as exc:
    if exc.code != 1:
        raise

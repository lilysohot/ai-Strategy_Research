"""Offline diagnostic: slow backend must not stall another agent's event loop."""
import asyncio
import importlib
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from frontier_agent.core.runtime.loop.tool_exec import execute_tools

module=importlib.import_module('plugins.tools.corpus_search')

class Backend:
    def search_with_coverage(self, query, *, limit):
        time.sleep(0.20)
        return [], {'processing':'complete','availability':'unknown','query_status':'no_match'}

async def main():
    selected=module.corpus_search
    if '--thread-control' in sys.argv:
        async def offloaded(**args):
            return await asyncio.to_thread(lambda: asyncio.run(module.corpus_search.func(**args)))
        selected=replace(selected,func=offloaded)
    started=time.monotonic()
    async def heartbeat():
        await asyncio.sleep(0.01)
        return time.monotonic()-started
    with patch.object(module,'get_service',return_value=Backend()):
        beat=asyncio.create_task(heartbeat())
        results=await execute_tools([
            {'name':'corpus_search','args':{'query':'one'}},
            {'name':'corpus_search','args':{'query':'two'}},
        ],{'corpus_search':selected},timeout=5,turn=1,count_offset=0)
        delay=await beat
    out={'thread_control':'--thread-control' in sys.argv,
         'each_backend_call_seconds':0.20,'elapsed_s':round(time.monotonic()-started,3),
         'heartbeat_scheduled_after_s':0.01,'heartbeat_actual_s':round(delay,3),
         'tool_errors':[r.is_error for r in results]}
    print(json.dumps(out))
    assert delay < 0.10, 'corpus_search blocks the shared event loop; concurrent agents cannot progress'

asyncio.run(main())

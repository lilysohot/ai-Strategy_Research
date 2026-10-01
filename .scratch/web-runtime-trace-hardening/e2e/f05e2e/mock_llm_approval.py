# F21 e2e mock: first turn calls `bash` with a mutating command (confirm-level
# -> parks on the approval gate), then answers. Port 8018 so the API env does
# not change between phases. ASCII-only to avoid codepage issues on Windows.
import time

from deploy.huggingface.mock_llm import MockLLMServer, text_turn, tool_call_turn

server = MockLLMServer(
    script=[
        tool_call_turn("create_file", {"path": "/outputs/answer.md", "content": "# Answer\n"}),
        text_turn("Approval flow finished. This is the final answer."),
    ],
    port=8018,
    require_auth=False,
    chunk_delay_s=0.02,
    verbose=True,
)
with server:
    print("mock llm (approval script) on", server.base_url, flush=True)
    while True:
        time.sleep(3600)

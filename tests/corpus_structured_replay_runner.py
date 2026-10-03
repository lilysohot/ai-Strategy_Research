"""Child-process fixture: real publication and TerminalSession, synthetic I/O only.

This is a test executable, not a live-trial launcher. Guards are installed before
importing repository modules; writer and reader never share Python objects.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shlex
import socket
import sys
import time
from pathlib import Path

ROOT = Path(sys.argv[2]).resolve()
SCENARIO = sys.argv[3]
UNEXPECTED = []
PROBES = []
DOTENV_REFUSED = []
TOKENIZER_DOWNLOADS_REFUSED = []
PROBING = False
FAIL_STORE_READS = False


def deny(kind):
    """Build a fail-closed external boundary with auditable self-test calls."""

    def rejected(*args, **kwargs):
        (PROBES if PROBING else UNEXPECTED).append(kind)
        raise RuntimeError(f"09 replay denied {kind}")

    return rejected


def guard_open(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        path = Path(os.fsdecode(args[0]))
        if path.name == ".env":
            deny("dotenv")()
        if FAIL_STORE_READS and path.is_relative_to(ROOT / "write" / "store"):
            raise OSError("synthetic source resolver unavailable")


sys.addaudithook(guard_open)
socket.socket.connect = deny("network")
socket.socket.connect_ex = deny("network")
socket.create_connection = deny("network")
socket.getaddrinfo = deny("network")

# Explicit adapters at external boundaries, never mocks of the query, ledger,
# workflow, scheduler, manifest, request postprocessors or publication verifier.
import dotenv  # noqa: E402
import dotenv.main  # noqa: E402
import httpx  # noqa: E402
import psycopg  # noqa: E402
import tiktoken.load  # noqa: E402


def refuse_dotenv(*args, **kwargs):
    DOTENV_REFUSED.append("load_dotenv")
    return False


def refuse_tokenizer_download(*args, **kwargs):
    # Optional tokenizer assets are an external resource, not a model call.
    # Exercise the real estimator's offline fallback instead of warming caches
    # over the network or making these tests depend on host cache availability.
    TOKENIZER_DOWNLOADS_REFUSED.append("tokenizer_asset")
    raise OSError("09 replay has no tokenizer download transport")


dotenv.load_dotenv = dotenv.main.load_dotenv = refuse_dotenv
dotenv.dotenv_values = dotenv.main.dotenv_values = deny("dotenv")
httpx.HTTPTransport.handle_request = deny("network")
httpx.AsyncHTTPTransport.handle_async_request = deny("network")
psycopg.connect = deny("production_db")
psycopg.AsyncConnection.connect = deny("production_db")
tiktoken.load.read_file = refuse_tokenizer_download

from frontier_agent.infra import config  # noqa: E402

config.FrontierAgentConfig.model_config["env_file"] = None

from frontier_agent.infra.anthropic_client import AnthropicClient  # noqa: E402
from frontier_agent.infra.openai_client import OpenAIClient  # noqa: E402
from frontier_agent.infra.openai_responses_client import OpenAIResponsesClient  # noqa: E402
from plugins.corpus.service import CorpusService  # noqa: E402

for client in (OpenAIClient, OpenAIResponsesClient, AnthropicClient):
    client.__init__ = deny("model")
CorpusService._connect = deny("production_db")


def probe_guards():
    global PROBING
    PROBING = True
    for probe in (
        lambda: socket.create_connection(("synthetic.invalid", 443)),
        lambda: dotenv.dotenv_values(".env"),
        lambda: CorpusService._connect(None),
        lambda: OpenAIClient(model="synthetic", api_key="fake"),
    ):
        try:
            probe()
        except RuntimeError:
            pass
        else:
            raise AssertionError("external boundary guard did not reject probe")
    PROBING = False


def save_result(payload):
    payload.update(
        pid=os.getpid(),
        cwd=str(Path.cwd()),
        guard_probes=PROBES,
        unexpected_access=UNEXPECTED,
        dotenv_loads_refused=len(DOTENV_REFUSED),
        tokenizer_downloads_refused=len(TOKENIZER_DOWNLOADS_REFUSED),
        real_model_calls=0,
        production_database_access=0,
    )
    Path("replay-result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_publication():
    from test_corpus_structured_publication import forecast_artifacts

    from plugins.corpus.structured.store import publish_semantic

    if SCENARIO == "downstream_trim":
        from test_corpus_structured_query import published_material_with_condition

        snapshot, store, publication = published_material_with_condition(Path.cwd(), extra_units=8)
        save_result(
            {
                "source_id": snapshot.source_id,
                "build_id": snapshot.build_id,
                "snapshot_id": snapshot.snapshot_id,
                "publication_id": publication.publication_id,
                "store": str(store),
                "roles": ["material_items"],
                "snapshot": snapshot.model_dump(mode="json"),
            }
        )
        return
    if SCENARIO == "missing_footnote":
        from test_corpus_structured_publication import BUILD_ID, SOURCE_ID, Reader

        from plugins.corpus.structured.snapshot import (
            SnapshotBuildSource,
            SnapshotDependencySource,
            SnapshotDocumentSource,
            SnapshotHead,
            SnapshotUnitSource,
            build_snapshot,
        )

        override = build_snapshot(
            Reader(
                SnapshotBuildSource(
                    head=SnapshotHead(
                        source_id=SOURCE_ID, build_id=BUILD_ID, publication_generation=1
                    ),
                    parser_versions={"parse": "p1", "clean": "c1", "chunk": "k1"},
                    document=SnapshotDocumentSource(title="缺脚注合成材料", subject="999999.SZ"),
                    units=(
                        SnapshotUnitSource(
                            source_unit_id="forecast-u",
                            chunk_id="forecast-c",
                            kind="prose",
                            text="999999.SZ 2026年营业收入15亿元。",
                            locator="page:1/paragraph:1",
                            ordinal=1,
                            dependencies=(
                                SnapshotDependencySource(
                                    kind="footnote",
                                    target_unit_id=None,
                                    status="missing",
                                    required_for=("cite", "compare", "calculate"),
                                    reason="synthetic missing footnote",
                                ),
                            ),
                        ),
                    ),
                )
            ),
            SOURCE_ID,
        )
    if SCENARIO == "missing_footnote":
        from plugins.corpus.structured.ledger import plan_batch, replay_batch

        plan = plan_batch(override, max_attempts=2, relations_enabled=False)
        responses = Path.cwd() / "responses"
        responses.mkdir()
        store = Path.cwd() / "store"
        checked = replay_batch(plan, responses=responses, store_root=store)
        save_result(
            {
                "source_id": override.source_id,
                "build_id": override.build_id,
                "snapshot_id": override.snapshot_id,
                "plan_sha256": plan.plan_sha256,
                "publication_id": None,
                "store": str(store),
                "roles": [],
                "execution": checked.model_dump(mode="json"),
                "snapshot": override.model_dump(mode="json"),
            }
        )
        return
    snapshot, plan, store, references, checked = forecast_artifacts(
        Path.cwd(),
        item_overrides={"value": "15亿元"},
    )
    assert all(t.quality_status == "accepted" for t in checked.ledger.tasks), (
        checked.model_dump_json()
    )
    publication = publish_semantic(
        source_id=snapshot.source_id,
        build_id=snapshot.build_id,
        snapshot_id=snapshot.snapshot_id,
        artifacts=tuple(references.values()),
        expected_parent_publication_id=None,
        store_root=store,
    )
    payload = {
        "source_id": snapshot.source_id,
        "build_id": snapshot.build_id,
        "snapshot_id": snapshot.snapshot_id,
        "plan_sha256": plan.plan_sha256,
        "publication_id": publication.publication_id,
        "store": str(store),
        "roles": sorted(references),
        "execution": checked.model_dump(mode="json"),
        "snapshot": snapshot.model_dump(mode="json"),
    }
    save_result(payload)


def withdraw_publication():
    from plugins.corpus.structured.store import retire_semantic

    source = json.loads((ROOT / "write" / "replay-result.json").read_text())
    retire_semantic(
        source_id=source["source_id"],
        build_id=source["build_id"],
        expected_parent_publication_id=source["publication_id"],
        store_root=source["store"],
    )


def install_source_adapter(source):
    """Replace only the PG source port with the exact frozen synthetic unit."""
    from plugins.corpus.preparation.read_pg import ChunkEvidence, UnitEvidence, UnknownHandleError

    unit = source["snapshot"]["units"][0]

    def fetch(self, doc_id, locator):
        if doc_id != f"cv2:{source['build_id']}" or locator != "chunk:forecast-c":
            raise UnknownHandleError("synthetic build/chunk mismatch")
        text = unit["text"]
        return ChunkEvidence(
            source_id=source["source_id"],
            build_id=source["build_id"],
            chunk_id="forecast-c",
            kind="prose",
            title_text="合成材料",
            section_path=(),
            units=(UnitEvidence("forecast-u", text, 1, "paragraph", ()),),
            text=text,
            source_ranges=((0, len(text)),),
            spans=(("forecast-u", 0, len(text)),),
            active=True,
        )

    CorpusService.fetch_verbatim = fetch
    CorpusService.emit_cells = lambda *a, **k: []
    CorpusService.context_relations = lambda *a, **k: {}


def install_market_transport():
    """Supply frozen provider payloads below the real market adapter/service/tool."""
    from plugins.market.adapters.fuyao_rest import PATH_SEARCH, PATH_SNAPSHOT, PATH_VALUATIONS
    from plugins.market.transport import MarketTransport

    os.environ["THS_API_KEY"] = "synthetic-market-key"
    rows = {
        PATH_SEARCH: {"thscode": "999999.SZ", "ticker": "999999", "name": "虚构公司"},
        PATH_SNAPSHOT: {"thscode": "999999.SZ", "last_price": 15},
        PATH_VALUATIONS: {"thscode": "999999.SZ", "name": "虚构公司", "pe_ttm": 10},
    }

    def get(self, path, params=None, **kwargs):
        assert path in rows, path
        return {"code": 0, "data": {"timestamp": 1767225600000, "item": [rows[path]]}}

    MarketTransport.get = get


class ReplayFailure(BaseException):
    """Stop a broken fixture immediately instead of exercising provider retries."""


class ReplayMain:
    """Scripted provider receiving the actual postprocessed product requests."""

    model = "synthetic-main"

    def __init__(self, source):
        self.source = source
        self.requests = []
        self.tool_calls = []
        self.report = "合成公司2026年营业收入为15亿元。"
        if SCENARIO == "downstream_trim":
            self.report = "仅在合成许可获批时，虚构公司2026年收入15亿元的结论成立。"

    def answer(self, messages, kwargs):
        global FAIL_STORE_READS
        from frontier_agent.core.llm import LLMResponse
        from plugins.corpus.ledger import get_run_ledger

        self.requests.append(
            copy.deepcopy(
                {
                    "messages": messages,
                    "tools": kwargs.get("tools"),
                    "delivery_before_response": [
                        dict(r.statuses) for r in get_run_ledger().semantic.receipts
                    ],
                }
            )
        )
        step = len(self.requests)
        if SCENARIO == "readonly":
            if step == 1:
                # Opening without truncation probes write authority without
                # modifying existing publication data, even before the fix.
                script = "\n".join(
                    [
                        "import os, pathlib, sys",
                        f"root = pathlib.Path({self.source['store']!r})",
                        "targets = [*root.glob('index/*'), *root.glob('manifests/*.json'), *root.glob('objects/sha256/*/*')]",
                        "assert targets",
                        "for target in targets:",
                        "    try:",
                        "        fd = os.open(target, os.O_WRONLY)",
                        "    except PermissionError:",
                        "        continue",
                        "    except OSError as exc:",
                        "        if exc.errno == 30: continue",
                        "        raise",
                        "    else:",
                        "        os.close(fd)",
                        "        sys.exit('WRITABLE_STORE')",
                        "for parent in [root, root / 'index', root / 'objects', root / 'manifests']:",
                        "    path = parent / '.readonly-probe'",
                        "    try:",
                        "        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)",
                        "    except OSError as exc:",
                        "        if exc.errno in (1, 13, 30): continue",
                        "        raise",
                        "    else:",
                        "        os.close(fd)",
                        "        path.unlink()",
                        "        sys.exit('WRITABLE_STORE_DIRECTORY')",
                        "try:",
                        "    targets[0].chmod(targets[0].stat().st_mode)",
                        "except OSError as exc:",
                        "    if exc.errno not in (1, 13, 30): raise",
                        "else:",
                        "    sys.exit('WRITABLE_STORE_PERMISSIONS')",
                        "print('READONLY_CONFIRMED')",
                    ]
                )
                self.tool_calls.append("bash")
                return LLMResponse(
                    content="",
                    tool_calls=[
                        {
                            "id": "readonly-probe",
                            "type": "function",
                            "function": {
                                "name": "bash",
                                "arguments": json.dumps(
                                    {
                                        "command": shlex.join([sys.executable, "-c", script]),
                                        "description": "Check publication store write denial without changing data",
                                    }
                                ),
                            },
                        }
                    ],
                    finish_reason="tool_calls",
                )
            step -= 1
        if SCENARIO == "market":
            if step == 1:
                self.tool_calls.append("market_quote")
                return LLMResponse(
                    content="",
                    tool_calls=[
                        {
                            "id": "market-fixed",
                            "type": "function",
                            "function": {
                                "name": "market_quote",
                                "arguments": '{"query":"999999.SZ"}',
                            },
                        }
                    ],
                    finish_reason="tool_calls",
                )
            step -= 1
        budget_case = SCENARIO in {"budget", "downstream_trim"}
        retry_budget = budget_case and step == 2
        if budget_case and step > 2:
            step -= 1
        root_fallback = SCENARIO in {"missing_root", "invisible_root"}
        source_mode = SCENARIO == "legacy" or (root_fallback and step > 1)
        if root_fallback and step > 1:
            if step == 2:
                error = next(m["content"] for m in reversed(messages) if m["role"] == "tool")
                expected = (
                    "CS_NOT_FOUND" if SCENARIO == "invisible_root" else "CS_STORE_ROOT_REQUIRED"
                )
                assert expected in error, error
            step -= 1
        if step == 1 or retry_budget:
            name = "corpus_semantic_query"
            args = {key: self.source[key] for key in ("source_id", "build_id")}
            args["purpose"] = "cite"
            if SCENARIO == "budget" and step == 1:
                args["max_chars"] = 700
            if SCENARIO == "downstream_trim":
                args["max_chars"] = 20_000 if step == 1 else 5500
                if retry_budget:
                    args["limit"] = 1
                    args["query_text"] = "虚构公司2026年收入15亿元"
            if retry_budget:
                gap = json.loads(
                    next(m["content"] for m in reversed(messages) if m["role"] == "tool")
                )
                assert gap["page_status"] == "budget_limited" and not gap["records"]
            if source_mode:
                name = "corpus_fetch"
                args = {"doc_id": f"cv2:{self.source['build_id']}", "locator": "chunk:forecast-c"}
        elif step == 2:
            page = json.loads(next(m["content"] for m in reversed(messages) if m["role"] == "tool"))
            if SCENARIO == "missing_footnote":
                assert not page["records"] and page["page_status"] == "not_published", page
                return LLMResponse(
                    content="语义证据尚未发布，无法支持收入结论。", finish_reason="stop"
                )
            name = "corpus_submit_manifest"
            conclusion = {
                "id": "C1",
                "text_location": "合成报告第一段",
                "report_quote": self.report,
            }
            if source_mode:
                assert page["ok"], page
                conclusion["evidence"] = [
                    {
                        "doc_id": page["doc_id"],
                        "locator": page["locator"],
                        "quote": page["text"],
                        "purpose": "value",
                    }
                ]
            else:
                assert {r["role"] for r in page["records"]} == (
                    {"material_items"}
                    if SCENARIO == "downstream_trim"
                    else {"claims", "material_items"}
                ), page
                conclusion["semantic_references"] = [
                    {
                        "publication_id": page["publication_id"],
                        "record_id": r["record_id"],
                        "purpose": "cite",
                    }
                    for r in page["records"]
                ]
            args = {"conclusions": [conclusion]}
            if SCENARIO == "bad_handle":
                from plugins.corpus.structured.consumption import reference_for_record
                from plugins.corpus.structured.query import SemanticQueryRecord

                ref = reference_for_record(
                    page["publication_id"],
                    SemanticQueryRecord.model_validate(page["records"][0]),
                    "cite",
                    "C1",
                    self.report,
                ).model_dump(mode="json")
                ref["evidence_ranges"][0]["handle"] = "cv2:wrong#chunk:wrong"
                args["conclusions"][0]["semantic_references"] = [ref]
        elif step == 3:
            manifest = json.loads(
                next(m["content"] for m in reversed(messages) if m["role"] == "tool")
            )
            if SCENARIO == "missing_footnote":
                assert manifest["publish_status"] != "verified", manifest
            else:
                assert manifest["publish_status"] == (
                    "unsupported" if SCENARIO == "bad_handle" else "verified"
                ), manifest
            if SCENARIO == "withdrawn":
                Path("withdraw.request").touch()
                deadline = time.monotonic() + 10
                while not Path("withdraw.ack").exists():
                    assert time.monotonic() < deadline, "external writer did not acknowledge"
                    time.sleep(0.02)
            if SCENARIO == "resolver_error":
                FAIL_STORE_READS = True
            return LLMResponse(content=self.report, finish_reason="stop")
        else:
            raise AssertionError("unexpected extra model request")
        self.tool_calls.append(name)
        return LLMResponse(
            content="",
            tool_calls=[
                {
                    "id": f"replay-{len(self.requests)}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
                }
            ],
            finish_reason="tool_calls",
        )

    async def chat(self, messages, **kwargs):
        try:
            return self.answer(messages, kwargs)
        except Exception as exc:
            raise ReplayFailure(str(exc)) from exc

    async def stream(self, messages, **kwargs):
        from frontier_agent.core.llm import StreamDelta

        response = await self.chat(messages, **kwargs)
        yield StreamDelta(
            content=response.content or "",
            tool_call_deltas=[
                {
                    "index": index,
                    "id": call["id"],
                    "name": call["function"]["name"],
                    "arguments": call["function"]["arguments"],
                }
                for index, call in enumerate(response.tool_calls or [])
            ],
        )


async def research():
    source = json.loads((ROOT / "write" / "replay-result.json").read_text())
    os.environ["CORPUS_STRUCTURED_ROOT"] = source["store"]
    if SCENARIO == "missing_root":
        os.environ.pop("CORPUS_STRUCTURED_ROOT")
    if SCENARIO == "invisible_root":
        # Simulate a writer root not mounted into the new research environment.
        os.environ["CORPUS_STRUCTURED_ROOT"] = str(ROOT / "unmounted-store")
    if SCENARIO in {"missing_root", "invisible_root", "legacy"}:
        install_source_adapter(source)
    if SCENARIO == "market":
        install_market_transport()

    import apodex.session as session_module
    import frontier_agent.infra.llm_adapter as llm_adapter
    import workflows.stateful_react_agent.profile as workflow_profile
    from apodex.config import ModelConfig
    from apodex.profiles import get_profile
    from apodex.render import Renderer
    from plugins.corpus.ledger import VERIFICATION_FILENAME, get_run_ledger, resolve_artifact_dir

    llm = ReplayMain(source)
    session_module.build_llm = lambda *a, **k: llm
    llm_adapter.create_llm = lambda *a, **k: llm
    workflow_profile.create_react_llm = lambda *a, **k: llm
    session = session_module.TerminalSession(
        cfg=ModelConfig(model=llm.model, api_key="fake", base_url="https://synthetic.invalid"),
        cwd=str(Path.cwd()),
        renderer=Renderer(color=False),
        auto_approve=True,
        interactive=False,
        max_turns=8,
        mode="react",
    )
    session.tui_mode = True  # The same TerminalSession API used by Textual.
    try:
        await session.run_task("读取已发布合成材料，提交证据清单并生成中文报告。")
    except ValueError as exc:
        if SCENARIO not in {"writable_root", "nested_writable"}:
            raise
        save_result({"startup_error": str(exc), "model_calls": len(llm.requests)})
        return
    folder = resolve_artifact_dir()
    assert folder is not None
    verification = json.loads((folder / VERIFICATION_FILENAME).read_text())
    tools = [t["function"]["name"] for t in llm.requests[0]["tools"]]
    save_result(
        {
            "profile": get_profile("react").workflow_profile,
            "tools": tools,
            "tool_calls": llm.tool_calls,
            "model_calls": len(llm.requests),
            "requests": llm.requests,
            "verification": verification,
            "ledger": get_run_ledger().to_dict(),
            "trace_path": str(session.trace_path),
            "run_dir": os.environ["APODEX_RUN_DIR"],
            "publication_id": source["publication_id"],
            "display_history": session.display_history,
        }
    )


if __name__ == "__main__":
    probe_guards()
    if sys.argv[1] == "write":
        write_publication()
    elif sys.argv[1] == "retire":
        withdraw_publication()
    else:
        asyncio.run(research())
    if sys.argv[1] in {"write", "retire"}:
        from plugins.corpus.structured.store import prepare_readonly_access

        prepare_readonly_access(store_root=Path.cwd() / "store")

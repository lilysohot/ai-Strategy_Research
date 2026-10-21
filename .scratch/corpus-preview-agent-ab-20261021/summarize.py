"""Replay the real deterministic post-processor over untruncated observed tool results.

Trajectory files store pre-processor results and truncate long diagnostic messages;
they establish order only, and cannot be counted as the model's full tool input.
"""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from frontier_agent.core.loop_types import ToolResult
from workflows.stateful_react_agent._runtime import ReactToolResultPostProcessor

PROCESSOR = ReactToolResultPostProcessor()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def compact(text):
    return "".join(text.split()).casefold()


rows = []
answers = ["# 小范围主 agent 对照：答案与取证记录", ""]
for path in sorted((HERE / "runs").glob("*/*/result.json")):
    row = load(path)
    obs = load(path.with_name("observations.json"))
    trajectory = load(path.parent / "agent/trajectories/react_agent.json")
    messages = trajectory["messages"]
    by_id = {t["tool_call_id"]: t for t in obs["tools"]}
    texts, seen_parts, searches, fetches = [], set(), [], []
    last_assistant = max((i for i, msg in enumerate(messages) if msg.get("role") == "assistant"), default=-1)
    row["fetch_text_chars"] = row["unique_fetch_text_chars"] = row["search_payload_chars"] = 0
    row["consumed_fetch_text_chars"] = 0
    for i, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        tool = by_id.get(msg.get("tool_call_id"))
        if not tool:
            continue
        processed = PROCESSOR.process(ToolResult(**{k: v for k, v in tool.items() if k != "turn"}))
        try:
            body = json.loads(processed)
        except (json.JSONDecodeError, TypeError):
            continue
        if tool["name"] == "corpus_search":
            row["search_payload_chars"] += len(processed)
            searches.append({"query": tool["args"].get("query"), "count": body.get("count"),
                             "delivery_preview": body.get("delivery_preview"),
                             "coverage": body.get("coverage"),
                             "previews": sum(bool(h.get("preview", {}).get("text")) for h in body.get("hits", [])),
                             "locators": [h.get("locator") for h in body.get("hits", [])]})
        if tool["name"] != "corpus_fetch":
            continue
        parts = body.get("items", [body])
        call_chars = 0
        for part in parts:
            value = part.get("text", "")
            if not value:
                continue
            texts.append(value)
            call_chars += len(value)
            key = (body.get("doc_id", tool["args"].get("doc_id")), part.get("locator"), value)
            if key not in seen_parts:
                seen_parts.add(key)
                row["unique_fetch_text_chars"] += len(value)
        row["fetch_text_chars"] += call_chars
        if i < last_assistant:
            row["consumed_fetch_text_chars"] += call_chars
        fetches.append({"args": tool["args"], "text_chars": call_chars,
                        "fetch_complete": body.get("fetch_complete"), "ok": body.get("ok"),
                        "locators_returned": [p.get("locator") for p in parts if p.get("text")],
                        "followed_by_assistant": i < last_assistant})
    row["searches"] = searches
    row["fetches"] = fetches
    assert len(searches) == row["search_calls"], "A search result was not counted"
    assert len(fetches) == row["fetch_calls"], "A fetch result was not counted"
    row["trajectory_model"] = trajectory.get("model_name")
    row["trajectory_stop"] = trajectory.get("stopped_by")
    row["manifest_calls"] = sum(t["name"] == "corpus_submit_manifest" for t in obs["tools"])
    row["manifest_results"] = []
    for tool in obs["tools"]:
        if tool["name"] == "corpus_submit_manifest":
            payload = json.loads(tool["result"])
            row["manifest_results"].append({k: payload.get(k) for k in ("publish_status", "counts", "conclusions")})
    row["retrieval_fallbacks"] = sum(s.get("coverage", {}).get("retrieval", {}).get("used") == "lexical" for s in searches)
    row["query_embedding_tokens_reported"] = sum(s.get("coverage", {}).get("retrieval", {}).get("query_usage", {}).get("total_tokens", 0) for s in searches)
    row["preview_statuses"] = [s["delivery_preview"] for s in searches]
    row["tool_duration_ms"] = sum(t["duration_ms"] for t in obs["tools"])
    row["llm_attempt_duration_ms"] = sum(a.get("duration_ms") or 0 for a in obs["attempts"])
    corpus = compact("\n".join(texts))
    if row["case"] == "p16":
        row["diagnostic_terms_in_fetched_text"] = {term: compact(term) in corpus for term in ("华工正源", "6.4T", "去DSP", "立讯技术", "3.2T", "Live Demo")}
    row["total_usage"] = {key: sum(u.get(key, 0) or 0 for u in row.get("usage_responses", []) if isinstance(u, dict))
                          for key in ("prompt_tokens", "completion_tokens", "cache_read_tokens")}
    row["total_usage"]["total_tokens"] = row["total_usage"]["prompt_tokens"] + row["total_usage"]["completion_tokens"]
    rows.append(row)
    answers += [f"## {row['case']} / {row['mode']}", "", row["question"], "",
                str(row.get("final_answer") or "没有最终答案"), "",
                f"耗时 {row.get('elapsed_s')} 秒；search {row.get('search_calls')} 次；fetch {row.get('fetch_calls')} 次；"
                f"返回正文 {row['fetch_text_chars']} 字符；重复相同片段去重后 {row['unique_fetch_text_chars']} 字符。", "",
                "```json", json.dumps({"searches": searches, "fetches": fetches}, ensure_ascii=False, indent=2), "```", ""]
(HERE / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
(HERE / "answers.md").write_text("\n".join(answers), encoding="utf-8")
if len(rows) == 6:
    assert {r["case"] for r in rows} == {"p01", "p16", "n01"}
    for cid in ("p01", "p16", "n01"):
        pair = [r for r in rows if r["case"] == cid]
        assert {r["mode"] for r in pair} == {"off", "pilot"}
        for key in ("prompt_sha256", "manifest_sha256", "vector_profile", "model", "profile_overrides"):
            assert pair[0][key] == pair[1][key], (cid, key)
    snapshots = {s["coverage"]["publication_snapshot_ref"] for r in rows for s in r["searches"]}
    assert len(snapshots) == 1
    assert all(all(v == "pilot" for v in r["preview_statuses"]) for r in rows if r["mode"] == "pilot")
    assert all(all(v is None for v in r["preview_statuses"]) for r in rows if r["mode"] == "off")
    audit = {"runs": len(rows), "paired_prompt_model_profile_checks": "passed",
             "publication_snapshots": sorted(snapshots),
             "retrieval_fallbacks": sum(r["retrieval_fallbacks"] for r in rows),
             "search_calls": sum(r["search_calls"] for r in rows),
             "fetch_calls": sum(r["fetch_calls"] for r in rows),
             "reported_query_embedding_tokens": sum(r["query_embedding_tokens_reported"] for r in rows),
             "new_document_embeddings": 0,
             "text_measurement": "Deterministic replay of current real workflow post-processor over original full tool results; not truncated trajectory bodies. Followed by assistant response, not proof of semantic reading. Exact duplicate text parts only are deduplicated."}
    (HERE / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
for row in rows:
    print(json.dumps({k: row.get(k) for k in ("case", "mode", "elapsed_s", "search_calls", "fetch_calls", "fetch_text_chars", "consumed_fetch_text_chars", "trajectory_stop", "total_usage")}, ensure_ascii=False))

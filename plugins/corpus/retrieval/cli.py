"""Isolated pilot commands: python -m plugins.corpus.retrieval.cli --help."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from plugins.corpus.retrieval.context import load_source_metadata
from plugins.corpus.retrieval.embedding import DoubaoEmbedder, EmbeddingError, VectorConfig
from plugins.corpus.retrieval.index_pg import VectorIndex


def pilot_dsn(config: VectorConfig) -> str:
    """Reuse PG connection credentials, overriding database only in this process."""
    from plugins.corpus.service import dsn

    fields = conninfo_to_dict(dsn())
    if not config.target_db.startswith("vector_pilot_"):
        raise EmbeddingError("pilot_target_name_required")
    fields["dbname"] = config.target_db
    value = make_conninfo("", **fields)
    os.environ["CORPUS_TARGET_DB"] = config.target_db
    os.environ["CORPUS_DSN"] = value
    os.environ["CORPUS_READ_CHAIN"] = "new"
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "status",
            "init",
            "metadata",
            "build",
            "query",
            "compare",
            "native-query",
            "native-sync",
        ),
    )
    parser.add_argument("--max-requests", type=int)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument(
        "--retry-uncertain",
        action="store_true",
        help="Explicitly retry unknown outcomes; may incur duplicate provider cost.",
    )
    parser.add_argument("--query", default="")
    parser.add_argument("--mode", choices=("lexical", "hybrid"), default="hybrid")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--metadata-file", type=Path)
    parser.add_argument("--native-index", type=Path)
    parser.add_argument("--char-budget", type=int, default=16000)
    parser.add_argument("--deployment", choices=("pilot", "release"), default="pilot")
    args = parser.parse_args()
    if args.max_requests is None:
        args.max_requests = 0 if args.command == "native-sync" else 10
    if args.limit is None:
        args.limit = 20 if args.command == "native-query" else 10
    if args.max_requests < 0 or not 1 <= args.limit <= 20:
        parser.error("--max-requests must be >= 0; --limit must be between 1 and 20")
    load_dotenv()
    try:
        config = VectorConfig.from_env()
        if args.deployment == "release":
            from plugins.corpus.retrieval.native_live import enabled
            from plugins.corpus.service import dsn

            if args.command not in ("query", "native-query", "native-sync"):
                parser.error("release deployment supports query, native-query and native-sync")
            if os.getenv("CORPUS_NATIVE_RETRIEVAL") != "release" or not enabled(config.target_db):
                raise EmbeddingError("native_release_not_enabled")
            target = dsn()
            if conninfo_to_dict(target).get("dbname") != config.target_db:
                raise EmbeddingError("native_release_dsn_mismatch")
        else:
            target = pilot_dsn(config)
        index = VectorIndex(target, config)
        if args.command == "init":
            index.initialize()
            output = index.status()
        elif args.command == "metadata":
            if args.metadata_file is None:
                parser.error("--metadata-file is required for metadata")
            output = index.load_metadata(load_source_metadata(args.metadata_file))
        elif args.command == "status":
            output = index.status()
        elif args.command == "build":
            if args.max_requests and not config.api_key:
                raise EmbeddingError("api_key_missing")
            index.initialize()
            output = index.build(
                DoubaoEmbedder(config).embed,
                max_requests=args.max_requests,
                retry_failed=args.retry_failed,
                retry_uncertain=args.retry_uncertain,
            )
        elif args.command == "native-sync":
            if args.native_index is None:
                parser.error("native-sync requires --native-index")
            from plugins.corpus.retrieval.native import NativeIndex
            from plugins.corpus.retrieval.native_sync import sync

            output = sync(
                target,
                config.target_db,
                NativeIndex(args.native_index),
                config,
                DoubaoEmbedder(config).embed,
                max_requests=args.max_requests,
            )
        elif args.command == "native-query":
            if not args.query.strip() or args.native_index is None:
                parser.error("native-query requires --query and --native-index")
            if not 1 <= args.char_budget <= 16000:
                parser.error("--char-budget must be between 1 and 16000")
            from plugins.corpus.retrieval.native import NativeIndex
            from plugins.corpus.service import CorpusService

            output = asdict(
                CorpusService(target).search_native_evidence(
                    args.query,
                    index=NativeIndex(args.native_index),
                    limit=args.limit,
                    char_budget=args.char_budget,
                )
            )
        else:
            if not args.query.strip():
                parser.error("--query is required")
            from plugins.corpus.service import CorpusService

            results: dict[str, object] = {}
            for mode in ("lexical", "hybrid") if args.command == "compare" else (args.mode,):
                os.environ["CORPUS_RETRIEVAL_MODE"] = mode
                start = time.monotonic()
                hits, coverage = CorpusService(target).search_with_coverage(
                    args.query, limit=args.limit
                )
                results[mode] = {
                    "hits": [asdict(hit) for hit in hits],
                    "coverage": coverage,
                    "elapsed_ms": round((time.monotonic() - start) * 1000),
                }
            output = {"query": args.query, "results": results}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 1 if output.get("error_code") else 0
    except EmbeddingError as exc:
        print(json.dumps({"error_code": exc.code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

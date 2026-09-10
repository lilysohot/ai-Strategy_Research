#!/usr/bin/env bash
#
# 一键跑批：把 data/corpus/ 里的新研报入库，并留下台账。
#
# 用法（WSL / Linux 终端）：
#     bash scripts/ingest-corpus.sh
#
# 做了什么：
#   1. 扫描 data/corpus/，只解析**新增或内容有变**的文件（已入过的跳过，不重复解析）
#   2. 跳过最近 60 秒内刚被修改的文件（可能还在拷贝，避免解析到只写了一半的 PDF）
#   3. 结果写进台账（数据库 + data/corpus_runs/runs.jsonl）
#   4. 打印最近 5 次跑批概览
#
# 退出码：0 全部成功 | 1 有失败/空文档（需要人看）| 2 跑批没跑起来（如数据库不可达）
#
set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

echo "┌─ 语料跑批 ─────────────────────────────────────────"
uv run python -m plugins.corpus.service ingest --trigger script
code=$?
echo "└────────────────────────────────────────────────────"

echo
echo "── 最近 5 次跑批 ──"
uv run python -m plugins.corpus.service runs --limit 5

echo
case "$code" in
  0) echo "✅ 全部成功" ;;
  1) echo "⚠️  跑完了，但有失败/空文档 —— 用下面这条看是哪份："
     echo "    uv run python -m plugins.corpus.service failures" ;;
  2) echo "❌ 跑批没跑起来（数据库不可达？已有跑批在跑？）—— 看上面的错误信息" ;;
esac

exit "$code"

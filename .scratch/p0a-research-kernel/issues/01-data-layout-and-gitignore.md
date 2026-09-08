# 01 · 数据落地骨架与 .gitignore

Type: task
Status: closed
Blocked by: (none)

**Goal**: 建立资料库的数据落地位置，并确保大数据永不进 git。

**Why it first**: 后续所有入库任务都要往这里写；先定位置可避免中途迁移。
远期全量 8000 份原文按 5–20GB 估，一旦误入库几乎不可逆。

**Work**
- 建 `data/corpus/`（仓库根），子目录：
  - `originals/` — 原文不可变存档（P0b 起用，按 `report_id` 组织）
  - `corpus.db` — SQLite WAL（P0b 起用）
  - `manifest.json` — 报告级元数据（P0b 起用）
- 在 `.gitignore` 追加 `data/corpus/`（或 `data/`）
- 确认 `.gitignore` 已忽略的既有项（`server/runs/`、`uploads/`、`server/*.db`）未被本改动误伤

**Decisions already made**
- 用 `data/corpus/` 而非原研报方案的 `plugins/fin_data/`：`plugins/` 是代码层，
  数据塞进去会拖慢 `import_smoke.py` 分层扫描、`ruff` 遍历与备份。
- `deploy/Dockerfile.web` 已挂载 `../data`，无需改部署。

**Acceptance**
- `git check-ignore -v data/corpus/corpus.db` 命中
- `data/corpus/` 目录存在且可被非 root 写入
- `git status` 在放入大文件前后均干净

## Answer

- 已建 `data/corpus/` + `data/corpus/originals/`（各带 `.gitkeep`），并放了一份
  `data/corpus/README.md` 说明 L1/L2/L3 分层与「为何不放 `plugins/fin_data/`」。
- `.gitignore`：仓库根**已有**裸 `data/`（第 56 行），
  `git check-ignore -v data/corpus/corpus.db` 命中它。仍**显式**追加了
  `data/corpus/` 并写明理由：让这条命令直接指向这一行，
  不依赖读者回溯到泛化的 `data/`。
- 既有忽略项未被误伤（`server/runs/`、`uploads/`、`server/*.db` 原样保留）。

**实测**：`git check-ignore -v data/corpus/corpus.db` → `.gitignore:56:data/`。
（命中的是既有那条；`data/corpus/` 是第二重保险。）

⚠️ 副作用：`data/` 是整目录忽略，`data/corpus/README.md` **不会进 git**。
它是给本机操作者看的；目录骨架的真正来源是 P0b 的 ingest（`mkdir -p`），
gitignore 里那行显式规则才是可提交的那份说明。

## Comments

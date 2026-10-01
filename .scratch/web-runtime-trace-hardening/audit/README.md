# 存储审核复现脚本

这些脚本是 2026-09-29 存储链路审核的证据，不是已修复后的回归套件。
默认检查修复后应满足的契约，当前失败是预期的缺陷证据；未加入常规测试发现目录。

- `run_audit.py`：创建临时数据根及 SQLite，阻断网络连接/子进程，再运行明确选定的 pytest 文件。
  2026-09-30 为在本机 Windows 复现做了三处可移植性调整，隔离与阻断保证不变：
  ① 先导入 `asyncio`（否则 `asyncio.windows_utils` 在 `subprocess.Popen` 被替换后无法定义子类）；
  ② 放行 `socket.socketpair()`（Windows proactor 事件循环的自管道走 AF_INET 回环 connect，
  否则 fixture 阶段即被断网守卫拒绝）；③ 显式阻断 `asyncio.create_subprocess_exec/_shell`
  （Windows 上它们走导入期捕获的原始 `Popen`，只改 `subprocess.Popen` 拦不住）。
  契约断言与目标选择未改动；两轮结果口径因此可比。
- `test_storage_chain.py`：真实 ASGI 路由、store、observer、relay、恢复、产物/回滚路径；24 个检查。
  2026-10-01：夹具里 `monkeypatch.setattr(cfg, "uploads_root", …)` 一行随 F01 删除该字段而失效，
  使 24 个检查**全部在 setup 阶段 ERROR**（不是断言失败）；已删除该行，恢复 24/24 可复现。
- `frontend-audit.mjs`：转译并执行仓库实际 TypeScript；仅替换响应式环境、认证与 HTTP/stream 输入；
  2026-09-30 为 5 个检查，2026-10-01 增加 F21 的 5 项后共 10 个检查（F09 ×1、F10 ×3、F11 ×1、F21 ×5）。
- `audit-results.json`、`frontend-results.json`：本轮失败/通过结果，后续执行会覆盖，需比较时使用单独输出名。
- `baseline-results.json`：57 个已有相关回归通过，5 个 worker/mock 服务用例未选入。
- `source-manifest.json`：非干净工作区 HEAD 及审核源文件 SHA-256；不代表生产部署代码。
- `interrupted-run.json`：wrapper 参数问题导致默认测试收集后主动中断的历史记录，不计入审核统计；目标选择已修正。

命令、结果解读和完整覆盖边界见[全面复核](../../../docs/plan/web-storage-chain-audit.md)。
本目录数据为合成值；没有真实模型调用、真实业务库变更或用户运行文件迁移。
临时测试数据运行后删除，检查结果保留。不要以临时文件路径不存在判定结果不可用，复现命令会重建 fixture。

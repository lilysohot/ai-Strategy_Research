# 04 版本存储与抽取编排

Status: ready-for-agent
Execution: completed
Blocked by: 02, 03

以独立源版本、解析版本、证据包版本保存影子结果，提供 service 入口与 CLI。原子落盘、读取校验、按证据取回，重跑不覆盖旧版本；表格确定性抽取与正文模型抽取共用质量验证。

## Comments

2026-09-12：新增独立 corpus_evidence_runs 表及 save/load/fetch API、试验 CLI；内容寻址、原子文件发布、幂等入库、版本并存、CSV 备份恢复均已验证。空模型响应/截断/异常明确失败，预算未执行为 deferred。未做生产迁移。

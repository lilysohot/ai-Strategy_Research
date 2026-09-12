# 02 保真解析与证据包

Status: ready-for-agent
Execution: completed
Blocked by: 01

保留原始文字、页码/章节、bbox、表格行列、单位与列头；无 OCR 输入显式标记。按完整段落/表格行组组织有 hash 的证据包，长输入不得静默丢失尾部。改进 MD/DOCX 标题与表格保留。

## Comments

2026-09-12：实现版本化 EvidenceDocument / EvidencePacket / Cell / Span，PDF 行列 bbox、单位来源、完整文字层保留；MD 原文偏移与标题上下文、DOCX 段落和表格元素定位保留。图片页 unknown。跨页表格/OCR/复杂 DOCX 表格语义仍属 08，不声称任意版式已支持。

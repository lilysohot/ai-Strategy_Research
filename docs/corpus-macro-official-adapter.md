# M2 官方发布适配器

状态：代码与离线回归保留；真实原始 HTML 接入验收按用户决定暂跳过。版本 `bls-archive-1`。
此适配器降为可选来源增强，不再阻塞研报宏观处理；跳过不等于真实验收通过。
本轮仅 M2，不接一致预期、不实现配对计算、不开放生产入口。

## 接口与支持范围

实现位于 `plugins/corpus/macro_official.py`，私有 HTML 解析位于 `_bls_archive.py`。
按 codebase-design 原则，把地址限制、取证、版本判定和拒绝集中在一个适配器内；
复用 M1 模型、审核 authority 及现有 EvidenceRun 身份/引用接口，不复制 claims 规则。

- `OfficialReleaseRequest` 必须指定归档地址、发布日期、目标统计月、版本类型及事先固定的 SHA-256。
- 地址只允许 `https://www.bls.gov/news.release/archives/empsit_MMDDYYYY.htm`，日期须与请求一致。
  latest、其他主机、HTTP、查询参数、fragment、事件日期不匹配在请求校验阶段拒绝。
- `BlsReleaseAdapter.fetch(request)` 发出一次请求，不重试、不跟随重定向、不抓取引用页面。
  最多 2 MB，HTTP 操作超时 20 秒，读取块间检查 30 秒预算；拒绝压缩编码，避免隐式解压放大。
  此预算不是可中断任意宿主代码的 OS 级总超时；注入 client 由可信宿主管理。
- `replay(request, captured_archive)` 对宿主保留的响应重新核对哈希、来源元数据、结构和语义。
- 成功返回不可变事件、vintage、实际值和审核记录，以及保留原文的 EvidenceRun；
  失败返回 BlockedInput，值为 null、带原因和待补字段，不返回部分成功的可计算观测。
- `CapturedArchive.save(directory)` 是显式归档动作：按内容哈希独占创建原始 `.body` 和采集元数据
  `.json` 文件。同内容幂等，已存在但内容不符则拒绝，绝不覆盖旧文件。
  fetch/replay 本身不写文件或数据库；调用方负责保留 result.archive、请求与结果。

HTML 支持范围刻意收窄：明确闭合标签的 UTF-8 官方归档布局、Summary table B 月度变化区，
以及发布正文 pre 内的年度基准 Table A 文本表。不是通用 HTML/宏观表格解析器。
不支持的结构、合并数值列、重复表/行、异常嵌套、字段缺失均拒绝，不降级为 LLM 猜测。

## 版本与数值如何核验

| 情况 | 来源证据与选择规则 | 输出 |
|---|---|---|
| 首发 | 发布标题的完整统计月、Summary B 同月列、p 标记及 Preliminary 定义 | first |
| 常规月度修订 | 完整月份列、当页两次月度修订政策及正常发布节奏；核对 p 标记 | second / third |
| 年度基准修订 | 当期明确的 benchmark 公告、Table A 年份/列头/目标行 | benchmark |
| 历史列但无法证明版本 | 不从“很久以前”或旧 benchmark 页脚推断具体版本 | blocked |
| 延迟或合并发布 | 不满足当前支持的正常月度节奏 | blocked |

Summary B 只取“月度变化、千”的 Total nonfarm 行，不能取三个月平均、私营岗位或就业水平。
基准 Table A 只取 revised 的月度变化列，不取水平、原公布值或修订差额；
基准发布中本期首次公布仍为 first，涉及基准处理的历史月份归为 benchmark。
supersedes_id 未在本次归档内证明时不填，不编造前版本 ID。

原始数值、负号、零和逗号保留；单位保留原语言 `in thousands` / `Numbers in thousands`。
M1 单位转换增加这两个受审核许可控制的标签：必须由 authority 认可当前输入的
indicator + unit_mapping 审核范围，才允许乘 1,000。仅传入相同单位字符串仍会 blocked。
成功标准化后 calculation_permitted 仍为 false。

发布时间取正文 embargo 行，核对日期、星期和 ET/EST/EDT，使用 America/New_York 时区规则，
不是全年固定偏移。发布事件日、完整统计月份、可知时间和实际采集时间分开保存。
不从文件名或抓取时点反推历史可知时间，缺少精确发布时点拒绝。

参考的官方页面：[2025-06-06 发布归档](https://www.bls.gov/news.release/archives/empsit_06062025.htm)、
[含年度基准说明的 2025-02-07 发布归档](https://www.bls.gov/news.release/archives/empsit_02072025.htm)、
[BLS 月度修订说明](https://www.bls.gov/web/empsit/cesnaicsrev.htm)。
这些网页阅读用于确认结构和规则，不是本轮已冻结的原始响应测试集。

## 信任与历史数据保护

1. 初始哈希和 transport/replay 输入由可信宿主管理。把任意文本包装成 BLS 地址、再算一次 hash，
   不会使其成为可信官方归档；本接口不是对恶意宿主的来源认证系统，未暴露为 Agent 工具。
2. 同一适配器内，URL 一旦固定哈希，不能通过更换 expected_sha256 放行内容变化。
   跨进程必须复用宿主保留的固定请求；进程内 pin/审核登记不是持久权限服务。
   官方归档如后来被更正，应单独调查更正时点与新证据，不能把新内容倒填为原公布时点。
3. 原始字节和采集元数据随结果保留；网络/大小/编码拒绝时可能没有完整响应，明确 archive=None，
   不把截断内容保存为完整归档。HTTP 错误的有界完整响应可保留并审计。
4. 证据字符位置对应保留的 UTF-8 HTML 解码文本，可用现有 resolve_reference 回取。
   run 的 source_rev 是原始响应 SHA-256；pipeline/extractor/lint 版本为 bls-archive-1，
   不冒充财务校验版本，不投射为旧财务可计算事实。
5. 审核记录绑定完整输入和规则版本；仅恢复审核 JSON 不恢复信任。
   新进程需用可信归档重新执行适配器。未部署跨进程审核认证或 M4 的决策时点门禁。

## 验证记录（2026-09-13）

- `tests/test_corpus_macro_official.py`：60 项通过，全部是明确标注的合成布局/传输夹具。
- Corpus 全子集：342 项通过；新增/修改模块 Ruff、格式和 Pyright 检查通过。
- import_smoke：335/335、384/384；check_symbols：434 文件、0 missing。
- preflight：一次真实廉价调用通过；judge 配置未设置，未执行模型评审。
- 直接 HTTP 获取指定 BLS 历史页返回 403，未取得用于原始字节/hash/真实 DOM 重放的官方 HTML。
  搜索工具可读页面文本不等于取得了原始响应，不能用它伪装下载或验收成功。
- 未运行全仓库测试；没有真实事件验收成功率或独立留出通过率可报告。

M2 的代码实现与离线验收已交付，整体完成框未勾选。用户后续决定先跳过真实网页验收，不继续重试。
如果以后恢复此适配器，补齐条件为：取得可访问官方归档或具有可信来源记录的原始 HTML、
固定哈希及采集记录，完成真实 fetch/replay、字段人工复核、引用回取和归档不覆盖检查。
当前不要求先完成此检查才能继续研究材料 R1—R3，也不要求用户提供网页。
用户后续指定政府统计与行情由同花顺接口承担；新接口覆盖与权限待 D1 确认，非本适配器继续抓取。
当前任务归 [统一总计划](plan/claims-market-closed-loop-plan.md)，本轮未接入新端点。

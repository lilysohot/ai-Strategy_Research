# 03 · 独立 env 配置、冻结 profile 与模型 Adapter

Status: ready-for-human
Execution: 已验收
Type: task
Plan: W2；R2-S2 的配置子项
Blocked by: 01
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；候选交付及未决项见下方验收记录。

## 目标

实现用户在 .env 中独立配置 M_extract 的路径；三个角色默认引用这一独立配置，不继承 M_main。

## 前置与外部门

01 已冻结配置键与公共契约。执行核查发现 01 及其交付物没有实际列明首轮 provider 白名单；原先“已冻结首轮支持 provider”的前置描述缺少依据。用户于 2026-10-02 确认首轮支持 OpenAI 兼容接口，本票据此固定为 `openai_compat`（Chat Completions），不增加 Anthropic Messages 或 Responses Adapter，不代表已选择具体供应商或模型。可以与 02 做隔离实现/测试，但不因此提前宣布 R2-S2 放行；真实凭据和真实请求均不需要。

## 范围与预期文件

- `.env.example`、`plugins/corpus/structured/config.py` 的专用配置加载/冻结 profile、
  `plugins/corpus/claims.py` 的 build_default_llm 接缝、角色调用 Adapter；工件根目录键固定为
  `CORPUS_STRUCTURED_ROOT`，模型键固定为四个 `STRUCTURED_EXTRACTION_*`。
- 必要时复用 frontier_agent/infra 的配置/provider 能力，不改主线默认参数或全局环境变量。
- tests/test_corpus_structured_config.py，使用假环境、假凭据和录制请求。
- 独立变量为 STRUCTURED_EXTRACTION_PROVIDER、STRUCTURED_EXTRACTION_MODEL、STRUCTURED_EXTRACTION_BASE_URL、STRUCTURED_EXTRACTION_API_KEY。

## 验收条件

- [x] 缺提取必需项时，即便 OPENAI_* 完整也返回未配置，零调用；不阻断确定性任务与已有结果查询。
- [x] 仅从专用变量构造有效模型/端点/认证；不能逐字段回退到主线，也不能只是修改产物 model 标签。
- [x] 三个角色可引用同一 profile；fake 多模型配置可分别命中不同 Adapter，角色与模型是独立维度。
- [x] 调用前冻结非敏感配置指纹和凭据引用；运行中修改主线或全局 env 不漂移已开始任务，换模型新建运行身份。
- [x] 日志、错误和快照均不含密钥或含密钥端点；真实 .env 不修改、不作为测试数据读取。
- [x] SDK/包装器自动重试关闭；能力参数本地适配不算 attempt，实际兼容请求必须走 05 的获准调用入口。
- [x] usage/响应模型不可得时保留未知，不伪造完整模型身份或零成本。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_config.py -q
uv run ruff check plugins/corpus tests/test_corpus_structured_config.py
```

测试断言调用参数与实际 Adapter 请求一致；仅校验 profile 对象不算完成。真实 provider 连通性留给 11。

## 非目标

不选择或购买模型，不填写用户凭据，不更换主线模型，不对未知 provider 增加自动 fallback。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

### 2026-10-02 · 候选实现与本地验证

- `plugins/corpus/structured/config.py`：仅加载四个专用键；显式指定 dotenv 文件、不搜索 cwd、不插值、不改全局环境；缺配置安全返回未配置。冻结模型 profile、凭据内存值和三个角色协议，角色与模型指纹分离；凭据不进入序列化。显式角色覆盖支持 fake 多模型测试。
- `plugins/corpus/structured/adapter.py`：兼容既有 `LlmResponse`/`LlmCallError` 调用面；真正发送冻结的模型、端点及认证，而非仅重标产物。采用直接 HTTP Adapter，隔离 SDK 的主线环境默认值；关闭自动重试、重定向和环境代理继承。调用前必须经过注入的授权入口，默认拒绝发送。
- `.env.example`：新增四个空专用键及 `CORPUS_STRUCTURED_ROOT` 的说明，不填写模型或凭据，不读取或修改真实 `.env`。
- `tests/test_corpus_structured_config.py`：40 项测试，使用假凭据、临时 dotenv 与录制 HTTP transport；阻断真实 socket/默认 HTTP transport。覆盖实际请求身份、缺配置零调用、环境变化不漂移、协议冻结、多模型、授权失败、无重试、异常脱敏、未知 usage/响应模型与现有 Claims/R2 调用面消费。
- 保留旧 `build_default_llm` 和既有业务默认路径不变；新 Adapter 通过显式注入接入，不自动启用新模型调用。05 负责持久预算账和原子 attempt 预留，本票的回调接缝不等于已实现 05。
- 查阅 OpenAI Docs 技能及[官方重试说明](https://developers.openai.com/api/docs/guides/rate-limits)，据此避免 SDK 与应用层重试叠加；同时检查本地 SDK 的环境默认值读取行为，选择直接 HTTP 实现隔离。公开文档读取不是业务模型调用。

验证命令与结果：

```text
uv run pytest tests/test_corpus_structured_config.py tests/test_corpus_structured_contracts.py tests/test_corpus_structured_snapshot.py tests/test_corpus_evidence_pipeline.py tests/test_corpus_material_semantics.py -q --tb=short
  exit 0；150 passed（本票 40 项 + 历史回归 110 项）
uv run ruff check plugins/corpus tests/test_corpus_structured_config.py
  exit 0；All checks passed
uv run pyright plugins/corpus/structured/config.py plugins/corpus/structured/adapter.py
  exit 0；0 errors, 0 warnings
uv run python tools/import_smoke.py --stage 1
  exit 0；375/375 modules
uv run python tools/import_smoke.py --stage 2
  exit 1；422/423 modules；benchmarks.public.harbor_agent 缺少可选依赖 harbor
uv run python tools/check_symbols.py
  exit 0；474 files，0 missing
git diff --check
  exit 0
```

首次候选工件 SHA-256（接口确认后的说明变更见下方补记）：

```text
config.py:  92acadb28cba750c35047720e6a784c524d0ab0b89298cbd1f235dadb54bc955
adapter.py: b5820df395322e75b951f1539e6192840e55f888d8d680c0f4739ffdc90a1a84
tests/test_corpus_structured_config.py:
  37fb9f11baf2df030c8396d089b8ec9883006de5bc271075b1c6c41996536f53
.env.example:
  cbd36032ac8b387b210911dbd2143d6e8438d6fa73f5dd28be40b1edb998df9d
```

当前收口判断：**本地验收通过，已闭环**。依据用户“如果达到验收标准闭环当前任务”的授权，
七项验收条件及首轮 `openai_compat` 范围已复核，最终证据见 Comments 最新记录。
此前 stage 2 缺依赖的记录保留为历史，当前已通过。真实 provider 连通性和 preflight 留给 11；
持久预算账由 05 交付，03 提供必须显式授权且默认拒绝发送的接缝。本票闭环不代表 R2-S2 整体放行。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
- 2026-10-02：用户要求执行下一步，开始 03。01 已验收；本票可与待验收的 02 隔离实现。
  核查发现历史记录未实际列明首轮 provider 白名单，已向用户确认接口范围；先推进 provider
  无关的配置冻结与零网络测试，不将该缺口当作已冻结，不修改真实 `.env`。
- 2026-10-02：候选实现与 150 项测试通过结果已落盘；状态改为 needs-info，等待首轮接口范围确认。未决项与失败门均保留，未提交 commit、未运行真实模型请求。
- 2026-10-02：用户回复“支持openai兼容”，确认首轮 Chat Completions 接口范围；解除 needs-info，转为 ready-for-human / 待验收。仅更新本票与 `.env.example` 的支持范围说明，运行时代码未变，不扩展为真实调用授权或下游放行。
  复跑 `uv run pytest tests/test_corpus_structured_config.py -q`：exit 0，40 passed；`git diff --check`：exit 0。
  `.env.example` 更新后 SHA-256：`9d1e33cfa16f2a5d9946c3615402fab4d696718a9fab623a2c9193a48a6e9627`；其余实现/测试工件指纹未变。
- 2026-10-02：02/03 收口核查发现新增 structured 公共 API 缺少 docstring；已按 `CONTRIBUTING.md` 补齐，公共定义静态扫描缺失数为 0。03 七项验收条件均有专项测试证据，复选框更新为完成；仍保持 `ready-for-human / 待验收`，等待用户最终签认。
  更新后 `config.py` SHA-256：`ef086ee105cc2037986ed49046fb20b8e7a2d8816059c53bfbd37bad139a63b3`；`adapter.py`：`21e94da0360f524ca4214b191b0c828b4fdb4d6c7b3b462344cf71c77b0389d3`；`mapping.py`：`2e2de3d4715d63560e848988637fc876a2662f8812b5187812803a30262507ea`。
- 2026-10-02：按用户条件闭环授权完成最终核查，Execution 更新为已验收。独立配置缺项拒绝、
  实际请求身份、三角色/多模型绑定、运行中冻结、脱敏、零重试/发送前授权及未知 usage 均有
  40 项配置/Adapter 专项覆盖；与 02 及业务回归合计 215 passed。Ruff、格式、Pyright、
  两阶段导入（375/375、424/424）、符号闭包（474 files，0 missing）通过。
  补齐类内公开方法说明后 `config.py` SHA-256 为
  `c83f813670bd635316d1aefab7d90e0919a73732ee6fddd3fc90fc8261304a3b`。
  其他工件与上一修订一致。全仓测试遗留及真实环境边界见 02 最终记录；未读取真实 `.env`，
  不把用户已配置凭据视为已验证连通性。02/03 的本地依赖解除，04 可开始实现。

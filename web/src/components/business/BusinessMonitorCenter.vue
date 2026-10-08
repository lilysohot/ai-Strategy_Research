<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { watchEvents as watchEventsApi, watchRules as watchRulesApi } from '@/api'
import { ApiError } from '@/api/client'
import { useSessionsStore } from '@/stores/sessions'
import type { WatchEvent, WatchRule } from '@/types'

const sessions = useSessionsStore()

const view = ref<'rules' | 'create'>('create')

const rules = ref<WatchRule[]>([])
const events = ref<WatchEvent[]>([])
const loadingRules = ref(false)
const saving = ref(false)
let actionCounter = 0

const form = reactive({
  symbol: '',
  market: '',
  quoteBasis: '',
  currency: 'CNY',
  direction: 'above',
  threshold: '',
  expiresAt: '',
  triggerMode: 'single',
  action: 'notify',
  task: '',
  budget: '',
  alreadyMet: 'wait_next',
})

const readiness = computed(() => {
  const missing: string[] = []
  if (!form.symbol.trim()) missing.push('标的')
  if (!form.market) missing.push('市场')
  if (!form.quoteBasis) missing.push('行情口径')
  if (!form.threshold.trim()) missing.push('阈值')
  if (!form.expiresAt) missing.push('有效期')
  if (form.action === 'auto_analyze' && !form.task.trim()) missing.push('分析任务')
  return missing
})

const canCreate = computed(() =>
  !!sessions.activeId && readiness.value.length === 0,
)

async function loadRules(): Promise<void> {
  loadingRules.value = true
  try {
    const res = await watchRulesApi.list({
      status: undefined,
      limit: 100,
    })
    rules.value = res.rules
    const ev = await watchEventsApi.list({ limit: 20 })
    events.value = ev.events
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '加载监控规则失败')
  } finally {
    loadingRules.value = false
  }
}

/** Map the page form to the DATA-09 spec shape. */
function buildSpec(): Record<string, unknown> {
  const spec: Record<string, unknown> = {
    symbol: form.symbol.trim(),
    market: form.market,
    currency: form.currency,
    quote_basis: form.quoteBasis,
    direction: form.direction === 'below' ? 'down' : 'up',
    threshold: form.threshold.trim(),
    trigger_mode: 'single',
    action: form.action,
    on_create_already_met: form.alreadyMet === 'evaluate_now' ? 'trigger_now' : 'wait_requalify',
  }
  if (form.expiresAt) {
    const d = new Date(form.expiresAt)
    spec.expires_at = d.toISOString()
  }
  if (form.action === 'auto_analyze' && form.task.trim()) spec.task = form.task.trim()
  if (form.budget.trim()) spec.budget = { max_runs: Number(form.budget.trim()) }
  return spec
}

async function createRule(): Promise<void> {
  if (saving.value || !sessions.activeId) return
  if (readiness.value.length) {
    ElMessage.warning(`请先填写：${readiness.value.join('、')}`)
    return
  }
  saving.value = true
  const key = `watch-rule.create:${sessions.activeId}:${form.symbol}:${Date.now()}:${actionCounter++}`
  try {
    await watchRulesApi.create(
      sessions.activeId,
      { name: `${form.symbol} 监控`, spec: buildSpec() },
      key,
    )
    ElMessage.success('监控规则已创建并立即生效')
    form.symbol = ''
    form.threshold = ''
    form.task = ''
    await loadRules()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '创建监控规则失败')
  } finally {
    saving.value = false
  }
}

function ruleTitle(rule: WatchRule): string {
  return rule.name || rule.id.slice(0, 8)
}

function statusLabel(status: string): string {
  return { active: '生效中', paused: '已暂停', cancelled: '已取消' }[status] ?? status
}

async function statusOp(rule: WatchRule, action: 'pause' | 'resume' | 'cancel'): Promise<void> {
  const confirmText = action === 'cancel'
    ? '取消后规则进入终态，不可再恢复。是否继续？'
    : action === 'pause'
      ? '暂停将停止新触发，未启动事件按服务端回执处理。是否继续？'
      : '恢复该规则并继续监听。是否继续？'
  if (!window.confirm(confirmText)) return
  const key = `watch-rule.${action}:${rule.id}:${Date.now()}:${actionCounter++}`
  try {
    await watchRulesApi.statusOp(rule.id, action, rule.current_version, key)
    ElMessage.success('规则状态已更新')
    await loadRules()
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      ElMessage.warning('规则状态已变更，请刷新后重试')
    } else {
      ElMessage.error(err instanceof Error ? err.message : '操作失败')
    }
  }
}

const specOf = (rule: WatchRule): Record<string, unknown> =>
  (rule.spec as Record<string, unknown> | undefined) ?? {}

defineExpose({ loadRules })
onMounted(loadRules)
</script>

<template>
  <div class="monitor-layout">
    <main class="monitor-main">
      <header class="monitor-head">
        <div>
          <p class="eyebrow">后台监控 · UI-08 / 09</p>
          <h2>页面负责说明规则，后台负责持续执行</h2>
          <p>关闭页面不会停止已生效规则；报价时间、接收时间与质量状态分别展示。</p>
        </div>
        <div class="backend-state"><span />后台状态待接入</div>
      </header>

      <nav class="monitor-tabs" aria-label="监控页面">
        <button type="button" :class="{ active: view === 'rules' }" @click="view = 'rules'">规则管理</button>
        <button type="button" :class="{ active: view === 'create' }" @click="view = 'create'">新建规则</button>
      </nav>

      <section v-if="view === 'rules'" class="rule-list">
        <header class="rule-list-head">
          <h3>监控规则</h3>
          <span>{{ rules.length }} 条</span>
        </header>
        <div v-if="loadingRules" class="empty-rules">
          <span class="empty-index">··</span>
          <h3>正在加载监控规则…</h3>
        </div>
        <div v-else-if="rules.length === 0" class="empty-rules">
          <span class="empty-index">00</span>
          <h3>尚无监控规则</h3>
          <p>创建一条单次规则后，后台持续按行情口径监听；关闭页面不影响已生效规则。</p>
          <el-button type="primary" @click="view = 'create'">新建规则</el-button>
        </div>
        <div v-else class="rule-stack">
          <article v-for="rule in rules" :key="rule.id" class="rule-row">
            <div class="rule-main">
              <div class="rule-identity">
                <strong>{{ ruleTitle(rule) }}</strong>
                <span :class="'status status--' + rule.status">{{ statusLabel(rule.status) }}</span>
              </div>
              <div class="rule-spec">
                <span>标的 {{ String(specOf(rule).symbol ?? '—') }}</span>
                <span>{{ String(specOf(rule).direction ?? '') === 'down' ? '低于' : '高于' }} {{ String(specOf(rule).threshold ?? '—') }}</span>
                <span>版本 v{{ rule.current_version }}</span>
              </div>
            </div>
            <div class="rule-actions">
              <template v-if="rule.status === 'active'">
                <el-button size="small" @click="statusOp(rule, 'pause')">暂停</el-button>
                <el-button size="small" type="danger" plain @click="statusOp(rule, 'cancel')">取消</el-button>
              </template>
              <el-button v-else-if="rule.status === 'paused'" size="small" type="primary" @click="statusOp(rule, 'resume')">恢复</el-button>
              <span v-else class="terminal-label">终态，不可操作</span>
            </div>
          </article>
        </div>

        <header class="rule-list-head rule-list-head--events">
          <h3>最近行情事件</h3>
          <span>{{ events.length }} 条</span>
        </header>
        <div v-if="events.length" class="event-stack">
          <div v-for="event in events" :key="event.id" class="event-row">
            <span :class="'status status--' + event.status">{{ statusLabel(event.status) }}</span>
            <span>规则 {{ event.rule_id.slice(0, 8) }}</span>
            <small>{{ event.triggered_at || '待触发' }}</small>
          </div>
        </div>
        <p v-else class="event-empty">暂无行情事件。</p>
      </section>

      <section v-else class="monitor-form">
        <div class="form-chapter">
          <span>01 / 触发条件</span>
          <h3>标的、口径与阈值</h3>
        </div>
        <div class="form-grid">
          <label class="field">
            <span>标的 <em>必填</em></span>
            <el-input v-model="form.symbol" placeholder="代码或标准标识" />
          </label>
          <label class="field">
            <span>市场 <em>必填</em></span>
            <el-select v-model="form.market" placeholder="选择市场">
              <el-option label="中国内地" value="CN" />
              <el-option label="香港" value="HK" />
              <el-option label="美国" value="US" />
            </el-select>
          </label>
          <label class="field">
            <span>行情口径 <em>必填</em></span>
            <el-select v-model="form.quoteBasis" placeholder="不可由页面猜测">
              <el-option label="最新成交" value="last_trade" />
              <el-option label="买一价" value="best_bid" />
              <el-option label="卖一价" value="best_ask" />
            </el-select>
          </label>
          <label class="field">
            <span>币种</span>
            <el-select v-model="form.currency">
              <el-option label="人民币 CNY" value="CNY" />
              <el-option label="美元 USD" value="USD" />
              <el-option label="港币 HKD" value="HKD" />
            </el-select>
          </label>
          <label class="field">
            <span>触发方向</span>
            <el-segmented v-model="form.direction" :options="[{ label: '高于或等于', value: 'above' }, { label: '低于或等于', value: 'below' }]" />
          </label>
          <label class="field">
            <span>阈值 <em>必填</em></span>
            <el-input v-model="form.threshold" inputmode="decimal" placeholder="不提供默认数值">
              <template #append>{{ form.currency }}</template>
            </el-input>
          </label>
          <label class="field field--wide">
            <span>有效期 <em>必填</em></span>
            <el-date-picker v-model="form.expiresAt" type="datetime" placeholder="选择规则失效时间" />
          </label>
        </div>

        <div class="form-chapter form-chapter--spaced">
          <span>02 / 触发动作</span>
          <h3>提醒，还是自动分析</h3>
        </div>
        <div class="choice-grid">
          <button type="button" :class="{ active: form.action === 'notify' }" @click="form.action = 'notify'">
            <strong>仅提醒</strong>
            <small>记录触发并发送站内通知，不创建分析 Run</small>
          </button>
          <button type="button" :class="{ active: form.action === 'auto_analyze' }" @click="form.action = 'auto_analyze'">
            <strong>自动分析</strong>
            <small>明确保存自动执行意图，并受任务和预算约束</small>
          </button>
        </div>
        <div v-if="form.action === 'auto_analyze'" class="form-grid action-fields">
          <label class="field field--wide">
            <span>分析任务 <em>必填</em></span>
            <el-input v-model="form.task" type="textarea" :rows="3" placeholder="说明触发后需要分析什么" />
          </label>
          <label class="field">
            <span>预算上限</span>
            <el-input v-model="form.budget" inputmode="decimal" placeholder="由服务端契约定义单位" />
          </label>
        </div>

        <div class="form-chapter form-chapter--spaced">
          <span>03 / 生命周期</span>
          <h3>触发次数与创建时已达标</h3>
        </div>
        <div class="form-grid">
          <label class="field">
            <span>触发次数模式</span>
            <el-select v-model="form.triggerMode">
              <el-option label="单次触发（C 阶段）" value="single" />
              <el-option label="重复触发（D 阶段，暂不可用）" value="repeat" disabled />
            </el-select>
          </label>
          <label class="field">
            <span>创建时已经满足阈值</span>
            <el-select v-model="form.alreadyMet">
              <el-option label="等待下一次跨越阈值" value="wait_next" />
              <el-option label="创建后立即按当前观测判定" value="evaluate_now" />
            </el-select>
          </label>
        </div>
      </section>
    </main>

    <aside class="monitor-aside">
      <div class="quote-card">
        <span>行情可用性</span>
        <strong>等待 DATA-09 能力探测</strong>
        <dl>
          <div><dt>观测时间</dt><dd>—</dd></div>
          <div><dt>接收时间</dt><dd>—</dd></div>
          <div><dt>质量状态</dt><dd>未连接</dd></div>
          <div><dt>采样频率</dt><dd>由服务端返回</dd></div>
        </dl>
        <p>没有可靠观测时间时，页面不会把“刚收到报价”写成“最新成交”。</p>
      </div>

      <div class="rule-preview">
        <span>规则预检</span>
        <h3>{{ readiness.length ? `${readiness.length} 项尚未填写` : '前端字段已齐' }}</h3>
        <ul v-if="readiness.length">
          <li v-for="item in readiness" :key="item">{{ item }}</li>
        </ul>
        <p v-else>还需要服务端校验标的能力、报价来源、归属、预算与幂等结果。</p>
      </div>

      <div class="lifecycle-note">
        <span>版本边界</span>
        <p>编辑阈值会创建新规则版本；未启动事件按服务端回执处理，既有 Run 的输入不会被改写。</p>
      </div>

      <el-tooltip
        :content="sessions.activeId ? (readiness.length ? '请先填写必填项' : '创建后台监控规则并立即生效') : '请先选择研究会话'"
        placement="top"
      >
        <span class="full-action">
          <el-button type="primary" :disabled="!canCreate" :loading="saving" @click="createRule">创建监控规则</el-button>
        </span>
      </el-tooltip>
    </aside>
  </div>
</template>

<style scoped>
.monitor-layout { display: grid; grid-template-columns: minmax(0, 1fr) 330px; min-height: 100%; }
.monitor-main { min-width: 0; padding: 28px clamp(20px, 3vw, 44px) 52px; overflow: auto; }
.monitor-head { display: flex; justify-content: space-between; gap: 24px; padding-bottom: 24px; border-bottom: 1px solid var(--line); }
.monitor-head h2 { margin: 4px 0 8px; font-family: 'Songti SC', 'Source Han Serif SC', serif; font-size: clamp(24px, 3vw, 34px); line-height: 1.2; }
.monitor-head p:not(.eyebrow) { max-width: 680px; margin: 0; color: var(--muted); }
.eyebrow { margin: 0; color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .12em; }
.backend-state { display: flex; align-self: flex-start; align-items: center; gap: 8px; padding-top: 8px; color: var(--muted); white-space: nowrap; }
.backend-state span { width: 8px; height: 8px; border-radius: 50%; background: var(--quiet); }
.monitor-tabs { display: flex; gap: 0; margin: 26px 0; border-bottom: 1px solid var(--line); }
.monitor-tabs button { padding: 10px 16px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--muted); cursor: pointer; }
.monitor-tabs button.active { border-color: var(--accent); color: var(--text); }
.empty-rules { min-height: 420px; display: grid; place-items: center; align-content: center; text-align: center; }
.empty-rules h3 { margin: 10px 0 5px; font-size: 20px; }
.empty-rules p { max-width: 520px; margin: 0 0 18px; color: var(--muted); }
.empty-index { color: var(--line-strong); font-family: 'Songti SC', serif; font-size: 72px; line-height: 1; }
.form-chapter { display: flex; align-items: baseline; justify-content: space-between; gap: 20px; }
.form-chapter span { color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .1em; }
.form-chapter h3 { margin: 0 0 18px; font-size: 20px; }
.form-chapter--spaced { margin-top: 34px; padding-top: 24px; border-top: 1px solid var(--line); }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 22px; }
.field { display: flex; min-width: 0; flex-direction: column; gap: 7px; color: var(--text-soft); }
.field--wide { grid-column: 1 / -1; }
.field > span { font-size: 13px; font-weight: 600; }
.field em { color: var(--warning); font-style: normal; }
.field :deep(.el-select), .field :deep(.el-date-editor) { width: 100%; }
.choice-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.choice-grid button { display: flex; flex-direction: column; gap: 5px; padding: 16px; border: 1px solid var(--line); border-radius: 5px; background: var(--bg-input); color: var(--text); text-align: left; cursor: pointer; }
.choice-grid button.active { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--bg-input)); }
.choice-grid small { color: var(--muted); }
.action-fields { margin-top: 18px; }
.monitor-aside { padding: 28px 22px; border-left: 1px solid var(--line); background: #141711; overflow: auto; }
.quote-card, .rule-preview, .lifecycle-note { padding: 18px 0; border-bottom: 1px solid var(--line); }
.quote-card:first-child { padding-top: 0; border-top: 2px solid var(--accent); padding-top: 14px; }
.quote-card > span, .rule-preview > span, .lifecycle-note > span { color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .09em; }
.quote-card strong { display: block; margin: 7px 0 10px; }
.quote-card dl { margin: 0; }
.quote-card dl div { display: grid; grid-template-columns: 90px 1fr; gap: 10px; padding: 6px 0; }
.quote-card dt { color: var(--muted); }
.quote-card dd { margin: 0; text-align: right; }
.quote-card p, .rule-preview p, .lifecycle-note p { color: var(--muted); font-size: 12px; }
.rule-preview h3 { margin: 7px 0; }
.rule-preview ul { margin: 8px 0 0; padding-left: 18px; color: var(--text-soft); }
.full-action, .full-action :deep(.el-button) { width: 100%; margin-top: 20px; }
.rule-list { padding-bottom: 20px; }
.rule-list-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 10px; }
.rule-list-head h3 { margin: 0; font-size: 16px; }
.rule-list-head > span { color: var(--muted); font-size: 12px; }
.rule-list-head--events { margin-top: 34px; padding-top: 22px; border-top: 1px solid var(--line); }
.rule-stack { display: flex; flex-direction: column; border-top: 1px solid var(--line); }
.rule-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 0; border-bottom: 1px solid var(--line); }
.rule-main { min-width: 0; }
.rule-identity, .rule-spec { display: flex; align-items: center; gap: 10px; }
.rule-identity strong { font-size: 15px; }
.rule-spec { margin-top: 6px; color: var(--muted); font-size: 12px; flex-wrap: wrap; }
.rule-spec > span { display: inline-flex; }
.rule-actions { flex-shrink: 0; }
.status { padding: 2px 8px; border-radius: 999px; font-size: 11px; border: 1px solid var(--line-strong); white-space: nowrap; }
.status--active { color: #5fd08a; border-color: color-mix(in srgb, #5fd08a 50%, var(--line)); }
.status--paused { color: var(--warning); }
.status--cancelled { color: var(--muted); }
.terminal-label { color: var(--muted); font-size: 12px; }
.event-stack { display: flex; flex-direction: column; }
.event-row { display: flex; align-items: center; gap: 12px; padding: 8px 0; color: var(--text-soft); font-size: 13px; border-bottom: 1px solid var(--line); }
.event-row small, .event-empty { color: var(--muted); }
.event-row :first-child { margin-right: auto; }
@media (max-width: 980px) { .monitor-layout { grid-template-columns: 1fr; } .monitor-aside { border-top: 1px solid var(--line); border-left: 0; } }
@media (max-width: 640px) {
  .monitor-main { padding: 20px 14px 36px; }
  .monitor-head { flex-direction: column; gap: 10px; }
  .form-grid, .choice-grid { grid-template-columns: 1fr; }
  .field--wide { grid-column: auto; }
  .rule-row { flex-direction: column; align-items: flex-start; gap: 10px; }
}
</style>

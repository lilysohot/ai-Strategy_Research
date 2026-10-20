<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { link as researchLink, monitor, watchRules, type MonitorStatus } from '@/api'
import type { ResearchLink, WatchRule } from '@/types'
import {
  activeMonitorRunId,
  autoAnalysisBindingIssue,
  type MonitorBindingState,
} from '@/utils/monitor'
import RunDetailView from '@/views/RunDetailView.vue'

const props = defineProps<{ researchId: string }>()
const emit = defineEmits<{ runsChanged: [researchId: string, activeRunId: string | null] }>()
const opened = ref(false)
const selectedRun = ref<string | null>(null)
const status = ref<MonitorStatus | null>(null)
const error = ref('')
const saving = ref(false)
const editing = ref<string | null>(null)
const showForm = ref(false)
const binding = ref<ResearchLink | null>(null)
const bindingState = ref<MonitorBindingState>('loading')
let timer: ReturnType<typeof setInterval> | null = null
let epoch = 0
let loading = false
let runFingerprint = ''
let operationKey = ''
let operationPayload = ''
const form = reactive({ symbol: '', direction: 'up', threshold: '', upper: '', expires: '', action: 'notify',
  task: '', alreadyMet: 'wait_requalify' })
const current = computed(() => status.value?.rules ?? [])
const autoAnalysisIssue = computed(() =>
  autoAnalysisBindingIssue(binding.value, bindingState.value),
)
const health = computed(() => {
  if (error.value) return error.value
  if (!status.value) return '正在读取监控状态'
  if (!status.value.enabled) return '监控服务未启用'
  if (!status.value.source_verified) return '行情时间待核验，暂不触发'
  if (!status.value.online) return '等待网页在线心跳'
  if (['collector', 'delivery', 'scheduler'].some(role => !status.value?.workers.some(w => w.role === role && w.healthy))) return '监控服务异常，请查看详情'
  return '监控服务正常'
})
const labels: Record<string, string> = {
  active: '监控中', paused: '已暂停', cancelled: '已取消', pending: '等待处理', accepted: '已接收',
  dispatching: '分析已排队或运行中', completed: '已完成', failed: '失败', expired: '已失效',
  needs_input: '需要补充账户或计划', blocked_budget: '预算已用完', merged: '已合并',
  quarantined: '处理失败，已隔离', browser_offline: '网页已离线', browser_reconnected: '网页已恢复，等待新行情',
  unverified_quote_time: '行情时间未经核验', stale_quote: '行情已过期', future_quote: '行情时间异常',
  imprecise_price: '报价精度不足', unsupported_instrument: '当前行情源不支持此标的',
  single_trigger_consumed: '本次监控已触发一次', research_busy: '等待当前研究执行结束',
  worker_capacity: '等待分析执行名额', consumer_quarantined: '行情消费失败，已隔离待处理',
  rule_lifecycle_changed: '规则曾暂停或恢复，旧触发已失效', prior_online_period: '上次在线期间的旧触发已失效',
  awaiting_fresh_quote: '等待下一次有效行情', condition_no_longer_met: '最新价格已不满足条件',
  max_delay: '超过触发有效期', rule_inactive: '规则已暂停或取消', rule_obsoleted: '规则已改版',
  research_binding_missing: '请在会话计划中绑定账户与主计划',
}
const label = (value: unknown) => labels[String(value)] ?? String(value ?? '—')
const time = (value: unknown) => value ? new Date(String(value)).toLocaleString() : '尚无'
function ruleState(rule: WatchRule): string {
  if (rule.status === 'paused') return '已暂停'
  if (rule.armed === false) return '已触发'
  if (!status.value?.enabled) return '等待服务启用'
  if (!status.value?.source_verified) return '行情待核验'
  if (rule.expires_at && new Date(String(rule.expires_at)).getTime() < Date.now()) return '已过期'
  if (!status.value?.online) return '网页离线'
  return rule.last_valid_quote_at ? '监控中' : '等待首轮有效采样'
}
function eventReason(event: Record<string, unknown>): string {
  const result = event.delivery_result as Record<string, unknown> | undefined
  const detail = event.detail as Record<string, unknown> | undefined
  return label(result?.reason ?? result?.error ?? detail?.expire_reason ?? detail?.failure_reason ?? event.status)
}
async function load(): Promise<void> {
  if (loading || !props.researchId) return
  loading = true
  const id = props.researchId
  const requestEpoch = epoch
  if (binding.value?.research_id !== id) {
    binding.value = null
    bindingState.value = 'loading'
  }
  const [monitorResult, bindingResult] = await Promise.allSettled([
    monitor.status(id),
    researchLink.get(id),
  ])
  try {
    if (requestEpoch !== epoch) return
    if (monitorResult.status === 'rejected') throw monitorResult.reason
    const result = monitorResult.value
    status.value = result
    error.value = ''
    const fingerprint = result.events.filter(e => e.run_id).map(e => `${e.run_id}:${e.status}`).join('|')
    if (fingerprint && fingerprint !== runFingerprint) {
      emit('runsChanged', id, activeMonitorRunId(result.events))
    }
    runFingerprint = fingerprint
  } catch (err) {
    if (requestEpoch === epoch) error.value = err instanceof Error ? err.message : '读取监控失败'
  } finally {
    if (requestEpoch === epoch) {
      if (bindingResult.status === 'fulfilled') {
        binding.value = bindingResult.value
        bindingState.value = 'ready'
      } else {
        bindingState.value = 'error'
      }
    }
    loading = false
  }
}

async function refreshBinding(): Promise<void> {
  const id = props.researchId
  const requestEpoch = epoch
  bindingState.value = 'loading'
  try {
    const result = await researchLink.get(id)
    if (requestEpoch !== epoch || id !== props.researchId) return
    binding.value = result
    bindingState.value = 'ready'
  } catch {
    if (requestEpoch === epoch) bindingState.value = 'error'
  }
}
function edit(rule?: WatchRule): void {
  editing.value = rule?.id ?? null
  const threshold = rule?.threshold
  const range = typeof threshold === 'object' && threshold ? threshold as Record<string, unknown> : null
  Object.assign(form, { symbol: String(rule?.symbol ?? ''), direction: String(rule?.direction ?? 'up'),
    threshold: String(range?.low ?? threshold ?? ''), upper: String(range?.high ?? ''),
    expires: rule?.expires_at ? new Date(String(rule.expires_at)) : '',
    action: String(rule?.action ?? 'notify'), task: String(rule?.task ?? ''),
    alreadyMet: String(rule?.on_create_already_met ?? 'wait_requalify') })
  showForm.value = true
  void refreshBinding()
}
async function save(): Promise<void> {
  if (saving.value) return
  if (!/^(?:6\d{5}\.SH|[03]\d{5}\.SZ)$/.test(form.symbol.trim().toUpperCase())) {
    ElMessage.warning('请输入完整 A 股代码，例如 601138.SH'); return
  }
  if (!form.threshold || !form.expires || (form.action === 'auto_analyze' && !form.task.trim())) {
    ElMessage.warning('请填写阈值、有效期和自动分析任务'); return
  }
  const expires = new Date(form.expires)
  if (!Number.isFinite(expires.getTime()) || expires.getTime() <= Date.now()) {
    ElMessage.warning('有效期需要晚于当前时间'); return
  }
  const spec = { symbol: form.symbol.trim().toUpperCase(), market: 'CN', currency: 'CNY', quote_basis: 'last',
    direction: form.direction, threshold: form.direction === 'range' ? { low: form.threshold, high: form.upper } : form.threshold,
    expires_at: expires.toISOString(), action: form.action, task: form.task.trim() || null,
    trigger_mode: 'single', budget: { max_runs: 1 }, on_create_already_met: form.alreadyMet,
    disconnect_recovery: 'wait_requalify' }
  const payload = JSON.stringify([props.researchId, editing.value, spec])
  if (operationPayload !== payload) { operationPayload = payload; operationKey = crypto.randomUUID() }
  saving.value = true
  try {
    if (form.action === 'auto_analyze') {
      await refreshBinding()
      if (autoAnalysisIssue.value) {
        ElMessage.warning(autoAnalysisIssue.value)
        return
      }
    }
    if (editing.value) {
      const rule = current.value.find(r => r.id === editing.value)
      if (!rule) throw new Error('监控已变更，请刷新后重试')
      await watchRules.update(rule.id, spec, rule.version, operationKey)
    } else {
      await watchRules.create(props.researchId, { name: `${spec.symbol} 价格监控`, spec }, operationKey)
    }
    showForm.value = false
    operationPayload = ''
    ElMessage.success('监控配置已保存')
    await load()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '保存失败')
  } finally { saving.value = false }
}
async function change(rule: WatchRule, action: 'pause' | 'resume' | 'cancel'): Promise<void> {
  if (saving.value) return
  if (action === 'cancel') {
    try { await ElMessageBox.confirm('取消后保留历史记录，并释放当前会话的监控名额。', '取消监控', { type: 'warning' }) }
    catch { return }
  }
  saving.value = true
  try {
    await watchRules.statusOp(rule.id, action, rule.version, crypto.randomUUID())
    await load()
  } catch (err) { ElMessage.error(err instanceof Error ? err.message : '操作失败') }
  finally { saving.value = false }
}
watch(() => props.researchId, () => {
  epoch++
  status.value = null
  binding.value = null
  bindingState.value = 'loading'
  opened.value = false
  showForm.value = false
  runFingerprint = ''
  void load()
})
onMounted(() => { void load(); timer = setInterval(() => void load(), 15000) })
onBeforeUnmount(() => { epoch++; if (timer) clearInterval(timer) })
</script>

<template>
  <section class="session-monitor" aria-label="会话价格监控">
    <div class="monitor-summary">
      <div>
        <strong>价格监控</strong>
        <span v-if="current.length"> · {{ current[0]?.symbol }} · {{ ruleState(current[0]!) }}</span>
        <span v-else> · 尚未设置</span>
        <small>{{ health }}</small>
      </div>
      <el-button size="small" @click="opened = true">{{ current.length ? '查看监控' : '设置监控' }}</el-button>
    </div>
    <el-dialog v-model="opened" title="当前会话的价格监控" width="min(720px, 94vw)" append-to-body :close-on-click-modal="false">
      <div class="monitor-content">
        <p>每 {{ Math.round((status?.poll_seconds ?? 900) / 60) }} 分钟采样一次，可能错过两次采样之间的价格变化。关闭所有工作台页面后，约 2 分钟内停止监控；已启动的分析继续运行。</p>
        <el-alert :title="health" :type="health === '监控服务正常' ? 'success' : 'warning'" :closable="false" />
        <div v-for="rule in current" :key="rule.id" class="monitor-rule">
          <h3>{{ rule.name }} <small>{{ ruleState(rule) }} · v{{ rule.version }}</small></h3>
          <p>{{ rule.direction === 'up' ? '上穿' : rule.direction === 'down' ? '下穿' : '进入区间' }} {{ rule.threshold }} CNY · {{ rule.action === 'notify' ? '提醒' : '自动分析一次' }}</p>
          <p>最近检查：{{ time(rule.last_check_at) }}<br>有效行情：{{ rule.last_valid_quote_price ?? '尚无' }} · {{ time(rule.last_valid_quote_at) }}<br>下次采样：{{ time(rule.next_poll_at) }}</p>
          <p v-if="rule.source_error || rule.last_suppressed_reason">状态说明：{{ label(rule.source_error || rule.last_suppressed_reason) }}</p>
          <el-button :disabled="saving" @click="edit(rule)">编辑 / 重新设置</el-button>
          <el-button :disabled="saving" @click="change(rule, rule.status === 'paused' ? 'resume' : 'pause')">{{ rule.status === 'paused' ? '恢复' : '暂停' }}</el-button>
          <el-button :disabled="saving" @click="change(rule, 'cancel')">取消监控</el-button>
        </div>
        <el-button v-if="current.length < (status?.session_limit ?? 1) && !showForm" @click="edit()">添加价格监控</el-button>
        <el-form v-if="showForm" label-position="top" @submit.prevent="save">
          <h3>{{ editing ? '编辑监控（保存后重新获得一次触发资格）' : '新建监控' }}</h3>
          <el-form-item label="A 股代码 · 中国内地 · 最新成交价 · 人民币" required><el-input v-model="form.symbol" placeholder="例如 601138.SH" /></el-form-item>
          <div class="monitor-grid">
            <el-form-item label="触发方向"><el-select v-model="form.direction"><el-option label="上穿价格" value="up"/><el-option label="下穿价格" value="down"/><el-option label="进入区间" value="range"/></el-select></el-form-item>
            <el-form-item :label="form.direction === 'range' ? '区间下限' : '触发价格'" required><el-input v-model="form.threshold" inputmode="decimal" /></el-form-item>
            <el-form-item v-if="form.direction === 'range'" label="区间上限" required><el-input v-model="form.upper" inputmode="decimal" /></el-form-item>
            <el-form-item label="有效期至" required><el-date-picker v-model="form.expires" type="datetime" placeholder="选择日期和时间" /></el-form-item>
          </div>
          <el-form-item label="首次采样已满足条件时"><el-select v-model="form.alreadyMet"><el-option label="等待价格离开条件后再次达到" value="wait_requalify"/><el-option label="立即触发一次" value="trigger_now"/></el-select></el-form-item>
          <el-form-item label="触发后的操作"><el-radio-group v-model="form.action"><el-radio-button value="notify">仅提醒</el-radio-button><el-radio-button value="auto_analyze" :disabled="!!autoAnalysisIssue">在当前会话自动分析</el-radio-button></el-radio-group></el-form-item>
          <el-alert v-if="autoAnalysisIssue" :title="autoAnalysisIssue" type="warning" :closable="false" show-icon />
          <template v-if="form.action === 'auto_analyze'">
            <p>自动分析将使用当前研究绑定的主账户和主计划。每个版本最多发起一次分析；当前研究运行中时等待，新行情仍满足条件才执行。</p>
            <el-form-item label="分析任务" required><el-input v-model="form.task" type="textarea" :rows="3" placeholder="达到目标价时，结合当前账户和计划重新评估买入条件" /></el-form-item>
          </template>
          <el-button native-type="submit" type="primary" :loading="saving" :disabled="form.action === 'auto_analyze' && !!autoAnalysisIssue">保存监控</el-button>
          <el-button :disabled="saving" @click="showForm = false">返回</el-button>
        </el-form>
        <h3>触发记录</h3>
        <p v-if="!status?.events.length">暂无触发记录。</p>
        <article v-for="event in status?.events" :key="event.id" class="monitor-event">
          <strong>{{ event.symbol }} · {{ label(event.status) }}</strong>
          <p>{{ eventReason(event) }}<span v-if="event.delivery_state === 'quarantined'"> · 消费失败，已隔离</span></p>
          <p>触发价 {{ event.price }} · {{ typeof event.received_at_ms === 'number' ? new Date(event.received_at_ms).toLocaleString() : '—' }}</p>
          <el-button v-if="event.run_id" link @click="selectedRun = event.run_id">查看分析 Run {{ event.run_id.slice(0, 8) }}</el-button>
        </article>
        <p v-if="status && status.event_total > 20">显示最近 20 条触发记录。</p>
        <el-button @click="load">刷新状态</el-button>
      </div>
    </el-dialog>
    <el-dialog :model-value="!!selectedRun" title="监控分析记录" width="min(900px, 94vw)" append-to-body @close="selectedRun = null">
      <RunDetailView v-if="selectedRun" :run-id="selectedRun" />
    </el-dialog>
  </section>
</template>

<style scoped>
.session-monitor { margin: 8px 16px; padding: 10px 14px; border: 1px solid var(--el-border-color); border-radius: 8px; }
.monitor-summary { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.monitor-summary small { display: block; margin-top: 4px; color: var(--el-text-color-secondary); }
.monitor-content { max-height: 72vh; overflow-y: auto; padding-right: 8px; }
.monitor-content p { line-height: 1.7; color: var(--el-text-color-secondary); }
.monitor-rule, .monitor-event { border-bottom: 1px solid var(--el-border-color); padding: 12px 0; margin-bottom: 12px; }
.monitor-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.monitor-grid :deep(.el-date-editor) { width: 100%; }
h3 small { font-weight: normal; }
@media (max-width: 600px) { .monitor-grid { grid-template-columns: 1fr; } }
</style>

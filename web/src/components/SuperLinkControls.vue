<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { superLink, type Space, type LinkRun, type Delivery, type ControlCommand, type RecoveryCommand, type RecoveryRecord } from '../api/superLink'
import type { RunControlRecord } from '../types'
import { useAuthStore } from '../stores/auth'
import { linkLabel } from '../utils/superLink'
import SuperLinkApproval from './SuperLinkApproval.vue'

const props = defineProps<{
  space: Space
  runs: LinkRun[]
  deliveries: Delivery[]
  pending?: RunControlRecord[]
  pendingTotal?: number
  activeRunIds?: string[]
  actions?: RecoveryRecord[]
  actionsNext?: string | null
}>()
const emit = defineEmits<{ changed: []; 'more-actions': [] }>()
const fallbackPending = ref<RunControlRecord[]>([])
const recent = ref<RunControlRecord[]>([])
const fallbackActive = ref<LinkRun[]>([])
const fallbackAudit = ref<RecoveryRecord[]>([])
const auditCursor = ref<string | null>(null)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const open = ref(false)
const action = ref<ControlCommand['action'] | RecoveryCommand['action']>('pause')
const reason = ref('')
const message = ref('')
const participant = ref('')
const target = ref('')
const additional = ref(3)
const formVersion = ref(0)
const steerText = ref<Record<string, string>>({})
const recoveryOpen = ref(false)
const readonly = computed(() => props.space.can_control === false)
const stopped = computed(() => ['stopping', 'stopped'].includes(props.space.control_state))
const pendingRecords = computed(() => props.pending ?? fallbackPending.value)
const pendingCount = computed(() => props.pendingTotal ?? pendingRecords.value.length)
const activeRuns = computed<LinkRun[]>(() => {
  if (!props.activeRunIds) return fallbackActive.value
  const known = new Map<string, LinkRun>()
  for (const run of fallbackActive.value) known.set(run.run_id, run)
  for (const run of props.runs) known.set(run.run_id, run)
  return props.activeRunIds
    .map(id => known.get(id))
    .filter((run): run is LinkRun => Boolean(run))
})
const auditRecords = computed(() => props.actions ?? fallbackAudit.value)
const auditMore = computed(() => props.actions ? Boolean(props.actionsNext) : Boolean(auditCursor.value))
const auth = useAuthStore()
const storageKey = `super-link.command:${auth.user?.id}:${props.space.space_id}`
type Saved = { kind: 'control'; body: ControlCommand } | { kind: 'recovery'; body: RecoveryCommand }
const saved = ref<Saved | null>(null)
let alive = true
let refreshSeq = 0
let timer: ReturnType<typeof setTimeout> | undefined
const labels: Record<string, string> = { pause: '暂停协作', stop: '停止协作', resume: '恢复协作', continue: '补充任务', inspection_retry: '重试技术核查', admission_retry: '重试执行受理', feedback_retry: '重试补正派发', finalization_retry: '重试运行收尾', abandon_finalization: '放弃收尾', extend_budget: '增加自动跟进额度' }
const descriptions: Record<string, string> = {
  pause: '暂停新检查和后续派发；已交给运行器的任务继续收尾，排队任务保留。审批中的运行仍需处理。',
  stop: '停止后续派发，取消排队任务，并请求当前运行退出。停止前未执行的交付不再自动执行；研究成果与记录保留。',
  resume: '恢复后续调度。已取消或中断的任务不会重跑；需要继续研究时请单独补充任务。',
  continue: '给选定的 Agent 创建一轮新的人工任务，进入其会话顺序队列，沿用本方研究记忆。',
  inspection_retry: '仅重试技术失败或配置问题，不修改旁路的业务判断。',
  admission_retry: '重新尝试已通过核查的执行受理，仍遵守额度和顺序队列。',
  feedback_retry: '重新尝试将旁路反馈交给原发送方，不强制它得出通过结论。',
  finalization_retry: '只重试保存和交付收尾，不重新运行模型。需要已有真实退出记录。',
  abandon_finalization: '在确认工作进程退出后，将该次收尾标为失败以释放阻塞。未发布成果不会被伪装为成功。',
  extend_budget: '只增加自动跟进额度，仍需通过核查；单次最多增加 100 轮，总额度不超过 1000。',
}
const recoveryActions = ['inspection_retry', 'admission_retry', 'feedback_retry', 'finalization_retry', 'abandon_finalization', 'extend_budget'] as const
const runTarget = computed(() => ['finalization_retry', 'abandon_finalization'].includes(action.value))
const needsTarget = computed(() => recoveryActions.includes(action.value as RecoveryCommand['action']) && action.value !== 'extend_budget')
const stateLabel = computed(() => ({ active: '协作中', paused: '已暂停', stopping: '正在停止', stopped: '已停止' })[props.space.control_state] ?? '协作中')
const peerLabel = (sessionId: string) => props.space.participants?.find(p => p.session_id === sessionId)?.role === 'team' ? 'Team' : 'Single'

// 低频兜底轮询：仅刷新“最近 100 条记录”，并为未提供 pending/activeRunIds 的旧调用方保留兼容数据。
async function refresh() {
  const seq = ++refreshSeq
  clearTimeout(timer)
  try {
    const data = await superLink.interventions(props.space.space_id)
    if (!alive || seq !== refreshSeq) return
    fallbackPending.value = data.pending; recent.value = data.recent; fallbackActive.value = data.active_runs
  } catch (e) { if (alive && seq === refreshSeq) error.value = e instanceof Error ? e.message : '操作状态读取失败' }
  finally { if (alive && seq === refreshSeq) timer = setTimeout(() => void refresh(), 30000) }
}
async function loadAudit(more = false) {
  try {
    const data = await superLink.recoveryActions(props.space.space_id, more ? auditCursor.value ?? undefined : undefined)
    if (!alive) return
    fallbackAudit.value = more ? [...fallbackAudit.value, ...data.items] : data.items
    auditCursor.value = data.next_after
  } catch (e) { if (alive) error.value = e instanceof Error ? e.message : '审计记录读取失败' }
}
function refreshAudit() {
  if (props.actions) emit('changed')
  else void loadAudit()
}
function moreAudit() {
  if (props.actions) emit('more-actions')
  else void loadAudit(true)
}
function begin(value: typeof action.value) {
  action.value = value; reason.value = ''; message.value = ''; target.value = ''
  formVersion.value = props.space.control_version
  participant.value = props.space.participants?.[0]?.participant_id ?? ''
  additional.value = 3; error.value = ''; open.value = true
}
async function send() {
  if (busy.value || readonly.value) return
  if (!saved.value) {
    if (!reason.value.trim() || (needsTarget.value && !target.value)) return
    if (action.value === 'continue' && (!participant.value || !message.value.trim())) return
    const base = { action: action.value, idempotency_key: crypto.randomUUID(), reason: reason.value.trim() }
    saved.value = recoveryActions.includes(action.value as RecoveryCommand['action'])
      ? { kind: 'recovery', body: { ...base, action: action.value as RecoveryCommand['action'], ...(needsTarget.value ? { target_id: target.value } : { additional_runs: additional.value }) } }
      : { kind: 'control', body: { ...base, action: action.value as ControlCommand['action'], expected_version: formVersion.value, ...(action.value === 'continue' ? { participant_id: participant.value, message: message.value.trim() } : {}) } }
    try { sessionStorage.setItem(storageKey, JSON.stringify(saved.value)) } catch { /* Retry identity stays in memory. */ }
  }
  busy.value = true; error.value = ''; notice.value = ''
  const command = saved.value
  try {
    if (command.kind === 'control') await superLink.control(props.space.space_id, command.body)
    else await superLink.recover(props.space.space_id, command.body)
    if (!alive) return
    saved.value = null
    try { sessionStorage.removeItem(storageKey) } catch { /* Optional storage. */ }
    open.value = false; notice.value = `${labels[command.body.action]}请求已记录，请以最新运行状态为准。`
    emit('changed'); void refresh(); if (!props.actions) void loadAudit()
  } catch (e) { if (alive) error.value = e instanceof Error ? e.message : '提交失败，可重试同一请求' }
  finally { if (alive) busy.value = false }
}
function discard() {
  saved.value = null; open.value = false
  try { sessionStorage.removeItem(storageKey) } catch { /* Optional storage. */ }
  emit('changed')
}
async function steer(run: LinkRun) {
  const value = steerText.value[run.run_id]?.trim()
  if (!value || busy.value || readonly.value || stopped.value) return
  busy.value = true; error.value = ''
  try {
    await superLink.steer(props.space.space_id, run.run_id, value)
    if (!alive) return
    steerText.value[run.run_id] = ''; notice.value = '补充指令已发送，是否采纳以运行记录为准。'
    emit('changed')
    void refresh()
  } catch (e) { if (alive) error.value = e instanceof Error ? e.message : '补充指令发送失败' }
  finally { if (alive) busy.value = false }
}
function afterChange() {
  emit('changed')
  void refresh()
}
onMounted(() => {
  try {
    const value = JSON.parse(sessionStorage.getItem(storageKey) ?? 'null')
    if (value?.body?.idempotency_key && ['control', 'recovery'].includes(value.kind)) saved.value = value
  } catch { /* Optional storage. */ }
  void refresh(); if (!props.actions) void loadAudit()
})
onUnmounted(() => { alive = false; refreshSeq++; clearTimeout(timer) })
</script>

<template>
  <section class="sl-controls" aria-label="协作控制面板">
    <header><div><h2>协作控制 · {{ stateLabel }}</h2><p>控制版本 {{ space.control_version ?? 0 }} · 目标版本 {{ space.goal_version }}</p></div>
      <div class="actions">
        <el-button v-if="space.control_state === 'active'" :disabled="readonly || busy || !!saved" @click="begin('pause')">暂停协作</el-button>
        <el-button v-if="['paused', 'stopped'].includes(space.control_state)" :disabled="readonly || busy || !!saved" @click="begin('resume')">恢复协作</el-button>
        <el-button v-if="!stopped" type="danger" :disabled="readonly || busy || !!saved" @click="begin('stop')">停止协作</el-button>
        <el-button :disabled="readonly || busy || !!saved || space.paused" @click="begin('continue')">补充任务</el-button>
        <el-button :disabled="readonly || busy || !!saved" @click="recoveryOpen = !recoveryOpen">故障恢复</el-button>
      </div>
    </header>
    <p v-if="readonly">服务处于只读恢复模式，暂不接受控制操作。</p>
    <p v-if="space.control_state === 'stopping'">正在取消队列并等待工作进程退出与收尾。未确认退出前不会显示为已停止；收尾阻塞可在故障恢复中处理。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="notice" :title="notice" type="info" :closable="false" />
    <div v-if="saved" class="pending-command"><p>有待确认的操作：{{ labels[saved.body.action] }}。可以重试原请求；关闭后请先核对操作记录。</p>
      <el-button :loading="busy" :disabled="readonly" @click="send">重试原请求</el-button><el-button :disabled="busy" @click="discard">关闭待确认请求</el-button>
    </div>
    <div v-if="recoveryOpen" class="actions recovery"><el-button v-for="item in recoveryActions" :key="item" :disabled="readonly || busy || !!saved" @click="begin(item)">{{ labels[item] }}</el-button></div>
    <h3>待处理审批（{{ pendingCount }}）</h3>
    <p v-if="pendingCount > pendingRecords.length" class="muted">另有 {{ pendingCount - pendingRecords.length }} 条尚未显示，请先处理当前审批或稍后刷新。</p>
    <p v-if="!pendingRecords.length">当前没有等待人工决定的操作。审批超时会拒绝，不会自动放行。</p>
    <SuperLinkApproval v-for="record in pendingRecords" :key="record.control_id" :space-id="space.space_id" :record="record" :disabled="readonly || stopped" @changed="afterChange" />
    <details><summary>运行中补充指令（{{ activeRuns.filter(r => r.status === 'running').length }}）</summary>
      <div v-for="run in activeRuns.filter(r => r.status === 'running')" :key="run.run_id" class="steer">
        <label :for="`steer-${run.run_id}`">{{ peerLabel(run.session_id) }} · {{ run.run_id.slice(0, 8) }}</label>
        <el-input :id="`steer-${run.run_id}`" v-model="steerText[run.run_id]" type="textarea" maxlength="16000" placeholder="补充当前运行所需的信息或调整建议" :disabled="readonly || busy || stopped" />
        <el-button :disabled="readonly || busy || stopped || !steerText[run.run_id]?.trim()" @click="steer(run)">发送补充指令</el-button>
      </div>
    </details>
    <details><summary>审批与指令记录（最近 100 条）</summary>
      <article v-for="record in recent" :key="record.control_id" class="record"><strong>{{ record.kind === 'approval' ? '审批' : '指令' }} · {{ linkLabel(record.status) }}</strong><span> · 运行 {{ record.run_id.slice(0, 8) }}</span>
        <p>{{ record.request.tool_name ?? record.request.message }} {{ record.decision ?? '' }}</p><p v-if="record.replacement_command">替代指令：{{ record.replacement_command }}</p><small>{{ record.resolved_at ?? record.created_at }}</small>
      </article>
    </details>
    <details><summary>控制与恢复审计</summary><el-button @click="refreshAudit">刷新操作记录</el-button>
      <article v-for="record in auditRecords" :key="record.id" class="record"><strong>{{ labels[String(record.request.action)] ?? record.request.action }}</strong><p>{{ record.request.reason }}</p><small>{{ record.created_at }} · 操作者 {{ record.actor_id }}</small><pre>{{ JSON.stringify(record.result, null, 2) }}</pre></article>
      <el-button v-if="auditMore" @click="moreAudit">更早的操作</el-button>
    </details>
    <el-dialog v-model="open" :title="labels[action]" width="min(620px, 94vw)" :close-on-click-modal="!busy" :show-close="!busy" :close-on-press-escape="!busy">
      <p>{{ descriptions[action] }}</p>
      <template v-if="!saved">
        <template v-if="action === 'continue'">
          <label>接收方</label><el-select v-model="participant" aria-label="补充任务接收方"><el-option v-for="p in space.participants" :key="p.participant_id" :value="p.participant_id" :label="p.role === 'team' ? 'Team' : 'Single'" /></el-select>
          <label>补充任务内容</label><el-input v-model="message" aria-label="补充任务内容" type="textarea" :rows="5" maxlength="16000" />
        </template>
        <template v-if="needsTarget">
          <label>{{ runTarget ? '目标运行' : '目标交付' }}</label>
          <el-select v-model="target" filterable aria-label="恢复目标">
            <template v-if="runTarget"><el-option v-for="r in runs" :key="r.run_id" :value="r.run_id" :label="`${peerLabel(r.session_id)} · ${r.run_id.slice(0, 8)} · ${linkLabel(r.finalization?.error ?? r.status)}`" /></template>
            <template v-else><el-option v-for="d in deliveries" :key="d.message_id" :value="d.message_id" :label="`${d.message_id.slice(0, 8)} · ${linkLabel(d.phase)}`" /></template>
          </el-select><p class="muted">显示页面已加载的记录。较早目标请先在运行或交付列表加载；服务端会核对恢复条件。</p>
        </template>
        <template v-if="action === 'extend_budget'"><label>增加轮数</label><el-input-number v-model="additional" :min="1" :max="100" :step="1" step-strictly /></template>
        <label>操作原因</label><el-input v-model="reason" aria-label="操作原因" type="textarea" :rows="3" maxlength="2000" />
      </template>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <template #footer><el-button :disabled="busy" @click="open = false">关闭</el-button><el-button type="primary" :loading="busy" :disabled="readonly || (!saved && (!reason.trim() || (needsTarget && !target) || (action === 'continue' && !message.trim())))" @click="send">{{ saved ? '重试原请求' : '确认操作' }}</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.sl-controls{border:1px solid var(--el-border-color);border-radius:12px;padding:24px;background:var(--el-bg-color);margin-top:20px;overflow-wrap:anywhere}.sl-controls header{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}.sl-controls h2{font-size:18px;margin:0}.sl-controls p{font-size:13px;line-height:1.7}.actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.recovery{margin:16px 0}.record{border-top:1px solid var(--el-border-color);padding:12px 0}.record pre{white-space:pre-wrap;font-size:12px}.steer{margin:16px 0}.steer .el-button{margin-top:8px}details{margin-top:18px}summary{cursor:pointer}label{display:block;margin:16px 0 8px}.muted,small{color:var(--el-text-color-secondary)}.pending-command{padding:12px;background:var(--el-fill-color-light)}@media(max-width:700px){.sl-controls{padding:18px}}
</style>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { runs as runsApi } from '../api'
import { superLink, type Space, type LinkRun, type Delivery } from '../api/superLink'
import { linkLabel } from '../utils/superLink'
import { renderMarkdown } from '../utils/markdown'
import RunDetailView from './RunDetailView.vue'
import ArtifactPanel from '../components/ArtifactPanel.vue'
import SuperLinkControls from '../components/SuperLinkControls.vue'
import SuperLinkStudio from '../components/SuperLinkStudio.vue'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const pendingKey = `super-link.pending-create:${auth.user?.id ?? 'anonymous'}`
const spaceId = computed(() => typeof route.params.spaceId === 'string' ? route.params.spaceId : '')
const spaces = ref<Space[]>([])
const current = ref<Space | null>(null)
const runs = ref<LinkRun[]>([])
const deliveries = ref<Delivery[]>([])
const spaceCursor = ref<string | null>(null)
const runCursor = ref<string | null>(null)
const deliveryCursor = ref<string | null>(null)
const loading = ref(false)
const loadingMore = ref(false)
const error = ref('')
const disabled = ref(false)
const canCreate = ref(false)
const createReason = ref('')
const creating = ref(false)
const createOpen = ref(false)
const goal = ref('')
const createError = ref('')
const selected = ref<Delivery | null>(null)
const deliveryOpen = ref(false)
const detailError = ref('')
const selectedRun = ref<string | null>(null)
const runOpen = ref(false)
const answer = ref('')
const runError = ref('')
const updatedAt = ref('')
const browsingHistory = ref(false)
let epoch = 0
let detailEpoch = 0
let runEpoch = 0
let timer: ReturnType<typeof setTimeout> | undefined
let creation: { goal: string; key: string } | null = null
try {
  const saved = JSON.parse(sessionStorage.getItem(pendingKey) ?? 'null')
  if (saved && typeof saved.goal === 'string' && typeof saved.key === 'string') {
    creation = saved; goal.value = saved.goal
  }
} catch { /* Storage may be disabled; in-page retries remain idempotent. */ }
const peers = computed(() => current.value?.participants ?? [])
const message = (e: unknown) => e instanceof ApiError ? e.message : '暂时无法连接，请稍后重试'
const date = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '尚未发布'
const role = (id: string) => peers.value.find(p => p.participant_id === id)?.role === 'team' ? 'Team' : 'Single'
const peerRuns = (session: string) => runs.value.filter(r => r.session_id === session)

async function refresh() {
  const ticket = epoch
  const id = spaceId.value
  clearTimeout(timer)
  browsingHistory.value = false
  loading.value = true
  try {
    if (id) {
      const [s, r, d] = await Promise.all([superLink.space(id), superLink.runs(id), superLink.deliveries(id)])
      if (ticket !== epoch) return
      current.value = s; runs.value = r.items; deliveries.value = d.items
      runCursor.value = r.next_after; deliveryCursor.value = d.next_after
    } else {
      const [cap, list] = await Promise.all([superLink.capabilities(), superLink.spaces()])
      if (ticket !== epoch) return
      canCreate.value = cap.can_create; createReason.value = cap.reason ?? ''
      spaces.value = list.items; spaceCursor.value = list.next_after
    }
    error.value = ''; disabled.value = false
    updatedAt.value = new Date().toLocaleTimeString('zh-CN')
  } catch (e) {
    if (ticket !== epoch) return
    disabled.value = e instanceof ApiError && e.detail === 'super_link_disabled'
    error.value = disabled.value ? 'Super-link 尚未启用。原有研究工作台仍可正常使用。'
      : e instanceof ApiError && e.status === 404 ? '未找到这个协作空间，或你没有访问权限。' : message(e)
    canCreate.value = false
  } finally {
    if (ticket === epoch) {
      loading.value = false
      if (id && !disabled.value) timer = setTimeout(() => { if (!loadingMore.value) void refresh(); else timer = setTimeout(() => void refresh(), 5000) }, 5000)
    }
  }
}

async function more(kind: 'spaces' | 'runs' | 'deliveries') {
  const ticket = epoch
  const id = spaceId.value
  loadingMore.value = true
  browsingHistory.value = true
  clearTimeout(timer)
  try {
    if (kind === 'spaces' && spaceCursor.value) {
      const page = await superLink.spaces(spaceCursor.value)
      if (ticket !== epoch) return
      spaces.value.push(...page.items); spaceCursor.value = page.next_after
    } else if (kind === 'runs' && runCursor.value) {
      const page = await superLink.runs(id, runCursor.value)
      if (ticket !== epoch) return
      runs.value.push(...page.items); runCursor.value = page.next_after
    } else if (kind === 'deliveries' && deliveryCursor.value) {
      const page = await superLink.deliveries(id, deliveryCursor.value)
      if (ticket !== epoch) return
      deliveries.value.push(...page.items); deliveryCursor.value = page.next_after
    }
  } catch (e) { if (ticket === epoch) error.value = message(e) }
  finally { if (ticket === epoch) loadingMore.value = false }
  // Viewing older pages intentionally pauses polling; refresh returns to latest.
}

async function create() {
  if (creating.value || !goal.value.trim() || !canCreate.value) return
  const value = goal.value.trim()
  if (!creation || creation.goal !== value) creation = { goal: value, key: crypto.randomUUID() }
  try { sessionStorage.setItem(pendingKey, JSON.stringify(creation)) } catch { /* Optional persistence. */ }
  creating.value = true; createError.value = ''
  try {
    const result = await superLink.create(value, creation.key)
    try { sessionStorage.removeItem(pendingKey) } catch { /* Optional persistence. */ }
    createOpen.value = false; goal.value = ''; creation = null
    await router.push({ name: 'super-link-detail', params: { spaceId: result.space_id } })
  } catch (e) { createError.value = message(e) }
  finally { creating.value = false }
}

async function inspectDelivery(id: string) {
  const ticket = ++detailEpoch
  const pageEpoch = epoch
  selected.value = null; detailError.value = ''; deliveryOpen.value = true
  try {
    const result = await superLink.delivery(spaceId.value, id)
    if (ticket === detailEpoch && pageEpoch === epoch) selected.value = result
  } catch (e) { if (ticket === detailEpoch && pageEpoch === epoch) detailError.value = message(e) }
}
async function inspectRun(id: string) {
  const ticket = ++runEpoch
  const pageEpoch = epoch
  selectedRun.value = id; answer.value = ''; runError.value = ''; runOpen.value = true
  try {
    const result = await runsApi.get(id)
    if (ticket === runEpoch && pageEpoch === epoch) answer.value = result.final_answer ?? ''
  } catch (e) { if (ticket === runEpoch && pageEpoch === epoch) runError.value = message(e) }
}
watch(spaceId, () => {
  epoch++; clearTimeout(timer); current.value = null; runs.value = []; deliveries.value = []
  error.value = ''; disabled.value = false; loadingMore.value = false
  deliveryOpen.value = false; runOpen.value = false
  void refresh()
}, { immediate: true })
onUnmounted(() => { epoch++; clearTimeout(timer) })
</script>

<template>
  <main class="super-link" data-testid="super-link-page">
    <header class="sl-heading">
      <div><p class="sl-eyebrow">FRONTIER / 协作工作室</p><h1>Super-link<span class="sl-title-dot">.</span></h1>
        <p class="sl-intro">让研究、核查与跟进，坐在一起。</p></div>
      <div class="sl-actions">
        <RouterLink v-if="spaceId" :to="{ name: 'super-link' }">全部协作</RouterLink>
        <el-button :loading="loading" :disabled="loadingMore" @click="refresh">刷新状态</el-button>
        <el-button v-if="!spaceId" type="primary" :disabled="!canCreate || loading" @click="createOpen = true">新建协作</el-button>
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <p v-if="!spaceId && createReason && !error" class="sl-muted">{{ createReason }}</p>

    <template v-if="spaceId && current">
      <section class="sl-goal"><div><span class="sl-eyebrow">当前共同目标</span><h2>{{ current.goal }}</h2></div>
        <div class="sl-budget"><span class="sl-eyebrow">自动跟进</span><p><strong>{{ current.automatic_budget?.used ?? '—' }}</strong><span> / {{ current.automatic_budget?.limit ?? '—' }} 轮</span></p></div>
      </section>
    </template>
    <SuperLinkStudio v-if="!disabled && (!spaceId || current)" :space="current" :runs="runs" :deliveries="deliveries" :stale="!!error" :history="browsingHistory" />

    <template v-if="!spaceId && !disabled">
      <header class="sl-section-heading"><div><span class="sl-eyebrow">YOUR WORKSPACES</span><h2>协作空间</h2></div><span class="sl-muted">{{ spaces.length }} 个已加载</span></header>
      <div v-if="!loading && !error && !spaces.length" class="sl-empty">
        <h2>从一个共同研究目标开始</h2><p>创建后，Team 开展首轮研究，Single 在收到通过检查的执行交付后承接。</p>
      </div>
      <section class="sl-spaces" aria-label="协作列表">
        <RouterLink v-for="s in spaces" :key="s.space_id" class="sl-space" :to="{ name: 'super-link-detail', params: { spaceId: s.space_id } }">
          <div class="sl-space-top"><span class="sl-space-icon" aria-hidden="true">▦</span><span class="sl-pill">{{ s.control_state === 'stopping' ? '正在停止' : s.control_state === 'stopped' ? '已停止' : s.paused ? '已暂停' : '协作空间' }}</span></div>
          <h2>{{ s.goal }}</h2><div class="sl-space-footer"><span class="sl-muted">Team <span class="sl-link-dots">···</span> Single</span><span class="sl-open">进入工作室 ↗</span></div>
        </RouterLink>
      </section>
      <el-button v-if="spaceCursor" :loading="loadingMore" :disabled="loading" @click="more('spaces')">加载更多协作</el-button>
    </template>

    <template v-if="spaceId && current">
      <SuperLinkControls :key="current.space_id" :space="current" :runs="runs" :deliveries="deliveries" @changed="refresh" />
      <p v-if="browsingHistory" class="sl-muted">正在查看较早记录，自动刷新已暂停。点击“刷新状态”返回最新记录。</p>
      <header class="sl-section-heading"><div><span class="sl-eyebrow">SESSION ACTIVITY</span><h2>工作记录</h2></div><span v-if="updatedAt" class="sl-muted">{{ error ? '上次更新' : '状态更新于' }} {{ updatedAt }}</span></header>
      <section class="sl-peers" aria-label="参与方会话">
        <article v-for="peer in peers" :key="peer.participant_id" class="sl-peer">
          <header><div class="sl-peer-title"><span class="sl-peer-marker" :class="{ single: peer.role !== 'team' }" aria-hidden="true" /><h2>{{ peer.role === 'team' ? 'Team' : 'Single' }}</h2></div><span class="sl-muted">{{ peer.role === 'team' ? '研究与策略' : '跟进与监控' }}</span></header>
          <p v-if="!peerRuns(peer.session_id).length" class="sl-muted">尚无运行，等待任务交付。</p>
          <button v-for="r in peerRuns(peer.session_id)" :key="r.run_id" class="sl-run" @click="inspectRun(r.run_id)">
            <span>{{ linkLabel(r.status) }}<small>{{ date(r.created_at) }}</small></span>
            <span v-if="r.finalization?.error" class="sl-issue">{{ linkLabel(r.finalization.error) }}</span><span v-else-if="r.dispatch?.error" class="sl-issue">派发待处理</span><span v-else>查看成果 ↗</span>
          </button>
        </article>
      </section>
      <el-button v-if="runCursor" :loading="loadingMore" :disabled="loading" @click="more('runs')">更早的运行</el-button>
      <section class="sl-deliveries" aria-label="交付链路">
        <header><div><h2>交付链路</h2><p class="sl-muted">旁路检查独立呈现；收到信息不等于已经执行。</p></div><span>{{ deliveries.length }} 份已加载</span></header>
        <p v-if="!deliveries.length" class="sl-empty">尚无正式交付。成果将在来源运行结束并保存后进入链路。</p>
        <button v-for="d in deliveries" :key="d.message_id" class="sl-delivery" @click="inspectDelivery(d.message_id)">
          <span><strong>{{ role(d.sender_id) }} → {{ role(d.recipient_id) }}</strong><small>{{ date(d.published_at) }}{{ d.revises_message_id ? ' · 修订交付' : '' }}</small></span>
          <span class="sl-pill">{{ linkLabel(d.phase) }}</span>
          <span>{{ d.inspection ? `旁路：${linkLabel(d.inspection.verdict)}` : '等待检查' }}</span>
          <span v-if="d.feedback?.run">补正：{{ linkLabel(d.feedback.run.status) }}</span>
        </button>
        <el-button v-if="deliveryCursor" :loading="loadingMore" :disabled="loading" @click="more('deliveries')">更早的交付</el-button>
      </section>
    </template>

    <el-dialog v-model="createOpen" title="新建 Super-link 协作" width="min(600px, 94vw)" :close-on-click-modal="!creating" :close-on-press-escape="!creating" :show-close="!creating">
      <form @submit.prevent="create">
        <label for="sl-goal-input">共同研究目标</label>
        <el-input id="sl-goal-input" v-model="goal" type="textarea" :rows="6" maxlength="16000" :disabled="creating" placeholder="例如：检索最新研报，研究潜在交易对象，并将有证据支持的对象交给 Single 持续跟进。" />
        <p class="sl-muted">建立独立的 Team / Single 会话，使用当前模型配置，由 Team 启动首轮研究。</p>
        <el-alert v-if="createError" :title="createError" type="error" :closable="false" />
        <div class="sl-actions sl-form-actions"><el-button :disabled="creating" @click="createOpen = false">取消</el-button><el-button native-type="submit" type="primary" :loading="creating" :disabled="!goal.trim() || !canCreate">创建并开始研究</el-button></div>
      </form>
    </el-dialog>
    <el-drawer v-model="deliveryOpen" title="正式交付与独立检查" size="min(760px, 100vw)">
      <el-alert v-if="detailError" :title="detailError" type="error" :closable="false" />
      <template v-if="selected">
        <p>{{ role(selected.sender_id) }} → {{ role(selected.recipient_id) }} · {{ linkLabel(selected.phase) }}</p>
        <p class="sl-muted">{{ selected.content?.requests_execution ? '请求接收方执行' : '信息交付，供后续读取' }}</p>
        <div class="sl-prose" v-html="renderMarkdown(selected.content?.body ?? '')" />
        <h3>旁路检查</h3><p class="sl-pre">{{ selected.inspection?.explanation ?? '尚未检查' }}</p>
        <p v-if="selected.feedback?.error" class="sl-issue">反馈跟进：{{ linkLabel(selected.feedback.error) }}</p>
        <p class="sl-muted">目标版本 {{ selected.goal_version }} · 内容摘要 {{ selected.content_sha256 }}</p>
        <ol><li v-for="attempt in selected.attempts" :key="attempt.number"><strong>第 {{ attempt.number }} 次 · {{ linkLabel(attempt.verdict) }}</strong><p class="sl-pre">{{ attempt.explanation }}</p><p>{{ attempt.failure_kind }} · {{ date(attempt.started_at) }}</p><details><summary>核查依据与模型快照</summary><pre class="sl-pre">{{ JSON.stringify({ model: attempt.model_snapshot, basis: attempt.input }, null, 2) }}</pre></details></li></ol>
        <template v-if="selected.revises_message_id"><h3>修订来源</h3><el-button @click="inspectDelivery(selected.revises_message_id!)">查看原交付</el-button></template>
        <template v-if="selected.revisions?.length"><h3>后续修订</h3><el-button v-for="id in selected.revisions" :key="id" @click="inspectDelivery(id)">查看修订</el-button></template>
      </template><p v-else-if="!detailError">正在读取交付…</p>
    </el-drawer>
    <el-drawer v-model="runOpen" title="会话运行详情" size="min(900px, 100vw)" destroy-on-close>
      <el-alert v-if="runError" :title="runError" type="error" :closable="false" />
      <h3>本轮成果</h3><div v-if="answer" class="sl-prose" v-html="renderMarkdown(answer)" /><p v-else class="sl-muted">尚无最终成果，可查看运行记录。</p>
      <el-button v-if="selectedRun" @click="inspectRun(selectedRun!)">刷新成果</el-button>
      <details><summary>运行模型与收尾状态</summary><pre class="sl-pre">{{ JSON.stringify(runs.find(r => r.run_id === selectedRun), null, 2) }}</pre></details>
      <ArtifactPanel :run-id="selectedRun" />
      <RunDetailView :run-id="selectedRun" :active="runOpen" />
    </el-drawer>
  </main>
</template>

<style scoped>
.super-link{max-width:1180px;margin:0 auto;padding:28px 24px 64px;color:var(--text)}
.sl-heading,.sl-actions,.sl-peer header,.sl-deliveries>header{display:flex;align-items:center;justify-content:space-between;gap:16px}
.sl-heading{align-items:center;margin-bottom:28px}.sl-heading h1{font-size:42px;font-weight:600;margin:12px 0 8px;letter-spacing:-2px}.sl-title-dot{color:var(--accent)}.sl-intro{font-size:14px;color:var(--muted);margin:0;line-height:1.8}
.sl-eyebrow{font-size:10px;letter-spacing:1.5px;color:var(--muted);margin:0;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.sl-muted{font-size:12px;color:var(--el-text-color-secondary);line-height:1.7}
.sl-actions{flex-wrap:wrap}.sl-actions a{color:var(--el-color-primary);white-space:nowrap}.sl-spaces,.sl-peers{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;margin:24px 0}
.sl-space,.sl-peer,.sl-goal,.sl-deliveries{border:1px solid var(--el-border-color);border-radius:10px;padding:24px;background:var(--el-bg-color)}
.sl-section-heading{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-top:32px}.sl-section-heading h2{font-size:20px;font-weight:500;margin:7px 0 0}.sl-space-top,.sl-space-footer{display:flex;align-items:center;justify-content:space-between;gap:12px}.sl-space-icon{font-size:23px;color:var(--accent)}.sl-space-footer{border-top:1px solid var(--el-border-color-lighter);padding-top:16px;margin-top:20px}.sl-link-dots{letter-spacing:3px;margin:0 8px;color:var(--quiet)}
.sl-goal{display:flex;justify-content:space-between;align-items:center;gap:32px;background:transparent;border-width:1px 0;border-radius:0;padding:20px 0}.sl-goal>div:first-child{min-width:0}.sl-goal h2{margin:8px 0 0;font-weight:500}.sl-budget{flex-shrink:0;border-left:1px solid var(--line);padding-left:32px}.sl-budget p{margin:8px 0 0;font-size:12px;color:var(--muted)}.sl-budget strong{font-size:27px;font-weight:500;color:var(--text)}.sl-peer-title{display:flex;align-items:center;gap:10px}.sl-peer-marker{width:9px;height:9px;background:#8eab78;box-shadow:3px 3px 0 var(--line)}.sl-peer-marker.single{background:#6d9dae}
.sl-space{display:block;text-decoration:none;color:inherit;transition:border-color .15s}.sl-space:hover{border-color:var(--el-color-primary)}
.sl-space h2,.sl-goal h2{font-size:17px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere}.sl-space h2{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;font-weight:500}
.sl-open{color:var(--el-color-primary);font-size:12px;white-space:nowrap}.sl-peer h2,.sl-deliveries h2{font-size:17px;margin:0;font-weight:500}
.sl-peer{min-width:0}.sl-peer header{margin-bottom:16px}.sl-run,.sl-delivery{width:100%;border:0;border-top:1px solid var(--el-border-color-lighter);background:transparent;color:inherit;text-align:left;cursor:pointer;padding:16px 0;display:flex;justify-content:space-between;gap:12px;align-items:center;font:inherit;font-size:13px}
.sl-run:hover,.sl-delivery:hover{color:var(--el-color-primary)}small{display:block;color:var(--el-text-color-secondary);font-size:12px;margin-top:5px}
.sl-pill{display:inline-block;font-size:12px;padding:4px 9px;border-radius:6px;background:var(--el-fill-color-light);color:var(--el-text-color-regular)}
.sl-deliveries{margin-top:24px}.sl-issue{color:var(--el-color-warning)}.sl-empty{text-align:center;padding:40px 12px;color:var(--el-text-color-secondary);line-height:1.8}.sl-empty h2{font-size:20px;color:var(--text)}
.sl-form-actions{justify-content:flex-end;margin-top:20px}label{display:block;margin-bottom:12px}.sl-pre{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7}.sl-prose{overflow-wrap:anywhere;line-height:1.8}.sl-prose :deep(pre){overflow-x:auto;max-width:100%}.sl-prose :deep(img){max-width:100%}
button:focus-visible,a:focus-visible{outline:2px solid var(--el-color-primary);outline-offset:3px}
@media(max-width:700px){.super-link{padding:16px 4px 40px}.sl-heading{flex-direction:column;align-items:flex-start;gap:20px}.sl-spaces,.sl-peers{grid-template-columns:1fr;gap:12px}.sl-space,.sl-peer,.sl-deliveries{padding:18px}.sl-delivery{flex-wrap:wrap}.sl-heading h1{font-size:36px}.sl-actions{gap:8px}.sl-actions :deep(.el-button+.el-button){margin-left:0}.sl-goal{gap:16px;align-items:flex-start}.sl-budget{padding-left:16px}.sl-budget strong{font-size:23px}.sl-goal h2{font-size:15px}.sl-section-heading{align-items:start}.sl-section-heading>.sl-muted{max-width:120px;text-align:right}.sl-deliveries>header{align-items:start}.sl-deliveries>header>span{white-space:nowrap;font-size:11px}}
</style>

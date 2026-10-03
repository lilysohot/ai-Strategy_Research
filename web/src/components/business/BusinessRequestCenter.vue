<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { inputRequests as inputRequestsApi } from '@/api'
import { ApiError } from '@/api/client'
import { useSessionsStore } from '@/stores/sessions'
import type { InputRequest, InputRequestStatus } from '@/types'

const emit = defineEmits<{ navigate: [area: 'research'] }>()
const props = defineProps<{ targetRequestId?: string | null }>()
const sessions = useSessionsStore()
const filter = ref<'all' | InputRequestStatus>('all')
const requests = ref<InputRequest[]>([])
const selectedId = ref<string | null>(null)
const selectedDetail = ref<InputRequest | null>(null)
const answer = ref('')
const values = reactive<Record<string, string>>({})
const uncertain = reactive<Record<string, boolean>>({})
const loading = ref(false)
const detailLoading = ref(false)
const submitting = ref(false)
const acknowledgeCurrent = ref(false)
const actionKeys = new Map<string, string>()
let detailGeneration = 0

const visibleRequests = computed(() => filter.value === 'all'
  ? requests.value
  : requests.value.filter((item) => item.status === filter.value))
const selected = computed(() => selectedDetail.value?.id === selectedId.value
  ? selectedDetail.value
  : requests.value.find((item) => item.id === selectedId.value)
    ?? null)
const selectedForSubmit = computed(() => selectedDetail.value?.id === selectedId.value
  ? selectedDetail.value
  : null)
const remainingFields = computed(() => {
  const item = selected.value
  if (!item) return []
  return item.remaining_fields
    ?? item.fields.map((field) => field.name).filter((name) => !hasCollectedValue(item, name))
})
const changedVersions = computed(() => {
  const item = selected.value
  if (!item) return []
  return Object.entries(item.current_versions ?? {}).filter(
    ([group, revision]) => item.known_versions[group] !== revision,
  )
})

function sessionTitle(id: string): string {
  return sessions.list.find((session) => session.id === id)?.title || '未命名研究'
}

function statusLabel(status: InputRequestStatus): string {
  return { pending: '待补充', answered: '已回答', cancelled: '已取消', expired: '已过期' }[status]
}

function useCaseLabel(useCase: string): string {
  return { plan_analysis: '计划分析', holding_cost: '持仓成本', general_reading: '资料阅读' }[useCase]
    ?? useCase
}

function resetDraft(): void {
  answer.value = ''
  acknowledgeCurrent.value = false
  for (const key of Object.keys(values)) delete values[key]
  for (const key of Object.keys(uncertain)) delete uncertain[key]
}

function collectedValue(item: InputRequest, qualifiedName: string): unknown {
  const [group, name] = qualifiedName.split('.', 2)
  return group && name ? item.collected[group]?.[name] : undefined
}

function hasCollectedValue(item: InputRequest, qualifiedName: string): boolean {
  return collectedValue(item, qualifiedName) !== undefined
}

function displayValue(raw: unknown): string {
  if (raw && typeof raw === 'object' && 'value' in raw) {
    return String((raw as { value?: unknown }).value ?? '')
  }
  return raw == null ? '' : String(raw)
}

function hydrateCollected(item: InputRequest): void {
  for (const field of item.fields) {
    const raw = collectedValue(item, field.name)
    if (raw !== undefined) values[field.name] = displayValue(raw)
  }
}

async function loadRequests(): Promise<void> {
  loading.value = true
  try {
    const all: InputRequest[] = []
    let offset = 0
    for (;;) {
      const response = await inputRequestsApi.list({ limit: 100, offset })
      all.push(...response.requests)
      if (!response.has_more || response.requests.length === 0) break
      offset += response.requests.length
    }
    requests.value = all
    if (props.targetRequestId && requests.value.some((item) => item.id === props.targetRequestId)) {
      selectedId.value = props.targetRequestId
    }
    if (!selectedId.value || !requests.value.some((item) => item.id === selectedId.value)) {
      selectedId.value = requests.value[0]?.id ?? null
    }
    if (selectedId.value) await loadDetail(selectedId.value)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载补数请求失败')
  } finally {
    loading.value = false
  }
}

async function loadDetail(id: string): Promise<void> {
  const generation = ++detailGeneration
  selectedId.value = id
  selectedDetail.value = null
  resetDraft()
  detailLoading.value = true
  try {
    const detail = await inputRequestsApi.get(id)
    if (generation !== detailGeneration || selectedId.value !== id) return
    selectedDetail.value = detail
    hydrateCollected(detail)
  } catch (error) {
    if (generation !== detailGeneration || selectedId.value !== id) return
    ElMessage.error(error instanceof Error ? error.message : '加载请求详情失败')
  } finally {
    if (generation === detailGeneration) detailLoading.value = false
  }
}

function buildDeclared(item: InputRequest): Record<string, Record<string, unknown>> {
  const declared: Record<string, Record<string, unknown>> = {}
  for (const field of item.fields) {
    const [group, name] = field.name.split('.', 2)
    if (!group || !name) continue
    const value = values[field.name]?.trim() ?? ''
    if (!value && !uncertain[field.name]) continue
    declared[group] ??= {}
    declared[group][name] = uncertain[field.name]
      ? { value, status: 'pending_clarification' }
      : value
  }
  return declared
}

function actionKey(id: string, action: string): string {
  const identity = `${action}:${id}`
  const existing = actionKeys.get(identity)
  if (existing) return existing
  const key = crypto.randomUUID()
  actionKeys.set(identity, key)
  return key
}

async function submitAnswer(): Promise<void> {
  const item = selectedForSubmit.value
  if (!item || item.status !== 'pending' || submitting.value || detailLoading.value) return
  const declared = buildDeclared(item)
  if (!answer.value.trim() && !Object.keys(declared).length) {
    ElMessage.warning('请填写回答或待补字段')
    return
  }
  if (changedVersions.value.length && !acknowledgeCurrent.value) {
    ElMessage.warning('资料版本已经变化，请先确认沿用当前版本')
    return
  }
  submitting.value = true
  const identity = `answer:${item.id}`
  try {
    const result = await inputRequestsApi.answer(item.id, {
      answer: answer.value.trim(),
      declared,
      expected_versions: acknowledgeCurrent.value
        ? item.current_versions
        : item.known_versions,
    }, actionKey(item.id, 'answer'))
    actionKeys.delete(identity)
    if (result.status === 'answered') ElMessage.success('资料已保存，后续分析已进入队列')
    else ElMessage.info('回答已记录，仍有资料需要补充')
    await loadRequests()
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      ElMessage.warning('资料或请求状态已经变化，请刷新后再提交')
      await loadRequests()
    } else {
      ElMessage.error(error instanceof Error ? error.message : '提交回答失败')
    }
  } finally {
    submitting.value = false
  }
}

async function cancelRequest(): Promise<void> {
  const item = selected.value
  if (!item || item.status !== 'pending' || submitting.value) return
  try {
    await ElMessageBox.confirm('取消后不能再回答这条补数请求。', '取消补数请求', {
      type: 'warning', confirmButtonText: '确认取消', cancelButtonText: '保留请求',
    })
  } catch {
    return
  }
  submitting.value = true
  const identity = `cancel:${item.id}`
  try {
    await inputRequestsApi.cancel(item.id, actionKey(item.id, 'cancel'))
    actionKeys.delete(identity)
    ElMessage.success('补数请求已取消')
    await loadRequests()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '取消失败')
  } finally {
    submitting.value = false
  }
}

async function openFollowUp(): Promise<void> {
  const item = selected.value
  if (!item) return
  await sessions.select(item.research_id)
  emit('navigate', 'research')
}

watch(filter, () => {
  const first = visibleRequests.value[0]
  if (first && !visibleRequests.value.some((item) => item.id === selectedId.value)) {
    void loadDetail(first.id)
  }
})
watch(() => props.targetRequestId, (id) => {
  if (id && id !== selectedId.value) void loadDetail(id)
})
onMounted(loadRequests)
</script>

<template>
  <div class="request-layout" v-loading="loading">
    <main class="request-main">
      <header class="request-head">
        <div>
          <p class="eyebrow">持久补数 · DATA-07 / UI-07</p>
          <h2>补齐事实，再继续分析</h2>
          <p>请求和回答保存在服务端；刷新或重启后仍可恢复。每条请求只属于一个研究。</p>
        </div>
        <el-segmented v-model="filter" :options="[
          { label: '全部', value: 'all' }, { label: '待补充', value: 'pending' },
          { label: '已回答', value: 'answered' }, { label: '已取消', value: 'cancelled' },
          { label: '已过期', value: 'expired' },
        ]" />
      </header>

      <div class="request-list" role="list">
        <button v-for="(item, index) in visibleRequests" :key="item.id" type="button"
          class="request-row" :class="{ active: item.id === selectedId }" @click="loadDetail(item.id)">
          <span class="request-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="request-copy">
            <strong>{{ item.fields.map((field) => field.name).join('、') }}</strong>
            <small>{{ sessionTitle(item.research_id) }} · {{ useCaseLabel(item.use_case) }}</small>
          </span>
          <span class="status-label" :data-status="item.status">{{ statusLabel(item.status) }}</span>
        </button>
        <el-empty v-if="!visibleRequests.length" description="该状态下没有请求" :image-size="72" />
      </div>
    </main>

    <aside v-if="selected" class="request-detail" aria-label="补数请求详情" v-loading="detailLoading">
      <div class="detail-topline">
        <span>{{ selected.source_run_id ? '来源运行' : '事件预检查' }}</span>
        <span class="status-label" :data-status="selected.status">{{ statusLabel(selected.status) }}</span>
      </div>
      <h3>{{ useCaseLabel(selected.use_case) }}</h3>
      <dl class="detail-facts">
        <div><dt>所属研究</dt><dd>{{ sessionTitle(selected.research_id) }}</dd></div>
        <div><dt>来源 Run</dt><dd>{{ selected.source_run_id || '尚未创建 Run' }}</dd></div>
        <div><dt>到期时间</dt><dd>{{ selected.expires_at || '未设置' }}</dd></div>
        <div><dt>请求版本</dt><dd>{{ selected.revision }}</dd></div>
      </dl>

      <template v-if="selected.status === 'pending'">
        <section v-if="changedVersions.length" class="version-warning">
          <strong>资料已在其他窗口更新</strong>
          <p v-for="([group, revision]) in changedVersions" :key="group">
            {{ group }}：请求时 v{{ selected.known_versions[group] }}，当前 v{{ revision }}
          </p>
          <el-checkbox v-model="acknowledgeCurrent">我已核对，并沿用当前版本继续</el-checkbox>
        </section>
        <section class="field-stack">
          <label v-for="field in selected.fields" :key="field.name" class="answer-field">
            <span>
              {{ field.name }} <small>{{ field.unit || field.currency || '' }}</small>
              <em v-if="hasCollectedValue(selected, field.name)" class="saved-field">已保存</em>
              <em v-else class="remaining-field">待补充</em>
            </span>
            <el-input v-model="values[field.name]" :disabled="uncertain[field.name]"
              :placeholder="field.known_value == null ? '填写明确值' : `已知：${field.known_value}`" />
            <small>{{ field.reason }}</small>
            <el-checkbox v-model="uncertain[field.name]">仍不确定，先记录回答</el-checkbox>
          </label>
        </section>
        <section v-if="selected.answers?.length" class="answer-history pending-history">
          <span>已提交回答</span>
          <article v-for="item in selected.answers" :key="item.revision">
            <strong>{{ item.outcome === 'answered' ? '已采用' : '仍待澄清' }}</strong>
            <p>{{ item.answer || '结构化字段回答' }}</p>
          </article>
          <small>剩余待补：{{ remainingFields.join('、') || '无' }}</small>
        </section>
        <label class="answer-field">
          <span>补充说明</span>
          <el-input v-model="answer" type="textarea" :rows="3" placeholder="说明事实来源或仍有歧义的地方" />
        </label>
        <div class="dialog-actions">
          <el-button :disabled="submitting" @click="cancelRequest">取消请求</el-button>
          <el-button type="primary" :loading="submitting" :disabled="detailLoading" @click="submitAnswer">提交回答</el-button>
        </div>
        <p class="integration-note">明确且完整的回答会保存业务版本并创建新的后续 Run；原快照保持不变。</p>
      </template>

      <template v-else>
        <section class="answer-history">
          <span>回答记录</span>
          <article v-for="item in selected.answers" :key="item.revision">
            <strong>{{ item.outcome === 'answered' ? '已采用' : '仍待澄清' }}</strong>
            <p>{{ item.answer || '结构化字段回答' }}</p>
          </article>
          <p v-if="!selected.answers?.length">没有回答记录。</p>
        </section>
        <el-button v-if="selected.follow_up_run_id" type="primary" @click="openFollowUp">
          返回研究查看后续 Run
        </el-button>
      </template>
    </aside>
  </div>
</template>

<style scoped>
.request-layout { display: grid; grid-template-columns: minmax(0, 1fr) 390px; min-height: 100%; }
.request-main { min-width: 0; padding: 28px clamp(20px, 3vw, 44px) 50px; overflow: auto; }
.request-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; padding-bottom: 24px; border-bottom: 1px solid var(--line); }
.request-head h2 { margin: 4px 0 8px; font-family: 'Songti SC', 'Source Han Serif SC', serif; font-size: clamp(24px, 3vw, 34px); }
.request-head p:not(.eyebrow) { max-width: 680px; margin: 0; color: var(--muted); }
.eyebrow { margin: 0; color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .12em; }
.request-list { display: flex; flex-direction: column; margin-top: 22px; border-top: 1px solid var(--line); }
.request-row { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 12px; align-items: center; width: 100%; padding: 15px 12px; border: 0; border-bottom: 1px solid var(--line); background: transparent; color: inherit; text-align: left; cursor: pointer; }
.request-row:hover, .request-row.active { background: color-mix(in srgb, var(--accent) 7%, transparent); }
.request-index { color: var(--quiet); font-family: monospace; font-size: 11px; }
.request-copy { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.request-copy strong, .request-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.request-copy small { color: var(--muted); }
.status-label { padding: 3px 8px; border: 1px solid var(--line); border-radius: 999px; color: var(--muted); font-size: 11px; }
.status-label[data-status='pending'] { border-color: var(--warning); color: var(--warning); }
.status-label[data-status='answered'] { border-color: var(--success); color: var(--success); }
.request-detail { padding: 26px 24px; border-left: 1px solid var(--line); background: var(--bg-input); overflow: auto; }
.detail-topline { display: flex; justify-content: space-between; color: var(--muted); font-size: 11px; }
.request-detail h3 { margin: 20px 0; font-size: 22px; }
.detail-facts { display: grid; gap: 10px; margin-bottom: 24px; }
.detail-facts div { display: grid; grid-template-columns: 82px minmax(0, 1fr); gap: 8px; }
.detail-facts dt { color: var(--muted); }
.detail-facts dd { margin: 0; overflow-wrap: anywhere; }
.field-stack { display: grid; gap: 14px; }
.answer-field { display: flex; flex-direction: column; gap: 7px; margin-bottom: 16px; }
.answer-field > span { font-weight: 700; }
.answer-field small { color: var(--muted); font-weight: 400; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
.integration-note { color: var(--muted); font-size: 12px; line-height: 1.6; }
.version-warning { margin-bottom: 18px; padding: 12px 14px; border: 1px solid var(--warning); background: color-mix(in srgb, var(--warning) 8%, transparent); }
.version-warning p { margin: 6px 0; color: var(--muted); font-size: 12px; }
.answer-history { display: grid; gap: 10px; margin-bottom: 18px; padding: 14px; border: 1px solid var(--line); }
.answer-history article { padding-top: 10px; border-top: 1px solid var(--line); }
.answer-history p { margin: 4px 0 0; color: var(--muted); }
.pending-history { margin-top: 4px; }
.saved-field, .remaining-field { margin-left: 8px; padding: 2px 6px; border: 1px solid var(--line); border-radius: 999px; font-size: 10px; font-style: normal; font-weight: 500; }
.saved-field { border-color: var(--success); color: var(--success); }
.remaining-field { border-color: var(--warning); color: var(--warning); }
@media (max-width: 900px) {
  .request-layout { grid-template-columns: 1fr; }
  .request-detail { border-top: 1px solid var(--line); border-left: 0; }
}
@media (max-width: 640px) {
  .request-main { padding: 18px 12px 30px; }
  .request-head { align-items: stretch; flex-direction: column; }
  .request-head :deep(.el-segmented) { overflow-x: auto; }
  .request-detail { padding: 20px 14px; }
}
</style>

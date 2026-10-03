<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, watch } from 'vue'

import type { SessionPlanInput, SessionPlanPreview } from '@/business-ui'

const props = defineProps<{
  modelValue: boolean
  sessionId: string | null
  sessionTitle: string
  plans: readonly SessionPlanPreview[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: [plan: SessionPlanInput]
  dirtyChange: [dirty: boolean]
}>()

const draft = reactive<SessionPlanInput>({
  name: '',
  symbol: '',
  market: 'CN',
  direction: 'buy',
  planPrice: '',
  targetPrice: '',
  isPrimary: false,
})

const currentPlans = computed(() => props.plans.filter((plan) => plan.sessionId === props.sessionId))
const canSave = computed(() => !!props.sessionId && !!draft.name.trim() && !!draft.symbol.trim())

watch(() => props.sessionId, () => resetDraft(), { flush: 'sync' })
watch(() => props.modelValue, (open) => {
  if (!open) resetDraft()
  else draft.isPrimary = currentPlans.value.length === 0
})
watch(draft, () => emit('dirtyChange', isDirty()), { deep: true, flush: 'sync' })
function beforeUnload(event: BeforeUnloadEvent): void {
  if (!isDirty()) return
  event.preventDefault()
  event.returnValue = ''
}
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnload)
  emit('dirtyChange', false)
})

function isDirty(): boolean {
  return !!(draft.name || draft.symbol || draft.planPrice || draft.targetPrice
    || draft.market !== 'CN' || draft.direction !== 'buy')
}

function resetDraft(): void {
  Object.assign(draft, {
    name: '',
    symbol: '',
    market: 'CN',
    direction: 'buy',
    planPrice: '',
    targetPrice: '',
    isPrimary: currentPlans.value.length === 0,
  } satisfies SessionPlanInput)
}

function discardDraft(): boolean {
  if (isDirty() && !window.confirm('计划尚未保存，关闭将丢弃草稿。是否继续？')) return false
  resetDraft()
  return true
}

function beforeClose(done: () => void): void {
  if (discardDraft()) done()
}

function close(): void {
  if (!discardDraft()) return
  emit('update:modelValue', false)
}

function save(): void {
  if (!canSave.value) return
  emit('save', {
    ...draft,
    name: draft.name.trim(),
    symbol: draft.symbol.trim().toUpperCase(),
    planPrice: draft.planPrice.trim(),
    targetPrice: draft.targetPrice.trim(),
  })
  resetDraft()
}

function marketLabel(market: SessionPlanPreview['market']): string {
  return { CN: '中国内地', HK: '香港', US: '美国' }[market]
}
defineExpose({ resetDraft })
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    width="min(720px, calc(100vw - 28px))"
    class="session-plan-dialog"
    :close-on-click-modal="false"
    :before-close="beforeClose"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="dialog-heading">
        <span>会话计划</span>
        <h2>{{ sessionTitle }}</h2>
        <p>在这里创建的计划自动归属当前会话，不可再关联其他会话。</p>
      </div>
    </template>

    <section class="current-plans" aria-labelledby="current-session-plan-title">
      <header>
        <h3 id="current-session-plan-title">本会话计划</h3>
        <span>{{ currentPlans.length }} 项</span>
      </header>

      <div v-if="currentPlans.length" class="plan-stack">
        <article v-for="plan in currentPlans" :key="plan.id" class="plan-row">
          <div class="plan-identity">
            <strong>{{ plan.name }}</strong>
            <span>{{ plan.symbol }} · {{ marketLabel(plan.market) }} · {{ plan.direction === 'buy' ? '买入' : '卖出' }}</span>
          </div>
          <div class="plan-prices">
            <span>计划价 {{ plan.planPrice || '待补充' }}</span>
            <span>目标价 {{ plan.targetPrice || '待补充' }}</span>
          </div>
          <span v-if="plan.isPrimary" class="primary-label">当前主计划</span>
          <span v-else class="draft-label">草稿</span>
        </article>
      </div>
      <div v-else class="plan-empty">当前会话还没有计划。第一项计划默认设为当前主计划。</div>
    </section>

    <section class="new-plan" aria-labelledby="new-session-plan-title">
      <header>
        <span>新增</span>
        <h3 id="new-session-plan-title">创建当前会话的计划</h3>
      </header>

      <div class="plan-form">
        <label class="field field--wide">
          <span>计划名称 <em>必填</em></span>
          <el-input v-model="draft.name" placeholder="例如：回调分批买入" />
        </label>
        <label class="field">
          <span>标的 <em>必填</em></span>
          <el-input v-model="draft.symbol" placeholder="代码或标准标识" />
        </label>
        <label class="field">
          <span>市场</span>
          <el-select v-model="draft.market">
            <el-option label="中国内地" value="CN" />
            <el-option label="香港" value="HK" />
            <el-option label="美国" value="US" />
          </el-select>
        </label>
        <label class="field">
          <span>方向</span>
          <el-segmented
            v-model="draft.direction"
            :options="[{ label: '买入', value: 'buy' }, { label: '卖出', value: 'sell' }]"
          />
        </label>
        <label class="field">
          <span>计划价</span>
          <el-input v-model="draft.planPrice" inputmode="decimal" placeholder="可稍后补充" />
        </label>
        <label class="field">
          <span>目标价</span>
          <el-input v-model="draft.targetPrice" inputmode="decimal" placeholder="可稍后补充" />
        </label>
        <label class="primary-choice field--wide">
          <el-switch v-model="draft.isPrimary" />
          <span>
            <strong>设为当前会话的主计划</strong>
            <small>启用后会替换本会话原有主计划，不影响其他会话。</small>
          </span>
        </label>
      </div>
    </section>

    <template #footer>
      <div class="dialog-actions">
        <span>前端交互预览 · 暂不写入服务端</span>
        <el-button @click="close">关闭</el-button>
        <el-button type="primary" :disabled="!canSave" @click="save">添加到当前会话</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
:global(.session-plan-dialog) { display: flex; max-height: calc(100vh - 32px); margin-top: 16px !important; margin-bottom: 16px !important; flex-direction: column; }
:global(.session-plan-dialog .el-dialog__body) { min-height: 0; overflow-y: auto; }
.dialog-heading span, .new-plan > header span { color: var(--accent); font-size: 10px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
.dialog-heading h2 { margin: 3px 0 5px; font-family: 'Songti SC', 'Source Han Serif SC', serif; font-size: 24px; }
.dialog-heading p { margin: 0; color: var(--muted); font-size: 13px; }
.current-plans { padding-bottom: 22px; border-bottom: 1px solid var(--line); }
.current-plans > header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.current-plans h3, .new-plan h3 { margin: 0; font-size: 15px; }
.current-plans > header span { color: var(--muted); font-size: 12px; }
.plan-stack { display: flex; flex-direction: column; border-top: 1px solid var(--line); }
.plan-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 16px; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--line); }
.plan-identity, .plan-prices { display: flex; min-width: 0; flex-direction: column; }
.plan-identity strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plan-identity span, .plan-prices span, .plan-empty, .dialog-actions > span { color: var(--muted); font-size: 12px; }
.primary-label, .draft-label { padding: 3px 7px; border: 1px solid var(--line-strong); border-radius: 999px; font-size: 11px; white-space: nowrap; }
.primary-label { border-color: color-mix(in srgb, var(--accent) 60%, var(--line)); color: var(--accent); }
.draft-label { color: var(--muted); }
.plan-empty { padding: 18px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.new-plan { padding-top: 22px; }
.new-plan > header { margin-bottom: 14px; }
.new-plan h3 { margin-top: 3px; }
.plan-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 18px; }
.field { display: flex; min-width: 0; flex-direction: column; gap: 7px; }
.field--wide { grid-column: 1 / -1; }
.field > span { font-size: 13px; font-weight: 600; }
.field em { color: var(--warning); font-style: normal; }
.field :deep(.el-select) { width: 100%; }
.primary-choice { display: flex; align-items: center; gap: 10px; padding-top: 4px; }
.primary-choice > span { display: flex; flex-direction: column; }
.primary-choice strong { font-size: 13px; }
.primary-choice small { color: var(--muted); }
.dialog-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; }
.dialog-actions > span { margin-right: auto; }
@media (max-width: 640px) {
  .plan-form { grid-template-columns: 1fr; }
  .field--wide { grid-column: auto; }
  .plan-row { grid-template-columns: minmax(0, 1fr) auto; }
  .plan-prices { grid-column: 1 / -1; flex-direction: row; gap: 12px; }
  .dialog-actions > span { display: none; }
}
</style>

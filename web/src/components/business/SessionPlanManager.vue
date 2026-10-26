<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { runs as runsApi } from '@/api'
import type {
  SessionBuySellPlanInput,
  SessionPlanInput,
  SessionPlanPreview,
} from '@/business-ui'
import { useBusinessStore } from '@/stores/business'

const props = defineProps<{
  modelValue: boolean
  sessionId: string | null
  sessionTitle: string
  plans: readonly SessionPlanPreview[]
  savePlan: (plan: SessionPlanInput) => Promise<void>
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  dirtyChange: [dirty: boolean]
  runSubmitted: [submission: { sessionId: string; runId: string; message: string }]
}>()

// 计划不保存价格（2026-10-08 口径）：只登记本标的规划资金；成交价由成交记录回填。
const draft = reactive<SessionPlanInput>({
  name: '',
  symbol: '',
  market: 'CN',
  direction: 'buy',
  allocatedCapital: '',
  isPrimary: false,
})

const business = useBusinessStore()

const currentPlans = computed(() => props.plans.filter((plan) => plan.sessionId === props.sessionId))
const canSave = computed(() => !!props.sessionId && !!draft.name.trim() && !!draft.symbol.trim())
const saving = ref(false)
const saveError = ref('')

// ——— 规划资金（会话 1:1）：只累加或重置，不做覆盖式更新 ———
const capitalDraft = reactive({
  amount: '',
  currency: 'CNY',
  delta: '',
  resetAmount: '',
})
const capitalBusy = ref(false)
const capitalError = ref('')

// ——— 实际买卖价格（规划资金 1:N）———
const buySellDraft = reactive<SessionBuySellPlanInput>({
  symbol: '',
  market: 'CN',
  side: 'buy',
  price: '',
  quantity: '',
  tradedAt: '',
  currency: 'CNY',
})
const buySellBusy = ref(false)
const buySellError = ref('')

watch(() => props.sessionId, () => {
  resetDraft()
  resetCapitalDraft()
  resetBuySellDraft()
}, { flush: 'sync' })
watch(() => props.modelValue, (open) => {
  if (!open) {
    resetDraft()
    resetCapitalDraft()
    resetBuySellDraft()
  } else {
    draft.isPrimary = currentPlans.value.length === 0
    if (props.sessionId) void business.loadCapitalPlan(props.sessionId)
  }
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
  return !!(draft.name || draft.symbol || draft.allocatedCapital
    || capitalDraft.amount || capitalDraft.delta || capitalDraft.resetAmount
    || buySellDraft.symbol || buySellDraft.price
    || draft.market !== 'CN' || draft.direction !== 'buy')
}

function resetCapitalDraft(): void {
  capitalError.value = ''
  Object.assign(capitalDraft, { amount: '', delta: '', resetAmount: '' })
}

function resetBuySellDraft(): void {
  buySellError.value = ''
  Object.assign(buySellDraft, {
    symbol: '',
    market: 'CN',
    side: 'buy',
    price: '',
    quantity: '',
    tradedAt: '',
    currency: 'CNY',
  } satisfies SessionBuySellPlanInput)
}

function decimalOk(value: string): boolean {
  return /^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value.trim())
}

/** 创建会话唯一的规划资金；已存在时服务端拒绝，不会覆盖原值。 */
async function createCapitalPlan(): Promise<void> {
  if (capitalBusy.value || !props.sessionId) return
  capitalError.value = ''
  if (!decimalOk(capitalDraft.amount)) {
    capitalError.value = '请输入非负十进制金额'
    return
  }
  capitalBusy.value = true
  try {
    await business.createCapitalPlan(props.sessionId, {
      allocatedCapital: capitalDraft.amount,
      currency: capitalDraft.currency,
    })
    capitalDraft.amount = ''
    ElMessage.success('规划资金已创建')
  } catch (err) {
    capitalError.value = err instanceof Error ? err.message : '保存失败，请重试'
  } finally {
    capitalBusy.value = false
  }
}

/** 在现有累计值上增加分配，而不是覆盖成新总额。 */
async function allocateCapital(): Promise<void> {
  if (capitalBusy.value) return
  capitalError.value = ''
  if (!decimalOk(capitalDraft.delta) || Number(capitalDraft.delta) <= 0) {
    capitalError.value = '请输入大于 0 的累加金额'
    return
  }
  capitalBusy.value = true
  try {
    await business.allocateCapital(capitalDraft.delta)
    capitalDraft.delta = ''
    ElMessage.success('已累加分配资金')
  } catch (err) {
    capitalError.value = err instanceof Error ? err.message : '累加失败，请重试'
  } finally {
    capitalBusy.value = false
  }
}

/** 重置为指定总额；与累加共用版本流，历史仍可追溯。 */
async function resetCapital(): Promise<void> {
  if (capitalBusy.value) return
  capitalError.value = ''
  if (!decimalOk(capitalDraft.resetAmount)) {
    capitalError.value = '请输入非负十进制金额'
    return
  }
  if (!window.confirm('重置会用新总额覆盖当前累计值（历史版本保留）。是否继续？')) return
  capitalBusy.value = true
  try {
    await business.resetCapital(capitalDraft.resetAmount)
    capitalDraft.resetAmount = ''
    ElMessage.success('规划资金已重置')
  } catch (err) {
    capitalError.value = err instanceof Error ? err.message : '重置失败，请重试'
  } finally {
    capitalBusy.value = false
  }
}

async function saveBuySellPlan(): Promise<void> {
  if (buySellBusy.value) return
  buySellError.value = ''
  if (!buySellDraft.symbol.trim() || !buySellDraft.price.trim()) {
    buySellError.value = '请填写标的与实际买卖价格'
    return
  }
  if (!decimalOk(buySellDraft.price)) {
    buySellError.value = '价格必须是十进制文本，不使用千分位或科学计数法'
    return
  }
  buySellBusy.value = true
  try {
    await business.createBuySellPlan(buySellDraft)
    resetBuySellDraft()
    ElMessage.success('实际买卖价格已保存')
  } catch (err) {
    buySellError.value = err instanceof Error ? err.message : '保存失败，请重试'
  } finally {
    buySellBusy.value = false
  }
}

async function archiveBuySellPlan(id: string): Promise<void> {
  if (buySellBusy.value) return
  buySellError.value = ''
  buySellBusy.value = true
  try {
    await business.archiveBuySellPlan(id)
  } catch (err) {
    buySellError.value = err instanceof Error ? err.message : '归档失败，请重试'
  } finally {
    buySellBusy.value = false
  }
}

function resetDraft(): void {
  saveError.value = ''
  Object.assign(draft, {
    name: '',
    symbol: '',
    market: 'CN',
    direction: 'buy',
    allocatedCapital: '',
    isPrimary: currentPlans.value.length === 0,
  } satisfies SessionPlanInput)
}

function discardDraft(): boolean {
  if (saving.value) return false
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

async function save(): Promise<void> {
  if (saving.value) return
  saveError.value = ''
  if (!canSave.value) {
    saveError.value = '请填写计划名称和标的后保存'
    return
  }
  const sessionId = props.sessionId
  const input = {
    ...draft,
    name: draft.name.trim(),
    symbol: draft.symbol.trim().toUpperCase(),
    allocatedCapital: draft.allocatedCapital.trim(),
  }
  saving.value = true
  try {
    await props.savePlan(input)
    if (props.sessionId === sessionId) resetDraft()
  } catch (err) {
    if (props.sessionId === sessionId) {
      saveError.value = err instanceof Error ? err.message : '保存失败，请重试'
    }
  } finally {
    saving.value = false
  }
}

function marketLabel(market: SessionPlanPreview['market']): string {
  return { CN: '中国内地', HK: '香港', US: '美国' }[market]
}

// ——— 回填实际成交价（2026-10-08 口径）———
// 计划不保存价格：用户按 Agent 建议价成交后，把**实际成交价**回填到这里并提交为
// holding_cost 用途的新 Run；后端在同一事务内新登记一条成交再重新分析。
const trade = reactive({
  side: 'buy' as 'buy' | 'sell',
  quantity: '',
  price: '',
  tradedAt: '',
  fees: '',
})
const tradeError = ref('')
const submittingTrade = ref(false)
const canSubmitTrade = computed(
  () => !!trade.quantity.trim() && !!trade.price.trim() && !!trade.tradedAt.trim(),
)

function resetTrade(): void {
  Object.assign(trade, { side: 'buy', quantity: '', price: '', tradedAt: '', fees: '' })
  tradeError.value = ''
}

async function submitTrade(): Promise<void> {
  tradeError.value = ''
  if (!canSubmitTrade.value) {
    tradeError.value = '请填写成交量、实际成交价与成交时间'
    return
  }
  const accountId = business.link?.account_id ?? null
  const planId = business.link?.primary_plan_id ?? null
  if (!props.sessionId || !accountId || !planId) {
    tradeError.value = '请先把主账户与当前主计划绑定到本会话'
    return
  }
  const plan = business.plans.find((item) => item.id === planId)
  const symbol = plan?.values?.symbol ?? ''
  const currency = plan?.values?.currency ?? 'CNY'
  const sessionId = props.sessionId
  const message = `已按 ${trade.price.trim()} ${trade.side === 'buy' ? '买入' : '卖出'} ${trade.quantity.trim()}，请按实际成交成本重新分析。`
  submittingTrade.value = true
  try {
    const res = await runsApi.submit({
      session_id: sessionId,
      message,
      investment_input: {
        use_case: 'holding_cost',
        account: { id: accountId },
        plan: { id: planId },
        declared: {
          trade: {
            symbol,
            side: trade.side,
            quantity: trade.quantity.trim(),
            price: trade.price.trim(),
            currency,
            traded_at: trade.tradedAt.trim(),
            ...(trade.fees.trim() ? { fees: trade.fees.trim() } : {}),
          },
        },
        idempotency_key: `fill-trade:${crypto.randomUUID()}`,
      },
    })
    resetTrade()
    emit('runSubmitted', { sessionId, runId: res.run_id, message })
    ElMessage.success(`成交已保存，分析已排队（Run ${res.run_id ?? ''}）`)
  } catch (err) {
    tradeError.value = err instanceof Error ? err.message : '保存失败，请重试'
  } finally {
    submittingTrade.value = false
  }
}
defineExpose({ resetDraft })
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    width="min(720px, calc(100vw - 28px))"
    class="session-plan-dialog"
    :close-on-click-modal="false"
    :close-on-press-escape="!saving"
    :show-close="!saving"
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

      <el-form :disabled="saving" @submit.prevent="save">
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
        <label class="primary-choice field--wide">
          <el-switch v-model="draft.isPrimary" />
          <span>
            <strong>设为当前会话的主计划</strong>
            <small>启用后会替换本会话原有主计划，不影响其他会话。</small>
          </span>
        </label>
      </div>
      </el-form>
      <p v-if="saveError" class="trade-error" role="alert">{{ saveError }}；填写内容已保留。</p>
    </section>

    <section class="capital-plan" aria-labelledby="session-capital-plan-title">
      <header>
        <span>规划资金</span>
        <h3 id="session-capital-plan-title">本会话的规划资金</h3>
        <p>一个会话只有一条规划资金；多次分配按累加记录，不会互相覆盖。</p>
      </header>

      <div v-if="business.capitalPlanPreview" class="capital-current">
        <div class="capital-amount">
          <strong>{{ business.capitalPlanPreview.allocatedCapital || '待补充' }}</strong>
          <span>{{ business.capitalPlanPreview.currency || 'CNY' }} · 版本 {{ business.capitalPlanPreview.revision }}</span>
        </div>
        <div class="capital-actions">
          <label class="field">
            <span>增加分配</span>
            <el-input v-model="capitalDraft.delta" inputmode="decimal" placeholder="在现值上累加，例如 5000" />
          </label>
          <el-button :loading="capitalBusy" @click="allocateCapital">累加</el-button>
          <label class="field">
            <span>重置为</span>
            <el-input v-model="capitalDraft.resetAmount" inputmode="decimal" placeholder="新的规划资金总额" />
          </label>
          <el-button :loading="capitalBusy" @click="resetCapital">重置</el-button>
        </div>
      </div>
      <div v-else class="capital-create">
        <label class="field">
          <span>规划资金</span>
          <el-input v-model="capitalDraft.amount" inputmode="decimal" placeholder="本会话从账户可用资金中划出的金额" />
        </label>
        <label class="field">
          <span>币种</span>
          <el-select v-model="capitalDraft.currency">
            <el-option label="人民币 CNY" value="CNY" />
            <el-option label="港币 HKD" value="HKD" />
            <el-option label="美元 USD" value="USD" />
          </el-select>
        </label>
        <el-button type="primary" :loading="capitalBusy" @click="createCapitalPlan">创建规划资金</el-button>
      </div>
      <p v-if="capitalError" class="trade-error" role="alert">{{ capitalError }}</p>
    </section>

    <section class="buy-sell-plans" aria-labelledby="session-buy-sell-title">
      <header>
        <h3 id="session-buy-sell-title">实际买卖价格</h3>
        <span>{{ business.buySellPlanPreviews.length }} 笔 · 与规划资金一对多</span>
      </header>

      <div v-if="business.buySellPlanPreviews.length" class="plan-stack">
        <article
          v-for="entry in business.buySellPlanPreviews"
          :key="entry.id"
          class="plan-row"
          :class="{ 'is-archived': entry.archived }"
        >
          <div class="plan-identity">
            <strong>{{ entry.symbol }} · {{ entry.side === 'buy' ? '买入' : '卖出' }}</strong>
            <span>{{ entry.price }} {{ entry.currency }}<template v-if="entry.quantity"> · {{ entry.quantity }}</template></span>
          </div>
          <span class="draft-label">{{ entry.tradedAt || '未填时间' }}</span>
          <el-button
            v-if="!entry.archived"
            size="small"
            :disabled="buySellBusy"
            @click="archiveBuySellPlan(entry.id)"
          >
            归档
          </el-button>
          <span v-else class="draft-label">已归档</span>
        </article>
      </div>
      <div v-else class="plan-empty">
        还没有实际买卖价格。{{ business.capitalPlanPreview ? '可在下方登记每笔买入/卖出。' : '请先创建规划资金。' }}
      </div>

      <div v-if="business.capitalPlanPreview" class="plan-form buy-sell-form">
        <label class="field">
          <span>标的</span>
          <el-input v-model="buySellDraft.symbol" placeholder="代码或标准标识" />
        </label>
        <label class="field">
          <span>市场</span>
          <el-select v-model="buySellDraft.market">
            <el-option label="中国内地" value="CN" />
            <el-option label="香港" value="HK" />
            <el-option label="美国" value="US" />
          </el-select>
        </label>
        <label class="field">
          <span>方向</span>
          <el-segmented
            v-model="buySellDraft.side"
            :options="[{ label: '买入', value: 'buy' }, { label: '卖出', value: 'sell' }]"
          />
        </label>
        <label class="field">
          <span>实际价格 <em>必填</em></span>
          <el-input v-model="buySellDraft.price" inputmode="decimal" placeholder="实际成交价，不得用现价代替" />
        </label>
        <label class="field">
          <span>数量</span>
          <el-input v-model="buySellDraft.quantity" inputmode="decimal" placeholder="股数/份数，可留空" />
        </label>
        <label class="field">
          <span>成交时间</span>
          <el-date-picker
            v-model="buySellDraft.tradedAt"
            type="datetime"
            format="YYYY-MM-DD HH:mm:ss"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            placeholder="可留空"
          />
        </label>
        <label class="field">
          <span>币种</span>
          <el-select v-model="buySellDraft.currency">
            <el-option label="人民币 CNY" value="CNY" />
            <el-option label="港币 HKD" value="HKD" />
            <el-option label="美元 USD" value="USD" />
          </el-select>
        </label>
        <div class="field buy-sell-submit">
          <el-button type="primary" :loading="buySellBusy" @click="saveBuySellPlan">保存实际买卖价格</el-button>
        </div>
      </div>
      <p v-if="buySellError" class="trade-error" role="alert">{{ buySellError }}</p>
    </section>

    <section class="trade-fill" aria-labelledby="session-trade-fill-title">
      <header>
        <h3 id="session-trade-fill-title">回填实际成交价</h3>
        <span>计划不保存价格，价格以成交记录为准</span>
      </header>
      <div class="field-grid">
        <label class="field">
          <span>方向</span>
          <el-segmented
            v-model="trade.side"
            :options="[{ label: '买入', value: 'buy' }, { label: '卖出', value: 'sell' }]"
          />
        </label>
        <label class="field">
          <span>成交量</span>
          <el-input v-model="trade.quantity" inputmode="decimal" placeholder="股数/份数" />
        </label>
        <label class="field">
          <span>实际成交价</span>
          <el-input
            v-model="trade.price"
            inputmode="decimal"
            placeholder="不得用现价或建议价代替"
          />
        </label>
        <label class="field">
          <span>成交时间</span>
          <el-date-picker
            v-model="trade.tradedAt"
            type="datetime"
            format="YYYY-MM-DD HH:mm:ss"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            placeholder="选择实际成交时间"
          />
        </label>
        <label class="field">
          <span>费用（可选）</span>
          <el-input v-model="trade.fees" inputmode="decimal" placeholder="可留空" />
        </label>
      </div>
      <p v-if="tradeError" class="trade-error" role="alert">{{ tradeError }}</p>
      <el-button type="primary" :loading="submittingTrade" @click="submitTrade">
        保存成交并重新分析
      </el-button>
    </section>

    <template #footer>
      <div class="dialog-actions">
        <span>保存后归属当前会话</span>
        <el-button :disabled="saving" @click="close">关闭</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存计划</el-button>
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
.capital-plan, .buy-sell-plans { padding-top: 22px; margin-top: 22px; border-top: 1px solid var(--line); }
.capital-plan > header, .buy-sell-plans > header { margin-bottom: 14px; }
.capital-plan h3, .buy-sell-plans h3 { margin: 3px 0; font-size: 15px; }
.capital-plan > header p { margin: 0; color: var(--muted); font-size: 12px; }
.buy-sell-plans > header span { color: var(--muted); font-size: 12px; }
.capital-current { display: flex; flex-direction: column; gap: 14px; }
.capital-amount { display: flex; align-items: baseline; gap: 10px; }
.capital-amount strong { font-family: 'Songti SC', 'Source Han Serif SC', serif; font-size: 26px; }
.capital-amount span { color: var(--muted); font-size: 12px; }
.capital-actions, .capital-create { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)) auto; gap: 12px; align-items: end; }
.capital-create { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) auto; }
.buy-sell-form { margin-top: 14px; }
.buy-sell-submit { justify-content: flex-end; }
.plan-row.is-archived { opacity: .55; }
.plan-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 18px; }
.field { display: flex; min-width: 0; flex-direction: column; gap: 7px; }
.field--wide { grid-column: 1 / -1; }
.field > span { font-size: 13px; font-weight: 600; }
.field em { color: var(--warning); font-style: normal; }
.trade-error { color: var(--el-color-danger); font-size: 13px; }
.field :deep(.el-select) { width: 100%; }
.field :deep(.el-date-editor) { width: 100%; }
.primary-choice { display: flex; align-items: center; gap: 10px; padding-top: 4px; }
.primary-choice > span { display: flex; flex-direction: column; }
.primary-choice strong { font-size: 13px; }
.primary-choice small { color: var(--muted); }
.dialog-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; }
.dialog-actions > span { margin-right: auto; }
@media (max-width: 640px) {
  .plan-form { grid-template-columns: 1fr; }
  .capital-actions, .capital-create { grid-template-columns: 1fr; }
  .field--wide { grid-column: auto; }
  .plan-row { grid-template-columns: minmax(0, 1fr) auto; }
  .plan-prices { grid-column: 1 / -1; flex-direction: row; gap: 12px; }
  .dialog-actions > span { display: none; }
}
</style>

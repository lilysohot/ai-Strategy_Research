<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { runs as runsApi } from '@/api'
import type { SessionBuySellPlanInput, SessionPlanPreview } from '@/business-ui'
import { useBusinessStore } from '@/stores/business'

const props = defineProps<{
  modelValue: boolean
  sessionId: string | null
  sessionTitle: string
  plans: readonly SessionPlanPreview[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  dirtyChange: [dirty: boolean]
  runSubmitted: [submission: { sessionId: string; runId: string; message: string }]
}>()

const business = useBusinessStore()
const fundingAccount = computed(() => business.accounts.find(
  (account) => account.id === capitalDraft.accountId,
))
const boundAccount = computed(() => business.accounts.find(account => account.id === business.capitalPlan?.account_id))
const accountOptions = computed(() => business.accounts.filter(account =>
  !account.archived || account.id === business.capitalPlan?.account_id,
))
const capitalLoading = ref(false)
const initialAccountId = ref('')

const currentPlans = computed(() => props.plans.filter((plan) => plan.sessionId === props.sessionId))

// ——— 规划资金（会话 1:1）：只累加或重置，不做覆盖式更新 ———
const capitalDraft = reactive({
  accountId: '',
  amount: '',
  currency: 'CNY',
  delta: '',
  resetAmount: '',
})
const capitalBusy = ref(false)
const capitalError = ref('')

// ——— 实际买卖价格（规划资金 1:N）———
// 与回填实际成交价合并为一个入口：保存即登记买卖价格，并在会话资金账户已绑定时
// 自动提交 holding_cost 成本分析 Run（保存必须保留执行分析）。
const buySellDraft = reactive<SessionBuySellPlanInput & { fees: string }>({
  symbol: '',
  market: 'CN',
  side: 'buy',
  price: '',
  quantity: '',
  tradedAt: '',
  currency: 'CNY',
  fees: '',
})
const buySellBusy = ref(false)
const buySellError = ref('')
const canAnalyzeTrade = computed(
  () => !!(props.sessionId && business.capitalPlan?.account_id
    && capitalDraft.accountId === business.capitalPlan.account_id),
)

watch(() => props.sessionId, () => {
  resetCapitalDraft()
  resetBuySellDraft()
}, { flush: 'sync' })
watch([() => props.modelValue, () => props.sessionId], async ([open, sessionId]) => {
  resetCapitalDraft()
  resetBuySellDraft()
  if (!open || !sessionId) return
  capitalLoading.value = true
  try {
    await Promise.all([
      business.loadCapitalPlan(sessionId), business.loadAccounts(), business.loadLink(sessionId),
    ])
    if (props.sessionId !== sessionId || !props.modelValue) return
    const preferred = business.capitalPlan?.account_id ?? business.link?.account_id
      ?? business.accounts.find(account => account.is_default && !account.archived)?.id
      ?? (accountOptions.value.length === 1 ? accountOptions.value[0]?.id : '')
    initialAccountId.value = preferred ?? ''
    capitalDraft.accountId = initialAccountId.value
    capitalDraft.currency = business.capitalPlan?.values.currency ?? fundingAccount.value?.base_currency ?? 'CNY'
    buySellDraft.currency = capitalDraft.currency
  } catch (err) {
    capitalError.value = err instanceof Error ? err.message : '加载资金账户失败'
  } finally {
    if (props.sessionId === sessionId) capitalLoading.value = false
  }
}, { immediate: true })

watch(() => capitalDraft.accountId, () => {
  if (!business.capitalPlan && fundingAccount.value) {
    capitalDraft.currency = fundingAccount.value.base_currency
    buySellDraft.currency = fundingAccount.value.base_currency
  }
})
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
  return !!(capitalDraft.accountId !== initialAccountId.value || capitalDraft.amount || capitalDraft.delta || capitalDraft.resetAmount
    || buySellDraft.symbol || buySellDraft.price
    || buySellDraft.quantity || buySellDraft.tradedAt || buySellDraft.fees)
}

watch([capitalDraft, buySellDraft], () => emit('dirtyChange', isDirty()), {
  deep: true,
  flush: 'sync',
})

function resetCapitalDraft(): void {
  capitalError.value = ''
  initialAccountId.value = ''
  Object.assign(capitalDraft, { accountId: '', amount: '', delta: '', resetAmount: '' })
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
    currency: business.capitalPlan?.values.currency ?? fundingAccount.value?.base_currency ?? 'CNY',
    fees: '',
  } satisfies SessionBuySellPlanInput & { fees: string })
}

function decimalOk(value: string): boolean {
  return /^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value.trim())
}

/** 创建会话唯一的规划资金；已存在时服务端拒绝，不会覆盖原值。 */
async function createCapitalPlan(): Promise<void> {
  if (capitalBusy.value || !props.sessionId) return
  capitalError.value = ''
  if (!capitalDraft.accountId || !fundingAccount.value || fundingAccount.value.archived) {
    capitalError.value = '请选择本会话的资金来源账户'
    return
  }
  if (!decimalOk(capitalDraft.amount)) {
    capitalError.value = '请输入非负十进制金额'
    return
  }
  capitalBusy.value = true
  try {
    await business.createCapitalPlan(props.sessionId, {
      allocatedCapital: capitalDraft.amount,
      currency: capitalDraft.currency,
      accountId: capitalDraft.accountId,
    })
    capitalDraft.amount = ''
    initialAccountId.value = capitalDraft.accountId
    ElMessage.success('规划资金已创建')
  } catch (err) {
    capitalError.value = err instanceof Error ? err.message : '保存失败，请重试'
  } finally {
    capitalBusy.value = false
  }
}

async function bindCapitalAccount(): Promise<void> {
  if (capitalLoading.value || capitalBusy.value || buySellBusy.value || !capitalDraft.accountId) return
  capitalError.value = ''
  capitalBusy.value = true
  try {
    await business.bindCapitalAccount(capitalDraft.accountId)
    initialAccountId.value = capitalDraft.accountId
    ElMessage.success('会话资金账户已绑定')
  } catch (err) {
    capitalError.value = err instanceof Error ? err.message : '账户绑定失败'
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

/** 保存一笔实际买卖价格，使用本会话资金账户自动触发成本分析。 */
async function saveBuySellPlan(): Promise<void> {
  if (buySellBusy.value || capitalBusy.value || capitalLoading.value) return
  buySellError.value = ''
  if (!props.sessionId || !business.capitalPlan?.account_id || capitalDraft.accountId !== business.capitalPlan.account_id) {
    buySellError.value = '请先保存本会话的资金账户绑定，再登记买卖'
    return
  }
  if (!buySellDraft.symbol.trim() || !buySellDraft.price.trim()) {
    buySellError.value = '请填写标的与实际买卖价格'
    return
  }
  if (!decimalOk(buySellDraft.price)) {
    buySellError.value = '价格必须是十进制文本，不使用千分位或科学计数法'
    return
  }
  if (!buySellDraft.quantity.trim() || !buySellDraft.tradedAt.trim()) {
    buySellError.value = '成本分析需要成交量与成交时间，请补齐后再保存'
    return
  }
  // Capture the source session/account before refreshing shared store state.
  const sessionId = props.sessionId
  const accountId = business.capitalPlan.account_id
  buySellBusy.value = true
  const submitted = {
    symbol: buySellDraft.symbol.trim().toUpperCase(),
    market: buySellDraft.market,
    side: buySellDraft.side,
    price: buySellDraft.price.trim(),
    quantity: buySellDraft.quantity.trim(),
    tradedAt: buySellDraft.tradedAt.trim(),
    currency: buySellDraft.currency.trim(),
    fees: buySellDraft.fees.trim(),
  }
  try {
    await business.createBuySellPlan(buySellDraft)
    resetBuySellDraft()
  } catch (err) {
    buySellError.value = err instanceof Error ? err.message : '保存失败，请重试'
    buySellBusy.value = false
    return
  }
  const message = `已按 ${submitted.price} ${submitted.currency} ${submitted.side === 'buy' ? '买入' : '卖出'} ${submitted.symbol} ${submitted.quantity}，请按实际成交成本重新分析。`
  try {
    const res = await runsApi.submit({
      session_id: sessionId,
      message,
      investment_input: {
        use_case: 'holding_cost',
        account: { id: accountId },
        declared: {
          trade: {
            symbol: submitted.symbol,
            market: submitted.market,
            side: submitted.side,
            quantity: submitted.quantity,
            price: submitted.price,
            currency: submitted.currency,
            traded_at: submitted.tradedAt,
            ...(submitted.fees ? { fees: submitted.fees } : {}),
          },
        },
        idempotency_key: `fill-trade:${crypto.randomUUID()}`,
      },
    })
    emit('runSubmitted', { sessionId, runId: res.run_id, message })
    ElMessage.success(`实际买卖价格已保存，成本分析已排队（Run ${res.run_id ?? ''}）`)
  } catch (err) {
    // 价格记录已保存成功，只是分析未提交成功；不回滚也不重复登记。
    buySellError.value = `价格已保存，成本分析提交失败：${err instanceof Error ? err.message : '请重试'}`
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

function clearDrafts(): void {
  resetCapitalDraft()
  resetBuySellDraft()
}

function discardDraft(): boolean {
  if (isDirty() && !window.confirm('规划资金或买卖价格尚未保存，关闭将丢弃。是否继续？')) return false
  clearDrafts()
  return true
}

function beforeClose(done: () => void): void {
  if (discardDraft()) done()
}

function close(): void {
  if (!discardDraft()) return
  emit('update:modelValue', false)
}

function marketLabel(market: SessionPlanPreview['market']): string {
  return { CN: '中国内地', HK: '香港', US: '美国' }[market]
}

defineExpose({ resetDraft: clearDrafts })
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
        <span>会话资金</span>
        <h2>{{ sessionTitle }}</h2>
        <p>规划资金与实际买卖价格自动归属当前会话；已有计划仅作只读展示。</p>
      </div>
    </template>

    <section v-if="currentPlans.length" class="current-plans" aria-labelledby="current-session-plan-title">
      <header>
        <h3 id="current-session-plan-title">已归属本会话的计划</h3>
        <span>{{ currentPlans.length }} 项</span>
      </header>

      <div class="plan-stack">
        <article v-for="plan in currentPlans" :key="plan.id" class="plan-row">
          <div class="plan-identity">
            <strong>{{ plan.name }}</strong>
            <span>{{ plan.symbol }} · {{ marketLabel(plan.market) }} · {{ plan.direction === 'buy' ? '买入' : '卖出' }}</span>
          </div>
          <span v-if="plan.isPrimary" class="primary-label">当前主计划</span>
          <span v-else class="draft-label">草稿</span>
        </article>
      </div>
    </section>

    <section v-loading="capitalLoading" class="capital-plan" aria-labelledby="session-capital-plan-title">
      <p v-if="business.error" role="alert">{{ business.error }}</p>
      <label class="field">
        <span>资金来源账户</span>
        <el-select v-model="capitalDraft.accountId" placeholder="选择本会话绑定的资金账户"
          :disabled="capitalLoading || capitalBusy || buySellBusy || business.capitalPlan?.account_binding_locked">
          <el-option v-for="account in accountOptions" :key="account.id" :value="account.id"
            :disabled="account.archived"
            :label="`${account.name}${account.is_default ? '（默认主账户）' : ''}${account.archived ? '（已归档）' : ''} · ${account.base_currency} · 可分配 ${account.funding?.allocatable_capital ?? '待补充'}`" />
        </el-select>
      </label>
      <p v-if="business.capitalPlan">
        当前绑定：{{ boundAccount?.name ?? business.capitalPlan.account_id ?? '尚未绑定' }}
        <span v-if="business.capitalPlan.account_binding_locked"> · 已有资金入账，账户归属已固定</span>
      </p>
      <el-button v-if="business.capitalPlan && !business.capitalPlan.account_binding_locked"
        :disabled="capitalLoading || buySellBusy || !capitalDraft.accountId || capitalDraft.accountId === business.capitalPlan.account_id"
        :loading="capitalBusy" @click="bindCapitalAccount">绑定资金账户</el-button>
      <p v-if="!capitalLoading && !accountOptions.length">请先在交易账户资料中创建资金账户。</p>
      <p v-if="fundingAccount?.funding">
        所选账户现金 {{ fundingAccount.values.available_capital ?? '待补充' }} ·
        已预留 {{ fundingAccount.funding.reserved_capital }} ·
        可继续分配 {{ fundingAccount.funding.allocatable_capital ?? '待补充' }}
        {{ fundingAccount.base_currency }}
      </p>
      <p v-if="business.capitalPlan?.funding">
        本会话剩余额度 {{ business.capitalPlan.funding.remaining_capital ?? '待补充' }}
        {{ business.capitalPlan.values.currency }}
        <span v-if="business.capitalPlan.funding.unbooked_count">
          · {{ business.capitalPlan.funding.unbooked_count }} 笔记录尚未联动资金
        </span>
      </p>
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
          <el-button :loading="capitalBusy" :disabled="!business.capitalPlan?.account_id || capitalDraft.accountId !== business.capitalPlan.account_id" @click="allocateCapital">累加</el-button>
          <label class="field">
            <span>重置为</span>
            <el-input v-model="capitalDraft.resetAmount" inputmode="decimal" placeholder="新的规划资金总额" />
          </label>
          <el-button :loading="capitalBusy" :disabled="!business.capitalPlan?.account_id || capitalDraft.accountId !== business.capitalPlan.account_id" @click="resetCapital">重置</el-button>
        </div>
      </div>
      <div v-else class="capital-create">
        <label class="field">
          <span>规划资金</span>
          <el-input v-model="capitalDraft.amount" inputmode="decimal" placeholder="本会话从账户可用资金中划出的金额" />
        </label>
        <label class="field">
          <span>币种</span>
          <el-select v-model="capitalDraft.currency" disabled>
            <el-option label="人民币 CNY" value="CNY" />
            <el-option label="港币 HKD" value="HKD" />
            <el-option label="美元 USD" value="USD" />
          </el-select>
        </label>
        <el-button type="primary" :loading="capitalBusy" :disabled="capitalLoading || !capitalDraft.accountId" @click="createCapitalPlan">创建并绑定规划资金</el-button>
      </div>
      <p v-if="capitalError" class="trade-error" role="alert">{{ capitalError }}</p>
    </section>

    <section class="buy-sell-plans" aria-labelledby="session-buy-sell-title">
      <header>
        <h3 id="session-buy-sell-title">实际买卖价格</h3>
        <span>{{ business.buySellPlanPreviews.length }} 笔 · 保存后自动触发成本分析</span>
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
            <span v-if="!entry.archived && entry.cashEffect == null">尚未联动资金</span>
          </div>
          <span class="draft-label">{{ entry.tradedAt || '未填时间' }}</span>
          <el-button
            v-if="!entry.archived"
            size="small"
            :disabled="buySellBusy"
            @click="archiveBuySellPlan(entry.id)"
          >
            作废并归档
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
          <span>数量 <em>必填</em></span>
          <el-input v-model="buySellDraft.quantity" inputmode="decimal" placeholder="股数/份数" />
        </label>
        <label class="field">
          <span>成交时间 <em>必填</em></span>
          <el-date-picker
            v-model="buySellDraft.tradedAt"
            type="datetime"
            format="YYYY-MM-DD HH:mm:ss"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            placeholder="选择实际成交时间"
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
        <label class="field">
          <span>费用（可选）</span>
          <el-input v-model="buySellDraft.fees" inputmode="decimal" placeholder="可留空" />
        </label>
        <div class="field buy-sell-submit">
          <el-button type="primary" :loading="buySellBusy"
            :disabled="capitalLoading || capitalBusy || !business.capitalPlan?.account_id || capitalDraft.accountId !== business.capitalPlan.account_id"
            @click="saveBuySellPlan">
            {{ canAnalyzeTrade ? '保存并重新分析' : '保存实际买卖价格' }}
          </el-button>
        </div>
      </div>
      <p v-if="buySellError" class="trade-error" role="alert">{{ buySellError }}</p>
    </section>

    <template #footer>
      <div class="dialog-actions">
        <span>保存后自动归属当前会话</span>
        <el-button type="primary" @click="close">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
:global(.session-plan-dialog) { display: flex; max-height: calc(100vh - 32px); margin-top: 16px !important; margin-bottom: 16px !important; flex-direction: column; }
:global(.session-plan-dialog .el-dialog__body) { min-height: 0; overflow-y: auto; }
.dialog-heading span, .capital-plan > header span { color: var(--accent); font-size: 10px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
.dialog-heading h2 { margin: 3px 0 5px; font-family: 'Songti SC', 'Source Han Serif SC', serif; font-size: 24px; }
.dialog-heading p { margin: 0; color: var(--muted); font-size: 13px; }
.current-plans { padding-bottom: 22px; border-bottom: 1px solid var(--line); }
.current-plans > header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.current-plans h3 { margin: 0; font-size: 15px; }
.current-plans > header span { color: var(--muted); font-size: 12px; }
.plan-stack { display: flex; flex-direction: column; border-top: 1px solid var(--line); }
.plan-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 16px; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--line); }
.plan-identity { display: flex; min-width: 0; flex-direction: column; }
.plan-identity strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plan-identity span, .plan-empty, .dialog-actions > span { color: var(--muted); font-size: 12px; }
.primary-label, .draft-label { padding: 3px 7px; border: 1px solid var(--line-strong); border-radius: 999px; font-size: 11px; white-space: nowrap; }
.primary-label { border-color: color-mix(in srgb, var(--accent) 60%, var(--line)); color: var(--accent); }
.draft-label { color: var(--muted); }
.plan-empty { padding: 18px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
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
.dialog-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; }
.dialog-actions > span { margin-right: auto; }
@media (max-width: 640px) {
  .plan-form { grid-template-columns: 1fr; }
  .capital-actions, .capital-create { grid-template-columns: 1fr; }
  .field--wide { grid-column: auto; }
  .plan-row { grid-template-columns: minmax(0, 1fr) auto; }
  .dialog-actions > span { display: none; }
}
</style>

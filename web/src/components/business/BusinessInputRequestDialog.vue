<script setup lang="ts">
/**
 * Agent 识别缺数据后由服务端生成 input_request（pending）；本组件是它的
 * **结构化补数弹窗**：主账户资金只读 + 规划资金（必需）+ 承受风险/期望盈利（可后补）。
 *
 * 触发方负责查询 pending 请求并把它传进来；本组件只负责填写与提交（answer 接口），
 * 提交成功后服务端按 DATA-07 创建后续 Run。
 *
 * 字段集适配由 `ChatView.maybeOpenInputRequest` 用 `dialogCoversRequest` 判定：
 * 请求里还有弹窗采集不到的字段（例如 `plan.symbol`/`plan.market`/`plan.direction`）时
 * 不该自动弹这个窗，用户会永远停在"仍有待澄清项"。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { accounts as accountsApi, inputRequests as inputRequestsApi, link as linkApi } from '@/api'
import { useBusinessStore } from '@/stores/business'
import type { InputRequest } from '@/types'

const props = defineProps<{
  modelValue: boolean
  request: InputRequest | null
  /** 当前研究：无主账户时，弹窗内直接创建并绑定到它。 */
  researchId: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; answered: [] }>()

const store = useBusinessStore()
const form = reactive({
  allocatedCapital: '',
  riskValue: '',
  riskUnit: 'percent',
  profitValue: '',
  profitUnit: 'percent',
})
/** 无主账户时的内联创建草稿：只问总资金/可用资金，其余给可用默认值。 */
const accountDraft = reactive({
  totalCapital: '',
  availableCapital: '',
  currency: 'CNY',
  capitalBasis: 'tradable_assets',
})
const error = ref('')
const submitting = ref(false)

const boundAccount = computed(() => {
  const id = store.link?.account_id ?? null
  if (!id) return null
  return store.accounts.find((item) => item.id === id) ?? null
})
const totalCapital = computed(() => boundAccount.value?.values?.total_capital ?? null)
const availableCapital = computed(() => boundAccount.value?.values?.available_capital ?? null)
const missingFields = computed(() => props.request?.remaining_fields ?? [])

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    error.value = ''
    Object.assign(form, {
      allocatedCapital: '',
      riskValue: '',
      riskUnit: 'percent',
      profitValue: '',
      profitUnit: 'percent',
    })
    Object.assign(accountDraft, {
      totalCapital: '',
      availableCapital: '',
      currency: 'CNY',
      capitalBasis: 'tradable_assets',
    })
  },
)

function close(): void {
  emit('update:modelValue', false)
}

/**
 * 无主账户时，在弹窗内直接创建主账户并绑定到当前研究。
 *
 * 为什么必须在这里做完：弹窗由 `ChatView.maybeOpenInputRequest` 的
 * `promptedRequestIds` 去重，同一请求关闭后不会再弹。若只提示"请先到交易账户资料
 * 创建"，用户跳走建完再回来仍然卡在同一处。
 *
 * 返回**同一批**账户事实（成功时），由 `submit` 随回答一起申报：请求的待补字段里
 * 常常就包含这些账户字段（服务端按用途裁决），只在账户接口里写一遍不算"回答了本次
 * 待补字段"，请求会一直停在 pending。失败返回 null。
 */
async function createAndBindAccount(): Promise<Record<string, unknown> | null> {
  const total = accountDraft.totalCapital.trim()
  if (!total) {
    error.value = '请先填写主账户总资金（用于校验本标的规划资金上限）'
    return null
  }
  if (!props.researchId) {
    error.value = '缺少当前研究标识，无法绑定主账户；请刷新后重试'
    return null
  }
  const suffix = `${props.request?.id ?? 'request'}:${crypto.randomUUID()}`
  // 可用资金留空时按总资金处理：规划资金上限校验依赖它，不能缺。
  const available = accountDraft.availableCapital.trim() || total
  const asOf = new Date().toISOString()
  const created = await accountsApi.create(
    {
      name: '主账户',
      base_currency: accountDraft.currency,
      declared: {
        total_capital: total,
        available_capital: available,
        capital_basis: accountDraft.capitalBasis,
        as_of: asOf,
      },
      use_case: 'general_reading',
      allow_incomplete: false,
    },
    `dialog-account:${suffix}`,
  )
  const accountId = String((created as { account_id?: string }).account_id ?? '')
  if (!accountId) {
    error.value = '主账户创建失败：服务端未返回账户 ID'
    return null
  }
  await linkApi.set(
    props.researchId,
    { account_id: accountId, primary_plan_id: store.link?.primary_plan_id ?? null },
    `dialog-link:${suffix}`,
  )
  await store.loadAccounts()
  await store.loadLink(props.researchId)
  return {
    total_capital: total,
    available_capital: available,
    currency: accountDraft.currency,
    capital_basis: accountDraft.capitalBasis,
    as_of: asOf,
  }
}

async function submit(): Promise<void> {
  const request = props.request
  error.value = ''
  if (!request) return
  if (!form.allocatedCapital.trim()) {
    error.value = '请填写本标的规划资金（从主账户可用资金中划出）'
    return
  }

  submitting.value = true
  try {
    let accountFacts: Record<string, unknown> | null = null
    if (!boundAccount.value) {
      accountFacts = await createAndBindAccount()
      if (!accountFacts) return
    }

    const declared: Record<string, Record<string, unknown>> = {
      plan: { allocated_capital: { value: form.allocatedCapital.trim() } },
    }
    // 只在本次请求真的索要账户事实时才申报：否则会白写一个账户版本
    // （账户接口那次已经写过了）。
    if (accountFacts && (request.remaining_fields ?? []).some((name) => name.startsWith('account.'))) {
      declared.account = accountFacts
    }
    if (form.riskValue.trim()) {
      declared.plan.risk_budget_value = { value: form.riskValue.trim() }
      declared.plan.risk_budget_unit = { value: form.riskUnit }
    }
    if (form.profitValue.trim()) {
      declared.plan.target_profit_value = { value: form.profitValue.trim() }
      declared.plan.target_profit_unit = { value: form.profitUnit }
    }
    const answer = [
      `本标的规划资金：${form.allocatedCapital.trim()}`,
      form.riskValue.trim() ? `可承受风险：${form.riskValue.trim()}（${form.riskUnit}）` : '',
      form.profitValue.trim() ? `期望盈利：${form.profitValue.trim()}（${form.profitUnit}）` : '',
    ]
      .filter(Boolean)
      .join('；')

    const result = await inputRequestsApi.answer(
      request.id,
      { answer, declared, expected_versions: request.current_versions ?? {} },
      `dialog-answer:${request.id}:${crypto.randomUUID()}`,
    )
    if (result.status === 'answered') {
      ElMessage.success('资料已保存，后续分析已进入队列')
      emit('answered')
      close()
    } else {
      // 列出服务端仍然缺的字段：只说"请补齐"用户不知道该补什么。
      const remaining = result.remaining_fields ?? []
      error.value = remaining.length
        ? `仍有待澄清项：${remaining.join('、')}；请补齐后用同一条请求重试（可在补数中心逐项填写）`
        : '仍有待澄清项：请补齐后用同一条请求重试'
    }
  } catch (err) {
    // 服务端字段级错误（例如规划资金超过账户可用资金）直接展示。
    error.value = err instanceof Error ? err.message : '保存失败，请重试'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    width="min(620px, calc(100vw - 28px))"
    class="input-request-dialog"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="dialog-heading">
        <span>需要补充资料</span>
        <h2>这次分析缺少必要输入</h2>
        <p>填写的是你自己的真实资料，保存后写入服务端；刷新或重新登录仍可见。</p>
      </div>
    </template>

    <section class="account-context">
      <h3>主账户</h3>
      <p v-if="boundAccount">
        总资金 {{ totalCapital ?? '未填写' }} · 可用资金 {{ availableCapital ?? '未填写' }}
      </p>
      <template v-else>
        <p class="account-missing">
          还没有主账户：填写下面两项即可创建并绑定到当前研究，不占用本弹窗之外的步骤。
        </p>
        <div class="field-pair">
          <el-input
            v-model="accountDraft.totalCapital"
            inputmode="decimal"
            placeholder="总资金（必需）"
          />
          <el-input
            v-model="accountDraft.availableCapital"
            inputmode="decimal"
            placeholder="可用资金（默认同总资金）"
          />
        </div>
        <div class="field-pair">
          <el-select v-model="accountDraft.currency">
            <el-option label="人民币 CNY" value="CNY" />
            <el-option label="美元 USD" value="USD" />
            <el-option label="港币 HKD" value="HKD" />
          </el-select>
          <el-select v-model="accountDraft.capitalBasis">
            <el-option label="可交易资产" value="tradable_assets" />
            <el-option label="证券账户总资产" value="brokerage_total" />
            <el-option label="专项策略资金" value="strategy_budget" />
          </el-select>
        </div>
      </template>
    </section>

    <section class="field-stack">
      <label class="answer-field">
        <span>本标的规划资金（必需）</span>
        <el-input
          v-model="form.allocatedCapital"
          inputmode="decimal"
          placeholder="从主账户可用资金中划出，不得超过可用资金"
        />
      </label>
      <label class="answer-field">
        <span>可承受风险（可后补）</span>
        <div class="field-pair">
          <el-input v-model="form.riskValue" inputmode="decimal" placeholder="数值" />
          <el-select v-model="form.riskUnit">
            <el-option label="比例 %" value="percent" />
            <el-option label="金额" value="amount" />
          </el-select>
        </div>
      </label>
      <label class="answer-field">
        <span>期望盈利（可后补）</span>
        <div class="field-pair">
          <el-input v-model="form.profitValue" inputmode="decimal" placeholder="数值" />
          <el-select v-model="form.profitUnit">
            <el-option label="比例 %" value="percent" />
            <el-option label="金额" value="amount" />
          </el-select>
        </div>
      </label>
      <p v-if="missingFields.length" class="missing-hint">
        服务端标记的待补字段：{{ missingFields.join('、') }}
      </p>
      <p v-if="error" class="trade-error" role="alert">{{ error }}</p>
    </section>

    <template #footer>
      <div class="dialog-actions">
        <el-button @click="close">稍后补充</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存并继续分析</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
/**
 * Agent 识别缺数据后由服务端生成 input_request（pending）；本组件是它的
 * **结构化补数弹窗**：主账户资金只读 + 规划资金（必需）+ 承受风险/期望盈利（可后补）。
 *
 * 触发方负责查询 pending 请求并把它传进来；本组件只负责填写与提交（answer 接口），
 * 提交成功后服务端按 DATA-07 创建后续 Run。
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { inputRequests as inputRequestsApi } from '@/api'
import { useBusinessStore } from '@/stores/business'
import type { InputRequest } from '@/types'

const props = defineProps<{ modelValue: boolean; request: InputRequest | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; answered: [] }>()

const store = useBusinessStore()
const form = reactive({
  allocatedCapital: '',
  riskValue: '',
  riskUnit: 'percent',
  profitValue: '',
  profitUnit: 'percent',
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
  },
)

function close(): void {
  emit('update:modelValue', false)
}

async function submit(): Promise<void> {
  const request = props.request
  error.value = ''
  if (!request) return
  if (!boundAccount.value) {
    error.value = '还没有主账户：请先到「交易账户资料」创建主账户，再回填本标的规划资金'
    return
  }
  if (!form.allocatedCapital.trim()) {
    error.value = '请填写本标的规划资金（从主账户可用资金中划出）'
    return
  }
  const declared: Record<string, Record<string, unknown>> = {
    plan: { allocated_capital: { value: form.allocatedCapital.trim() } },
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

  submitting.value = true
  try {
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
      error.value = '仍有待澄清项：请补齐后用同一条请求重试'
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
      <p v-else class="account-missing">
        还没有主账户：请先到「交易账户资料」创建主账户，再回来填写本标的规划资金。
      </p>
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

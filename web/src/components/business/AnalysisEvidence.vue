<script setup lang="ts">
/**
 * UI-06 分析依据 · DATA-05 快照展示。
 *
 * 只读该 Run 提交那一刻冻结的业务输入（GET /runs/{id}/investment-snapshot），
 * 绝不把当前资料回填成"本次分析依据"。旧的非业务 Run 明确报缺（404 snapshot_absent），
 * 显示空态而非伪装成空报告。
 */
import { computed, onMounted, ref, watch } from 'vue'

import { runs as runsApi } from '@/api'
import { ApiError } from '@/api/client'
import type { SnapshotView } from '@/types'

const props = defineProps<{
  runId: string | null
}>()

const loading = ref(false)
const absent = ref(false)
const notFound = ref(false)
const errorMessage = ref('')
const snapshot = ref<SnapshotView | null>(null)

const FIELD_LABELS: Record<string, string> = {
  total_capital: '总资金',
  available_capital: '可用资金',
  capital_basis: '资金口径',
  currency: '币种',
  as_of: '数据时点',
  symbol: '标的',
  market: '市场',
  asset_type: '资产类型',
  direction: '方向',
  plan_price: '计划价',
  plan_price_low: '计划价下限',
  plan_price_high: '计划价上限',
  target_price: '目标价',
  quantity: '数量',
  price: '成交价',
  fees: '费用',
  side: '成交方向',
  traded_at: '成交时间',
}

function labelOf(key: string): string {
  return FIELD_LABELS[key] ?? key
}

function displayValue(key: string, raw: unknown): string {
  if (raw === null || raw === undefined || raw === '') return '待补充'
  if (typeof raw === 'object') {
    const obj = raw as Record<string, unknown>
    const inner = obj.value ?? obj.raw ?? obj.text
    if (inner !== undefined && inner !== null && inner !== '') return String(inner)
    return '待补充'
  }
  if (key === 'direction') return raw === 'sell' ? '卖出' : '买入'
  return String(raw)
}

const valueRows = computed(() => {
  const values = snapshot.value?.values ?? {}
  return Object.entries(values).map(([key, value]) => ({
    key,
    label: labelOf(key),
    value: displayValue(key, value),
  }))
})

const accountSummary = computed(() => {
  const account = snapshot.value?.account
  if (!account || typeof account !== 'object') return null
  const { id, revision } = account as { id?: string; revision?: number }
  return { id: id ?? '', revision: revision ?? null }
})

const planSummary = computed(() => {
  const plan = snapshot.value?.plan
  if (!plan || typeof plan !== 'object') return null
  const { id, revision } = plan as { id?: string; revision?: number }
  return { id: id ?? '', revision: revision ?? null }
})

async function load(): Promise<void> {
  if (!props.runId) return
  loading.value = true
  absent.value = false
  notFound.value = false
  errorMessage.value = ''
  snapshot.value = null
  try {
    snapshot.value = await runsApi.investmentSnapshot(props.runId)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound.value = true
    }
    const detail = err instanceof ApiError ? err.detail : null
    if (detail && typeof detail === 'object' && 'code' in detail
      && (detail as { code?: string }).code === 'snapshot_absent') {
      absent.value = true
    }
    errorMessage.value = err instanceof Error ? err.message : '读取分析依据失败'
  } finally {
    loading.value = false
  }
}

watch(() => props.runId, () => load())
onMounted(load)
</script>

<template>
  <section class="analysis-evidence" aria-label="本次分析依据">
    <header class="evidence-head">
      <span>分析依据</span>
      <small v-if="snapshot?.created_at">提交于 {{ snapshot.created_at }}</small>
    </header>

    <div v-if="loading" class="evidence-state">加载分析依据…</div>

    <div v-else-if="absent" class="evidence-state evidence-state--warn" role="alert">
      该运行没有业务输入快照（非业务运行），不作回填。
    </div>

    <div v-else-if="notFound" class="evidence-state" role="alert">
      读取快照失败：{{ errorMessage }}
    </div>

    <div v-else-if="snapshot" class="evidence-body">
      <div class="evidence-refs">
        <div v-if="accountSummary" class="ref-chip">
          <span class="ref-label">账户</span>
          <code>{{ accountSummary.id.slice(0, 8) }}</code>
          <small v-if="accountSummary.revision">v{{ accountSummary.revision }}</small>
        </div>
        <div v-if="planSummary" class="ref-chip">
          <span class="ref-label">计划</span>
          <code>{{ planSummary.id.slice(0, 8) }}</code>
          <small v-if="planSummary.revision">v{{ planSummary.revision }}</small>
        </div>
        <div v-if="snapshot.use_case" class="ref-chip">
          <span class="ref-label">用途</span>
          <code>{{ snapshot.use_case }}</code>
        </div>
      </div>

      <table v-if="valueRows.length" class="evidence-values">
        <tbody>
          <tr v-for="row in valueRows" :key="row.key">
            <th scope="row">{{ row.label }}</th>
            <td :class="{ 'is-pending': row.value === '待补充' }">{{ row.value }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="evidence-empty">本次分析未采用可用业务字段。</p>
    </div>

    <div v-else class="evidence-state">无可用运行。</div>
  </section>
</template>

<style scoped>
.analysis-evidence { display: flex; flex-direction: column; gap: 12px; }
.evidence-head { display: flex; align-items: baseline; justify-content: space-between; }
.evidence-head > span { color: var(--accent); font-size: 10px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
.evidence-head > small { color: var(--muted); font-size: 11px; }
.evidence-state { color: var(--muted); font-size: 13px; padding: 8px 0; }
.evidence-state--warn { color: var(--warning); }
.evidence-refs { display: flex; flex-wrap: wrap; gap: 8px; }
.ref-chip { display: inline-flex; align-items: center; gap: 6px; padding: 4px 9px; border: 1px solid var(--line-strong); border-radius: 999px; font-size: 12px; }
.ref-label { color: var(--muted); }
.ref-chip code { font-family: var(--mono, monospace); }
.ref-chip small { color: var(--muted); }
.evidence-values { width: 100%; font-size: 13px; border-collapse: collapse; }
.evidence-values th, .evidence-values td { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: left; }
.evidence-values th { width: 40%; color: var(--muted); font-weight: 500; }
.evidence-values td.is-pending { color: var(--warning); }
.evidence-empty { color: var(--muted); font-size: 13px; }
</style>
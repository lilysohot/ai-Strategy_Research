<script setup lang="ts">
import { computed, ref } from 'vue'
import { superLink } from '../api/superLink'
import type { ApprovalDecisionValue, RunControlRecord } from '../types'
import { canSubmitApproval } from '../utils/approval'
import { redactSecrets } from '../utils/redact'

const props = defineProps<{ spaceId: string; record: RunControlRecord; disabled: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const confirm = ref('')
const replacement = ref('')
const scope = ref<ApprovalDecisionValue>('once')
const busy = ref(false)
const sent = ref(false)
const error = ref('')
const risk = computed(() => props.record.request.risk === 'high' ? 'high' : 'normal')
const text = (key: string) => redactSecrets(String(props.record.request[key] ?? ''))
async function decide(decision: ApprovalDecisionValue) {
  if (busy.value || props.disabled || !props.record.external_id) return
  if (decision !== 'reject' && !canSubmitApproval(risk.value, confirm.value)) return
  busy.value = true; error.value = ''
  try {
    await superLink.approve(props.spaceId, props.record.run_id, props.record.external_id, decision,
      decision === 'reject' ? replacement.value : undefined)
    sent.value = true
    emit('changed')
  } catch (e) { error.value = e instanceof Error ? e.message : '审批提交失败'; emit('changed') }
  finally { busy.value = false }
}
</script>

<template>
  <article class="approval" data-testid="sl-approval">
    <strong>等待审批：{{ text('tool_name') }}</strong>
    <p>运行 {{ record.run_id.slice(0, 8) }} <span v-if="record.request.agent_id">· 成员 {{ text('agent_id') }}</span> · {{ risk === 'high' ? '高风险' : '需确认' }}</p>
    <p>{{ text('reason') }}</p><pre>{{ text('target') }}<br>{{ text('preview') }}</pre>
    <el-input v-if="risk === 'high'" v-model="confirm" placeholder="输入 yes 以启用批准按钮" :disabled="busy || sent" />
    <el-input v-model="replacement" type="textarea" placeholder="拒绝时的替代指令（可选）" :disabled="busy || sent" />
    <div class="actions">
      <el-button type="danger" :disabled="disabled || busy || sent" @click="decide('reject')">拒绝此操作</el-button>
      <el-select v-model="scope" aria-label="授权范围" :disabled="disabled || busy || sent">
        <el-option label="仅此一次" value="once" />
        <el-option v-if="record.request.tool_name === 'bash'" label="本轮相同命令" value="session_bash" />
        <el-option label="本轮相同工具" value="session_all" />
      </el-select>
      <el-button type="primary" :disabled="disabled || busy || sent || !canSubmitApproval(risk, confirm)" @click="decide(scope)">批准操作</el-button>
    </div>
    <p v-if="sent" role="status">已提交，等待运行确认。实际结果以审批记录为准。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
  </article>
</template>

<style scoped>
.approval{padding:16px;border:1px solid var(--el-color-warning);border-radius:8px;margin:12px 0;overflow-wrap:anywhere}.approval p{font-size:13px}.approval pre{white-space:pre-wrap;max-height:220px;overflow:auto}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.actions .el-select{width:170px}.el-textarea{margin-top:12px}
</style>

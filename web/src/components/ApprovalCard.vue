<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { useRunStreamStore } from '@/stores/runs'
import type { ApprovalDecisionValue } from '@/types'
import { canSubmitApproval } from '@/utils/approval'
import { redactSecrets } from '@/utils/redact'

const runStream = useRunStreamStore()

const confirmText = ref('')
const replacement = ref('')
const submitting = ref(false)
const rejectBtn = ref<{ $el: HTMLButtonElement } | null>(null)

const request = computed(() => runStream.pendingApproval)
const canApprove = computed(() => {
  const req = request.value
  return !!req && !submitting.value && canSubmitApproval(req.risk, confirmText.value)
})

watch(
  request,
  async (req) => {
    confirmText.value = ''
    replacement.value = ''
    if (req) {
      await nextTick()
      rejectBtn.value?.$el.focus()
    }
  },
)

async function decide(decision: ApprovalDecisionValue): Promise<void> {
  const req = request.value
  if (!req || submitting.value) return
  if (decision !== 'reject' && !canApprove.value) return
  submitting.value = true
  try {
    await runStream.approve(
      req.approvalId,
      decision,
      decision === 'reject' ? replacement.value : undefined,
    )
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '审批提交失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section v-if="request" class="approval-card" data-testid="approval-dialog" aria-live="polite">
    <header class="approval-head">
      <div>
        <div class="approval-title">等待你决定：{{ redactSecrets(request.toolName) }}</div>
        <div class="approval-sub">Agent 已暂停在权限边界，提交结果以后才会继续。</div>
      </div>
      <el-tag size="small" :type="request.risk === 'high' ? 'danger' : 'warning'">
        {{ request.risk === 'high' ? '高风险' : '需确认' }}
      </el-tag>
    </header>

    <dl class="approval-facts">
      <div v-if="request.target">
        <dt>目标</dt>
        <dd><code data-testid="approval-target">{{ redactSecrets(request.target) }}</code></dd>
      </div>
      <div v-if="request.reason">
        <dt>原因</dt>
        <dd data-testid="approval-reason">{{ redactSecrets(request.reason) }}</dd>
      </div>
    </dl>

    <pre v-if="request.preview" class="approval-preview" data-testid="approval-preview">{{ redactSecrets(request.preview) }}</pre>

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      class="approval-warn"
      title="当前运行时不是操作系统级沙箱：获批的操作将以你的用户权限执行。"
    />

    <el-input
      v-if="request.risk === 'high'"
      v-model="confirmText"
      class="approval-confirm"
      placeholder="输入 yes 以启用批准按钮"
      data-testid="approval-confirm"
      @keydown.enter.prevent
    />

    <el-input
      v-model="replacement"
      class="approval-replacement"
      type="textarea"
      :rows="2"
      resize="none"
      placeholder="替代指令（可选）：拒绝时作为反馈告知模型该怎么做"
      data-testid="approval-replacement"
    />

    <div class="approval-actions">
      <el-button
        ref="rejectBtn"
        type="danger"
        :disabled="submitting"
        data-testid="approval-reject"
        @click="decide('reject')"
      >
        拒绝
      </el-button>
      <span class="approval-spacer" />
      <el-button :disabled="!canApprove || submitting" data-testid="approval-once" @click="decide('once')">
        允许一次
      </el-button>
      <el-button :disabled="!canApprove || submitting" data-testid="approval-session" @click="decide('session_all')">
        本次会话内允许
      </el-button>
      <el-button
        type="primary"
        :disabled="!canApprove || submitting"
        data-testid="approval-persist"
        @click="decide('persist')"
      >
        保存为永久规则
      </el-button>
    </div>
  </section>
</template>

<style scoped>
.approval-card {
  margin: 12px 14px 0;
  padding: 14px;
  border: 1px solid var(--warning);
  border-radius: 8px;
  background: color-mix(in srgb, var(--warning) 9%, var(--bg-raised));
}

.approval-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.approval-title {
  font-weight: 700;
  color: var(--text);
}

.approval-sub,
.approval-facts dt {
  color: var(--muted);
  font-size: 12px;
}

.approval-facts {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 0 10px;
}

.approval-facts div {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr);
  gap: 8px;
}

.approval-facts dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}

.approval-facts code {
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.06);
}

.approval-preview {
  max-height: 200px;
  overflow: auto;
  margin: 0 0 10px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #0d0e0b;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-all;
}

.approval-warn,
.approval-confirm,
.approval-replacement {
  margin-bottom: 10px;
}

.approval-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.approval-spacer {
  flex: 1;
}
</style>

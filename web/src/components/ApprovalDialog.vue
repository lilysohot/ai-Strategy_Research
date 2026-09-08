<script setup lang="ts">
/**
 * 人工审批弹窗（P3.2，§6.1）。
 *
 * 数据源是 run store 的 ``pendingApproval``（来自 ``approval_requested`` 事件），
 * 提交走真实 approve 路由；弹窗在 worker 回发 ``approval_resolved`` 时才消失
 * （store 负责），所以提交失败（409 竞态/断网）时用户可以重试。终端语义对齐：
 * 默认焦点在「拒绝」（终端默认 No）；高风险操作必须输入 ``yes`` 才能批准；
 * 拒绝可附替代指令（终端 ``[e]``），作为被拒调用的结果反馈给模型。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { useRunStreamStore } from '@/stores/runs'
import { canSubmitApproval } from '@/utils/approval'
import { redactSecrets } from '@/utils/redact'
import type { ApprovalDecisionValue } from '@/types'

const runStream = useRunStreamStore()

const confirmText = ref('')
const replacement = ref('')
const submitting = ref(false)
const rejectBtn = ref<{ $el: HTMLButtonElement } | null>(null)

// 每个新请求都重置输入；打开时把焦点放到「拒绝」上（对齐终端默认 No）。
watch(
  () => runStream.pendingApproval,
  async (req) => {
    confirmText.value = ''
    replacement.value = ''
    if (req) {
      await nextTick()
      rejectBtn.value?.$el.focus()
    }
  },
)

const request = computed(() => runStream.pendingApproval)
const canApprove = computed(() => {
  const req = request.value
  return !!req && !submitting.value && canSubmitApproval(req.risk, confirmText.value)
})

/** Submit a decision; high-risk guards here too (button is also disabled). */
async function decide(decision: ApprovalDecisionValue) {
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
  <el-dialog
    :model-value="!!request"
    width="560px"
    align-center
    data-testid="approval-dialog"
    :close-on-click-modal="false"
    :close-on-escape-key="false"
    :show-close="false"
  >
    <template #header>
      <div v-if="request" class="approval-header">
        <span class="approval-title">
          需要审批：{{ redactSecrets(request.toolName) }}
        </span>
        <el-tag size="small" :type="request.risk === 'high' ? 'danger' : 'warning'">
          {{ request.risk === 'high' ? '高风险' : '需确认' }}
        </el-tag>
      </div>
    </template>

    <div v-if="request" class="approval-body">
      <div v-if="request.target" class="approval-row">
        <span class="approval-label">目标</span>
        <code class="approval-target" data-testid="approval-target">
          {{ redactSecrets(request.target) }}
        </code>
      </div>
      <div v-if="request.reason" class="approval-row">
        <span class="approval-label">原因</span>
        <span data-testid="approval-reason">{{ redactSecrets(request.reason) }}</span>
      </div>
      <pre
        v-if="request.preview"
        class="approval-preview"
        data-testid="approval-preview"
      >{{ redactSecrets(request.preview) }}</pre>

      <!-- 安全约束（§6.1）：native runtime 不是 OS 沙箱，必须明示权限归属 -->
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
        <el-button
          :disabled="!canApprove || submitting"
          data-testid="approval-once"
          @click="decide('once')"
        >
          允许一次
        </el-button>
        <el-button
          :disabled="!canApprove || submitting"
          data-testid="approval-session"
          @click="decide('session_all')"
        >
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
    </div>
  </el-dialog>
</template>

<style scoped>
.approval-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.approval-title {
  font-weight: 600;
}

.approval-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
  align-items: baseline;
}

.approval-label {
  flex-shrink: 0;
  color: var(--el-text-color-secondary);
}

.approval-target {
  word-break: break-all;
  background: var(--el-fill-color-light);
  padding: 1px 6px;
  border-radius: 4px;
}

.approval-preview {
  margin: 0 0 10px;
  padding: 10px;
  background: #1e1e1e;
  color: #d4d4d4;
  border-radius: 8px;
  font-size: 12px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.approval-warn {
  margin-bottom: 10px;
}

.approval-confirm {
  margin-bottom: 10px;
}

.approval-replacement {
  margin-bottom: 12px;
}

.approval-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.approval-spacer {
  flex: 1;
}
</style>

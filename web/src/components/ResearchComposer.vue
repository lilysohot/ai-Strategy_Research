<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps<{
  disabled: boolean
  sending: boolean
  streaming: boolean
  stopping: boolean
  steering: boolean
}>()

const emit = defineEmits<{
  send: [message: string, files: File[]]
  stop: []
  steer: [message: string]
}>()

const input = ref('')
const steerInput = ref('')
const files = ref<File[]>([])
const filePicker = ref<HTMLInputElement | null>(null)
const textareaRef = ref()
const composing = ref(false)

const templates = [
  { label: '深度研究', text: '请进行深度研究：\n- 研究对象：\n- 时间范围：\n- 需要验证的假设：\n- 输出：结构化报告，包含风险与反方证据。' },
  { label: '报告产出', text: '请基于当前研究整理一份可下载报告，包含结论、关键证据、风险提示和后续跟踪清单。' },
  { label: '快速追问', text: '请针对上一轮结论继续追问：' },
]

function insertTemplate(text: string): void {
  input.value = input.value ? `${input.value}\n\n${text}` : text
  focus()
}

function onPickFiles(event: Event): void {
  const target = event.target as HTMLInputElement
  const picked = Array.from(target.files ?? [])
  if (!picked.length) return
  files.value = [...files.value, ...picked]
  target.value = ''
}

function removeFile(index: number): void {
  files.value = files.value.filter((_, i) => i !== index)
}

function formatSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function submit(): void {
  const text = input.value.trim()
  if (!text || props.disabled || props.sending || props.streaming) return
  emit('send', text, files.value)
  input.value = ''
  files.value = []
}

function submitSteer(): void {
  const text = steerInput.value.trim()
  if (!text || props.steering) return
  emit('steer', text)
  steerInput.value = ''
}

function onEnter(event: KeyboardEvent): void {
  if (composing.value || event.shiftKey || event.metaKey || event.ctrlKey) return
  event.preventDefault()
  submit()
}

async function focus(): Promise<void> {
  await nextTick()
  textareaRef.value?.focus?.()
}

function onDrop(event: DragEvent): void {
  const dropped = Array.from(event.dataTransfer?.files ?? [])
  if (!dropped.length) return
  files.value = [...files.value, ...dropped]
  ElMessage.success(`已添加 ${dropped.length} 个附件`)
}

defineExpose({ focus })
</script>

<template>
  <footer class="research-composer" @dragover.prevent @drop.prevent="onDrop">
    <div v-if="files.length" class="file-strip" aria-label="附件列表">
      <span v-for="(file, index) in files" :key="`${file.name}-${index}`" class="file-chip">
        <span class="file-name" :title="file.name">{{ file.name }}</span>
        <span class="file-size">{{ formatSize(file.size) }}</span>
        <button type="button" aria-label="移除附件" @click="removeFile(index)">×</button>
      </span>
    </div>

    <div v-if="streaming" class="steer-row">
      <el-input
        v-model="steerInput"
        size="small"
        placeholder="补充方向（下一工具边界生效）"
        :disabled="steering"
        data-testid="steer-input"
        @keydown.enter.prevent="submitSteer"
      />
      <el-button size="small" :loading="steering" :disabled="!steerInput.trim()" @click="submitSteer">
        补充方向
      </el-button>
    </div>

    <div class="template-row">
      <button
        v-for="item in templates"
        :key="item.label"
        type="button"
        class="template-chip"
        @click="insertTemplate(item.text)"
      >
        {{ item.label }}
      </button>
    </div>

    <div class="composer-box">
      <input
        ref="filePicker"
        type="file"
        multiple
        class="file-input"
        data-testid="file-input"
        @change="onPickFiles"
      />
      <el-button plain @click="filePicker?.click()">附件</el-button>
      <el-input
        ref="textareaRef"
        v-model="input"
        type="textarea"
        :rows="3"
        resize="none"
        placeholder="描述研究主题、时间范围、约束或继续追问..."
        data-testid="composer"
        @compositionstart="composing = true"
        @compositionend="composing = false"
        @keydown.enter="onEnter"
      />
      <el-button
        v-if="streaming"
        type="danger"
        plain
        :loading="stopping"
        data-testid="composer-stop"
        @click="emit('stop')"
      >
        停止
      </el-button>
      <el-button
        v-else
        type="primary"
        :loading="sending"
        :disabled="!input.trim() || disabled || sending"
        data-testid="send-btn"
        @click="submit"
      >
        发送
      </el-button>
    </div>
  </footer>
</template>

<style scoped>
.research-composer {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border-top: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg-app) 88%, black);
}

.file-strip,
.template-row,
.steer-row,
.composer-box {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-strip {
  flex-wrap: wrap;
}

.file-chip,
.template-chip {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg-raised);
  color: var(--text);
}

.file-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  max-width: 240px;
  padding: 4px 6px;
  font-size: 12px;
}

.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  color: var(--muted);
  flex: none;
}

.file-chip button {
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}

.template-chip {
  padding: 4px 8px;
  font-size: 12px;
  cursor: pointer;
}

.template-chip:hover {
  border-color: var(--accent);
}

.composer-box {
  align-items: flex-end;
}

.composer-box .el-textarea {
  flex: 1;
}

.file-input {
  display: none;
}

.steer-row .el-input {
  flex: 1;
}

@media (max-width: 640px) {
  .composer-box,
  .steer-row {
    align-items: stretch;
    flex-direction: column;
  }

  .composer-box .el-button,
  .steer-row .el-button {
    width: 100%;
  }
}
</style>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { RunMode } from '@/types'

const props = defineProps<{
  disabled: boolean
  sending: boolean
  streaming: boolean
  stopping: boolean
  steering: boolean
  sessionId: string | null
  teamAvailable: boolean
  teamUnavailableReason: string
  modeLoading: boolean
  activeMode?: RunMode
}>()

const emit = defineEmits<{
  send: [message: string, files: File[], mode: RunMode]
  stop: []
  steer: [message: string]
  refreshModes: []
}>()

const selectedMode = ref<RunMode>('single')
const displayedMode = computed(() => props.streaming ? props.activeMode ?? selectedMode.value : selectedMode.value)
const modeLocked = computed(() => props.disabled || props.sending || props.streaming || props.stopping)
const modeUnavailable = computed(() => selectedMode.value === 'team' && (!props.teamAvailable || props.modeLoading))
watch(() => props.sessionId, () => { selectedMode.value = 'single' })

function selectMode(event: Event): void {
  const mode = (event.target as HTMLSelectElement).value
  if (!modeLocked.value && (mode === 'single' || mode === 'team')) selectedMode.value = mode
}

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
  if (!text || modeLocked.value || modeUnavailable.value) return
  emit('send', text, [...files.value], selectedMode.value)
}

function clearSubmittedDraft(message: string, submittedFiles: File[]): void {
  // Keep edits made while the request was in flight, and retain everything on failure.
  if (input.value.trim() !== message || files.value.length !== submittedFiles.length
      || files.value.some((file, index) => file !== submittedFiles[index])) return
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

defineExpose({ focus, clearSubmittedDraft })
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
      <div v-if="displayedMode === 'team' && !streaming && (modeLoading || !teamAvailable)"
        class="mode-description" aria-live="polite" data-testid="mode-description">
        <span>{{ modeLoading ? '正在检查团队研究可用状态…' : teamUnavailableReason }}</span>
        <button type="button" class="mode-refresh" :disabled="modeLoading" @click="emit('refreshModes')">刷新状态</button>
      </div>
      <div class="composer-toolbar">
        <div class="composer-tools">
          <div class="mode-select-wrap" :title="streaming || stopping ? '本轮结束或停止完成后可切换模式' : '选择本轮研究模式'">
            <select
              class="mode-select" data-testid="mode-select" aria-label="本轮 Agent 模式"
              :value="displayedMode" :disabled="modeLocked" @change="selectMode"
            >
              <option value="single">单 Agent</option>
              <option value="team">团队研究{{ !teamAvailable && !streaming ? (modeLoading ? ' · 检查中' : ' · 暂未开放') : '' }}</option>
            </select>
            <svg class="mode-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
          </div>
          <button type="button" class="attach-button" @click="filePicker?.click()" aria-label="添加附件">
            <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7 11 5-5a2 2 0 0 1 3 3l-6 6a3.5 3.5 0 0 1-5-5l7-7" /></svg>
            <span>附件</span>
          </button>
        </div>
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
          :disabled="!input.trim() || modeLocked || modeUnavailable"
          data-testid="send-btn"
          @click="submit"
        >
          发送
        </el-button>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.mode-select-wrap { position: relative; min-width: 0; }
.mode-select { appearance: none; max-width: 100%; height: 32px; padding: 0 28px 0 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg-raised); color: var(--text); font: inherit; font-size: 12px; cursor: pointer; }
.mode-select:hover:not(:disabled) { border-color: var(--accent); }
.mode-select:focus-visible, .attach-button:focus-visible, .mode-refresh:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.mode-select:disabled { cursor: not-allowed; opacity: .65; }
.mode-chevron { position: absolute; width: 14px; height: 14px; right: 8px; top: 9px; fill: none; stroke: var(--muted); stroke-width: 1.5; pointer-events: none; }
.mode-description { padding: 0 12px 8px; font-size: 12px; color: var(--muted); line-height: 1.6; }
.mode-refresh { border: 0; background: transparent; color: var(--accent); font-size: 12px; cursor: pointer; padding: 0 6px; }

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
.steer-row {
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
  padding: 3px 6px;
  border-color: transparent;
  background: transparent;
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
}

.template-chip:hover {
  border-color: var(--accent);
}

.composer-box {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--bg-raised);
  overflow: hidden;
  transition: border-color .15s;
}

.composer-box:focus-within { border-color: var(--accent); }
.composer-box :deep(.el-textarea__inner) {
  box-shadow: none;
  background: transparent;
  padding: 12px;
  min-height: 84px !important;
}
.composer-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px; }
.composer-tools { display: flex; align-items: center; gap: 6px; min-width: 0; }
.composer-toolbar > .el-button { flex: none; min-width: 64px; margin: 0; }
.attach-button { display: inline-flex; align-items: center; gap: 3px; height: 32px; padding: 0 6px; border: 0; border-radius: 6px; background: transparent; color: var(--muted); cursor: pointer; font-size: 12px; }
.attach-button:hover { color: var(--text); background: var(--bg-app); }
.attach-button svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; }

.file-input {
  display: none;
}

.steer-row .el-input {
  flex: 1;
}

@media (max-width: 640px) {
  .steer-row {
    align-items: stretch;
    flex-direction: column;
  }

  .steer-row .el-button {
    width: 100%;
  }
  .attach-button span { display: none; }
}
</style>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { artifacts as artifactsApi } from '@/api'
import { ApiError } from '@/api/client'
import type { Artifact, ArtifactPreview, RunStatus } from '@/types'
import { renderMarkdown } from '@/utils/markdown'
import { previewRenderMode } from '@/utils/preview'

const props = defineProps<{
  runId: string | null
  title: string
  answer: string
  status: RunStatus | 'idle'
  fullScreen: boolean
}>()

const emit = defineEmits<{ toggleFullScreen: [] }>()

const tab = ref<'conclusion' | 'artifacts' | 'execution'>('conclusion')
const items = ref<Artifact[]>([])
const loading = ref(false)
const errorMsg = ref('')
const selected = ref<string | null>(null)
const preview = ref<ArtifactPreview | null>(null)
const previewLoading = ref(false)
const downloading = ref<string | null>(null)

const terminal = computed(() =>
  !!props.runId &&
    (props.status === 'completed' ||
      props.status === 'failed' ||
      props.status === 'stopped' ||
      props.status === 'idle'),
)

const selectedArtifact = computed(() =>
  items.value.find((a) => a.rel_path === selected.value) ?? null,
)

const previewMode = computed(() => {
  if (!selected.value || !preview.value) return null
  return previewRenderMode(selected.value, preview.value.kind)
})

const answerHtml = computed(() => renderMarkdown(props.answer || ''))
const previewHtml = computed(() =>
  previewMode.value === 'markdown' ? renderMarkdown(preview.value?.content ?? '') : '',
)

const sourceLabel = computed(() => {
  if (selectedArtifact.value) return '输出文件'
  if (props.runId) return '本次回答'
  return '尚未选择运行'
})

function basename(path: string): string {
  return path.split('/').pop() || path
}

function formatSize(n: number): string {
  if (!n || n < 0) return '-'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function isReadableArtifact(item: Artifact): boolean {
  return /\.(md|markdown|txt|json|csv|log|html?|png|jpe?g|gif|webp)$/i.test(item.rel_path)
}

async function load(): Promise<void> {
  if (!props.runId || !terminal.value) {
    items.value = []
    selected.value = null
    preview.value = null
    errorMsg.value = ''
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await artifactsApi.list(props.runId)
    items.value = res.artifacts
    const preferred =
      res.artifacts.find((a) => /\.(md|markdown)$/i.test(a.rel_path)) ??
      res.artifacts.find((a) => /\.(txt|html?)$/i.test(a.rel_path)) ??
      res.artifacts.find(isReadableArtifact) ??
      null
    if (preferred) await selectArtifact(preferred)
  } catch (err) {
    items.value = []
    selected.value = null
    preview.value = null
    errorMsg.value =
      err instanceof ApiError && err.status === 404
        ? '该运行暂无可读取产物'
        : err instanceof Error
          ? err.message
          : '加载产物失败'
  } finally {
    loading.value = false
  }
}

async function selectArtifact(item: Artifact): Promise<void> {
  if (!props.runId) return
  selected.value = item.rel_path
  preview.value = null
  previewLoading.value = true
  try {
    preview.value = await artifactsApi.preview(props.runId, item.rel_path)
    tab.value = 'conclusion'
  } catch (err) {
    selected.value = null
    ElMessage.error(err instanceof Error ? err.message : '预览失败')
  } finally {
    previewLoading.value = false
  }
}

async function download(item: Artifact): Promise<void> {
  if (!props.runId) return
  downloading.value = item.rel_path
  try {
    await artifactsApi.download(props.runId, item.rel_path)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '下载失败')
  } finally {
    downloading.value = null
  }
}

watch(
  () => [props.runId, props.status],
  () => {
    void load()
  },
  { immediate: true },
)

defineExpose({ load })
</script>

<template>
  <aside class="research-canvas" :class="{ fullscreen: fullScreen }" aria-label="研究画布">
    <header class="canvas-head">
      <div class="canvas-title">
        <span>{{ selectedArtifact ? basename(selectedArtifact.rel_path) : title }}</span>
        <small>{{ sourceLabel }}</small>
      </div>
      <div class="canvas-actions">
        <el-button size="small" plain :loading="loading" :disabled="!runId || !terminal" @click="load">
          刷新
        </el-button>
        <el-button size="small" plain @click="emit('toggleFullScreen')">
          {{ fullScreen ? '退出全屏' : '专注阅读' }}
        </el-button>
      </div>
    </header>

    <el-tabs v-model="tab" class="canvas-tabs">
      <el-tab-pane label="结论" name="conclusion">
        <article v-loading="previewLoading" class="canvas-reader">
          <template v-if="selectedArtifact && preview">
            <img
              v-if="previewMode === 'image'"
              class="canvas-image"
              :src="preview.content"
              alt="产物预览"
            />
            <div v-else-if="previewMode === 'markdown'" class="markdown-body" v-html="previewHtml" />
            <pre v-else-if="previewMode === 'code'" class="code-body">{{ preview.content }}</pre>
            <div v-else class="canvas-empty">该产物不支持预览，请下载查看。</div>
            <div v-if="preview.truncated" class="canvas-note">内容已截断，完整内容请下载。</div>
          </template>
          <div v-else-if="answer" class="markdown-body" v-html="answerHtml" />
          <div v-else class="canvas-empty">
            运行的回答或 Markdown 产物会显示在这里。
          </div>
        </article>
      </el-tab-pane>

      <el-tab-pane label="产物" name="artifacts">
        <div class="artifact-pane">
          <el-alert
            v-if="errorMsg"
            :title="errorMsg"
            type="warning"
            show-icon
            :closable="false"
            class="canvas-alert"
          />
          <el-empty v-if="!loading && !items.length" description="暂无产物" :image-size="64" />
          <ul v-else v-loading="loading" class="artifact-list">
            <li v-for="item in items" :key="item.rel_path" class="artifact-row">
              <button type="button" class="artifact-main" @click="selectArtifact(item)">
                <span class="artifact-name">{{ basename(item.rel_path) }}</span>
                <span class="artifact-meta">{{ formatSize(item.size) }}</span>
              </button>
              <el-button
                size="small"
                text
                type="primary"
                :loading="downloading === item.rel_path"
                @click="download(item)"
              >
                下载
              </el-button>
            </li>
          </ul>
        </div>
      </el-tab-pane>

      <el-tab-pane label="执行" name="execution">
        <div class="execution-summary">
          <dl>
            <div>
              <dt>Run</dt>
              <dd><code>{{ runId || '-' }}</code></dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>{{ status }}</dd>
            </div>
            <div>
              <dt>内容来源</dt>
              <dd>{{ sourceLabel }}</dd>
            </div>
          </dl>
        </div>
      </el-tab-pane>
    </el-tabs>
  </aside>
</template>

<style scoped>
.research-canvas {
  width: clamp(380px, 44vw, 720px);
  min-width: 360px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #141611;
  border-left: 1px solid var(--line);
  color: var(--text);
}

.research-canvas.fullscreen {
  position: fixed;
  inset: 0 0 31px 0;
  z-index: 40;
  width: auto;
  min-width: 0;
}

.canvas-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 58px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
}

.canvas-title {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.canvas-title span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: 'Songti SC', 'Source Han Serif SC', serif;
  font-size: 18px;
  font-weight: 700;
}

.canvas-title small,
.canvas-note,
.artifact-meta {
  color: var(--muted);
  font-size: 12px;
}

.canvas-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
}

.canvas-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.canvas-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.canvas-tabs :deep(.el-tabs__header) {
  padding: 0 16px;
  margin: 0;
  border-bottom-color: var(--line);
}

.canvas-reader {
  max-width: 760px;
  margin: 0 auto;
  padding: 26px 28px 44px;
}

.markdown-body {
  color: var(--text);
  font-size: 15px;
  line-height: 1.82;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  font-family: 'Songti SC', 'Source Han Serif SC', serif;
  line-height: 1.35;
}

.markdown-body :deep(a) {
  color: var(--accent);
}

.markdown-body :deep(pre),
.code-body {
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: #0d0e0b;
  color: var(--text);
}

.code-body {
  white-space: pre-wrap;
  line-height: 1.55;
}

.canvas-image {
  max-width: 100%;
  border-radius: 6px;
}

.canvas-empty,
.execution-summary {
  padding: 28px;
  color: var(--muted);
  text-align: center;
}

.canvas-alert {
  margin-bottom: 10px;
}

.artifact-pane {
  padding: 16px;
}

.artifact-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.artifact-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg-raised);
}

.artifact-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: 0;
  padding: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.artifact-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.execution-summary dl {
  margin: 0;
  text-align: left;
}

.execution-summary div {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 10px;
  margin-bottom: 10px;
}

.execution-summary dt {
  color: var(--muted);
}

.execution-summary dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}

@media (max-width: 1023px) {
  .research-canvas {
    position: absolute;
    inset: 0 0 31px auto;
    z-index: 25;
    width: min(92vw, 640px);
    transform: translateX(100%);
    transition: transform 0.2s ease;
  }

  .research-canvas.fullscreen {
    transform: translateX(0);
  }
}
</style>

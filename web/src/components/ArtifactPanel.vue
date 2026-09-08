<script setup lang="ts">
/**
 * Artifact list + download (T3.6).
 *
 * The list comes from ``GET /api/runs/{run_id}/artifacts`` (server-authoritative
 * ``rel_path``); downloading goes through the authenticated blob path in
 * ``api/artifacts.download`` because a plain anchor download cannot carry the
 * Authorization header every /api route requires.
 *
 * The panel is driven by the active run id and exposes a ``load`` so a stop
 * (or a terminal stream event) can pull the final artifact set.
 */

import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { ApiError } from '@/api/client'
import { artifacts as artifactsApi } from '@/api'
import type { Artifact, ArtifactPreview } from '@/types'
import { renderMarkdown } from '@/utils/markdown'
import { previewRenderMode } from '@/utils/preview'

const props = defineProps<{ runId: string | null }>()

const items = ref<Artifact[]>([])
const loading = ref(false)
const errorMsg = ref('')
const downloading = ref<string | null>(null)

// ── 预览（P2.3 §5.4）：单文件展开，rel_path 透传服务端解析 ──
const previewRelPath = ref<string | null>(null)
const previewData = ref<ArtifactPreview | null>(null)
const previewLoading = ref(false)
const previewError = ref('')

const previewMode = computed(() => {
  if (!previewRelPath.value || !previewData.value) return null
  return previewRenderMode(previewRelPath.value, previewData.value.kind)
})

const previewMdHtml = computed(() => {
  if (previewMode.value !== 'markdown') return ''
  return renderMarkdown(previewData.value?.content ?? '')
})

async function onPreview(a: Artifact) {
  // 同一文件再点一次 = 收起。
  if (previewRelPath.value === a.rel_path) {
    previewRelPath.value = null
    previewData.value = null
    return
  }
  if (!props.runId) return
  previewRelPath.value = a.rel_path
  previewData.value = null
  previewError.value = ''
  previewLoading.value = true
  try {
    previewData.value = await artifactsApi.preview(props.runId, a.rel_path)
  } catch (err) {
    previewRelPath.value = null
    previewError.value =
      err instanceof ApiError && err.status === 404
        ? '文件不存在或无权限预览'
        : err instanceof ApiError
          ? err.message
          : '预览失败'
  } finally {
    previewLoading.value = false
  }
}

async function load() {
  if (!props.runId) {
    items.value = []
    errorMsg.value = ''
    return
  }
  loading.value = true
  errorMsg.value = ''
  previewRelPath.value = null
  previewData.value = null
  try {
    const res = await artifactsApi.list(props.runId)
    items.value = res.artifacts
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      errorMsg.value = '该运行不存在或无权限查看'
    } else {
      errorMsg.value = err instanceof ApiError ? err.message : '加载产物失败'
    }
    items.value = []
  } finally {
    loading.value = false
  }
}

async function onDownload(a: Artifact) {
  if (!props.runId) return
  downloading.value = a.rel_path
  try {
    await artifactsApi.download(props.runId, a.rel_path)
  } catch (err) {
    // 404 = not owned / gone; anything else is a transport or server error.
    const msg =
      err instanceof ApiError && err.status === 404
        ? '文件不存在或无权限下载'
        : err instanceof ApiError
          ? err.message
          : '下载失败'
    ElMessage.error(msg)
  } finally {
    downloading.value = null
  }
}

function formatSize(n: number): string {
  if (!n || n < 0) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function basename(p: string): string {
  return p.split('/').pop() || p
}

// Reload when the active run changes; the parent also calls refresh() on stop.
watch(() => props.runId, load, { immediate: true })

defineExpose({ load })
</script>

<template>
  <div class="artifacts">
    <div class="artifacts__bar">
      <span class="artifacts__count">共 {{ items.length }} 个产物</span>
      <el-button size="small" :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="errorMsg"
      :title="errorMsg"
      type="error"
      show-icon
      :closable="false"
      class="artifacts__error"
    />

    <el-empty
      v-else-if="!loading && !items.length"
      description="暂无产物（运行完成后产物会出现在这里）"
      :image-size="60"
    />

    <ul v-else v-loading="loading" class="artifacts__list">
      <li v-for="a in items" :key="a.rel_path" class="artifacts__item">
        <div class="artifacts__row">
          <div class="artifacts__main">
            <span class="artifacts__name" :title="a.rel_path">{{ basename(a.rel_path) }}</span>
            <span class="artifacts__meta">
              {{ formatSize(a.size) }}
              <template v-if="a.created_at"> · {{ a.created_at.slice(0, 19).replace('T', ' ') }}</template>
            </span>
            <span class="artifacts__sha" :title="a.sha256">{{ a.sha256?.slice(0, 12) }}</span>
          </div>
          <div class="artifacts__actions">
            <el-button
              size="small"
              text
              type="primary"
              data-testid="preview-btn"
              @click="onPreview(a)"
            >
              {{ previewRelPath === a.rel_path ? '收起' : '预览' }}
            </el-button>
            <el-button
              size="small"
              text
              type="primary"
              :loading="downloading === a.rel_path"
              @click="onDownload(a)"
            >
              下载
            </el-button>
          </div>
        </div>
        <!-- 只读预览区（§5.4）：markdown 走脱敏渲染，文本 pre，图片 data URL -->
        <div
          v-if="previewRelPath === a.rel_path"
          v-loading="previewLoading"
          class="artifacts__preview"
        >
          <el-alert
            v-if="previewError"
            :title="previewError"
            type="error"
            show-icon
            :closable="false"
          />
          <template v-else-if="previewData">
            <img
              v-if="previewMode === 'image'"
              class="artifacts__img"
              :src="previewData.content"
              alt="预览"
            />
            <!-- renderMarkdown 输出已经脱敏（同 ChatView 的用法） -->
            <div
              v-else-if="previewMode === 'markdown'"
              class="artifacts__md"
              v-html="previewMdHtml"
            />
            <pre v-else-if="previewMode === 'code'" class="artifacts__code">{{ previewData.content }}</pre>
            <div v-else class="artifacts__hint">不支持预览，请下载查看</div>
            <div v-if="previewData.truncated" class="artifacts__hint">
              内容已截断，完整内容请下载查看
            </div>
          </template>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.artifacts {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.artifacts__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.artifacts__count {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.artifacts__error {
  margin-bottom: 10px;
}

.artifacts__list {
  list-style: none;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  max-height: 62vh;
}

.artifacts__item {
  padding: 8px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  margin-bottom: 6px;
}

.artifacts__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.artifacts__actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.artifacts__preview {
  margin-top: 8px;
  min-height: 24px;
}

.artifacts__img {
  max-width: 100%;
  max-height: 320px;
  border-radius: 4px;
}

.artifacts__code {
  margin: 0;
  padding: 10px;
  max-height: 360px;
  overflow: auto;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre;
}

.artifacts__md {
  max-height: 360px;
  overflow: auto;
  font-size: 13px;
  line-height: 1.6;
}

.artifacts__hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.artifacts__main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.artifacts__name {
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.artifacts__meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.artifacts__sha {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
}
</style>

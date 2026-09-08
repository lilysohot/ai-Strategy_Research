<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { useSessionsStore } from '@/stores/sessions'

const sessions = useSessionsStore()
const newTitle = ref('')
const creating = ref(false)

onMounted(async () => {
  try {
    await sessions.loadList()
  } catch {
    // loadList already stashed the message into store.error; surface it once.
    ElMessage.error(sessions.error ?? '加载会话失败')
  }
})

async function onNew() {
  creating.value = true
  try {
    const title = newTitle.value.trim() || undefined
    const created = await sessions.create(title)
    newTitle.value = ''
    ElMessage.success('已新建会话')
    // 选中后由父视图接管 runStream 订阅
    await sessions.select(created.id)
  } catch (err) {
    const msg = err instanceof Error ? err.message : '新建会话失败'
    ElMessage.error(msg)
  } finally {
    creating.value = false
  }
}

async function onSelect(id: string) {
  try {
    await sessions.select(id)
  } catch (err) {
    const msg = err instanceof Error ? err.message : '切换会话失败'
    ElMessage.error(msg)
  }
}

async function onDelete(id: string, title: string | null) {
  try {
    await ElMessageBox.confirm(
      `确定删除会话「${title || '未命名'}」？此操作不可恢复。`,
      '删除会话',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await sessions.remove(id)
    ElMessage.success('已删除')
  } catch (err) {
    const msg = err instanceof Error ? err.message : '删除失败'
    ElMessage.error(msg)
  }
}
</script>

<template>
  <aside class="session-list">
    <div class="new-row">
      <el-input
        v-model="newTitle"
        placeholder="新会话标题（可选）"
        size="small"
        data-testid="new-session-title"
        @keyup.enter="onNew"
      />
      <el-button
        type="primary"
        size="small"
        :loading="creating"
        :disabled="creating"
        data-testid="new-session"
        @click="onNew"
      >
        新建
      </el-button>
    </div>

    <el-alert
      v-if="sessions.error"
      :title="sessions.error"
      type="error"
      show-icon
      :closable="false"
      class="list-error"
    />

    <div v-if="sessions.loadingList" class="loading">加载中…</div>

    <ul v-else class="items">
      <li
        v-for="s in sessions.list"
        :key="s.id"
        class="item"
        :class="{ active: s.id === sessions.activeId }"
        data-testid="session-item"
        @click="onSelect(s.id)"
      >
        <div class="item-main">
          <span class="item-title">{{ s.title || '未命名会话' }}</span>
          <span class="item-meta">
            {{ s.turn_count ?? 0 }} 条 · {{ (s.updated_at || s.created_at || '').slice(0, 10) }}
          </span>
        </div>
        <el-button
          class="del-btn"
          size="small"
          text
          type="danger"
          data-testid="delete-session"
          @click.stop="onDelete(s.id, s.title)"
        >
          删除
        </el-button>
      </li>
      <li v-if="!sessions.list.length" class="empty">还没有会话，点击「新建」开始</li>
    </ul>
  </aside>
</template>

<style scoped>
.session-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  border-right: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
  width: 240px;
  flex-shrink: 0;
}

.new-row {
  display: flex;
  gap: 6px;
  padding: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.list-error {
  margin: 8px 12px 0;
}

.loading {
  padding: 24px;
  text-align: center;
  color: var(--el-text-color-secondary);
}

.items {
  list-style: none;
  margin: 0;
  padding: 8px;
  overflow-y: auto;
  flex: 1;
}

.item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
}

.item:hover {
  background: var(--el-fill-color-light);
}

.item.active {
  background: var(--el-color-primary-light-9);
  outline: 1px solid var(--el-color-primary-light-7);
}

.item-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.item-title {
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.del-btn {
  opacity: 0;
  transition: opacity 0.15s;
}

.item:hover .del-btn {
  opacity: 1;
}

.empty {
  padding: 24px 12px;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

/* 移动端：列表收窄 */
@media (max-width: 768px) {
  .session-list {
    width: 180px;
  }
}
</style>

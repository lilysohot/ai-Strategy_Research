<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useSessionsStore } from '@/stores/sessions'

const emit = defineEmits<{ selected: []; created: [] }>()

const auth = useAuthStore()
const router = useRouter()
const sessions = useSessionsStore()

const creating = ref(false)
const filter = ref('')

const visibleSessions = computed(() => {
  const q = filter.value.trim().toLowerCase()
  if (!q) return sessions.list
  return sessions.list.filter((s) => (s.title || '未命名研究').toLowerCase().includes(q))
})

function formatDate(value: string | null): string {
  if (!value) return '暂无活动'
  return value.slice(0, 10)
}

async function onNew(): Promise<void> {
  if (creating.value) return
  creating.value = true
  try {
    const created = await sessions.create()
    await sessions.select(created.id)
    ElMessage.success('已新建研究')
    emit('created')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '新建研究失败')
  } finally {
    creating.value = false
  }
}

async function onSelect(id: string): Promise<void> {
  try {
    await sessions.select(id)
    emit('selected')
  } catch (err) {
    const msg =
      err instanceof ApiError && err.status === 404
        ? '研究不可用'
        : err instanceof Error
          ? err.message
          : '打开研究失败'
    ElMessage.error(msg)
  }
}

async function onDelete(id: string, title: string | null): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定移除研究「${title || '未命名研究'}」？此操作会在当前视图移除研究。`,
      '移除研究',
      { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  try {
    await sessions.remove(id)
    ElMessage.success('已移除研究')
  } catch (err) {
    const msg =
      err instanceof ApiError && err.status === 404
        ? '研究不可用'
        : err instanceof Error
          ? err.message
          : '移除失败'
    ElMessage.error(msg)
  }
}

async function goModels(): Promise<void> {
  await router.push({ name: 'models' })
}

async function onLogout(): Promise<void> {
  await auth.logout()
  await router.push({ name: 'login' })
}

onMounted(async () => {
  try {
    await sessions.loadList()
  } catch {
    ElMessage.error(sessions.error ?? '加载研究列表失败')
  }
})
</script>

<template>
  <aside class="research-rail" aria-label="研究导航">
    <header class="rail-head">
      <div>
        <div class="brand">投研 Agent</div>
        <div class="brand-sub">研究工作台</div>
      </div>
      <el-button
        type="primary"
        size="small"
        :loading="creating"
        data-testid="new-session"
        @click="onNew"
      >
        新建研究
      </el-button>
    </header>

    <div class="rail-search">
      <el-input
        v-model="filter"
        size="small"
        clearable
        placeholder="筛选已加载研究"
        data-testid="session-filter"
      />
    </div>

    <el-alert
      v-if="sessions.error"
      :title="sessions.error"
      type="error"
      show-icon
      :closable="false"
      class="rail-error"
    />

    <div class="rail-section">
      <span>最近</span>
      <span>{{ visibleSessions.length }}</span>
    </div>

    <div v-if="sessions.loadingList" class="rail-loading">加载中...</div>
    <nav v-else class="research-list" aria-label="研究列表">
      <button
        v-for="s in visibleSessions"
        :key="s.id"
        type="button"
        class="research-item"
        :class="{ active: s.id === sessions.activeId }"
        data-testid="session-item"
        @click="onSelect(s.id)"
      >
        <span class="item-title">{{ s.title || '未命名研究' }}</span>
        <span class="item-meta">
          {{ s.turn_count ?? 0 }} 条 · {{ formatDate(s.updated_at || s.created_at) }}
        </span>
        <el-button
          class="item-delete"
          text
          size="small"
          type="danger"
          data-testid="delete-session"
          @click.stop="onDelete(s.id, s.title)"
        >
          移除
        </el-button>
      </button>
      <div v-if="!visibleSessions.length" class="rail-empty">
        {{ filter ? '没有匹配的已加载研究' : '还没有研究' }}
      </div>
    </nav>

    <footer class="rail-account">
      <el-dropdown trigger="click">
        <button type="button" class="account-button">
          <span class="account-avatar">{{ auth.user?.username?.slice(0, 1).toUpperCase() || 'U' }}</span>
          <span class="account-text">
            <span>{{ auth.user?.username || '账户' }}</span>
            <small>模型与连接</small>
          </span>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="goModels">模型与连接</el-dropdown-item>
            <el-dropdown-item divided @click="onLogout">退出</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </footer>
  </aside>
</template>

<style scoped>
.research-rail {
  width: 252px;
  min-width: 252px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-rail);
  border-right: 1px solid var(--line);
  color: var(--text);
}

.rail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 18px 14px 14px;
  border-bottom: 1px solid var(--line);
}

.brand {
  font-weight: 700;
  letter-spacing: 0;
}

.brand-sub,
.rail-section,
.item-meta,
.rail-empty,
.rail-loading,
.account-text small {
  color: var(--muted);
  font-size: 12px;
}

.rail-search {
  padding: 12px 14px 8px;
}

.rail-error {
  margin: 8px 14px;
}

.rail-section {
  display: flex;
  justify-content: space-between;
  padding: 8px 14px;
}

.research-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 8px 12px;
}

.research-item {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 100%;
  min-height: 68px;
  gap: 4px;
  padding: 10px 36px 10px 10px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.research-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.research-item.active {
  border-color: color-mix(in srgb, var(--accent) 60%, transparent);
  background: color-mix(in srgb, var(--accent) 13%, transparent);
}

.item-title {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 600;
}

.item-delete {
  position: absolute;
  right: 4px;
  top: 8px;
  opacity: 0;
}

.research-item:hover .item-delete,
.research-item:focus-visible .item-delete {
  opacity: 1;
}

.rail-empty,
.rail-loading {
  padding: 24px 12px;
  text-align: center;
}

.rail-account {
  padding: 12px;
  border-top: 1px solid var(--line);
}

.account-button {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--bg-raised);
  color: var(--text);
  cursor: pointer;
}

.account-avatar {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--accent);
  color: #11120e;
  font-weight: 700;
}

.account-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  text-align: left;
}

.account-text span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1279px) {
  .research-rail {
    width: 232px;
    min-width: 232px;
  }
}
</style>

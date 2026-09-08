<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import DisclaimerBar from '@/components/DisclaimerBar.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const confirm = ref('')
const submitting = ref(false)
const errorMsg = ref<string | null>(null)

// 423 lockout 本地倒计时
const lockSeconds = ref(0)
let lockTimer: ReturnType<typeof setInterval> | null = null

const lockText = computed(() =>
  lockSeconds.value > 0 ? `账号已锁定，请 ${lockSeconds.value}s 后重试` : '',
)

function startLockCountdown(seconds: number) {
  lockSeconds.value = seconds
  if (lockTimer) clearInterval(lockTimer)
  lockTimer = setInterval(() => {
    lockSeconds.value -= 1
    if (lockSeconds.value <= 0 && lockTimer) {
      clearInterval(lockTimer)
      lockTimer = null
    }
  }, 1000)
}

onUnmounted(() => {
  if (lockTimer) clearInterval(lockTimer)
})

// 前端镜像后端校验规则（server/security.py: validate_password_strength / auth.py 长度约束）
const usernameError = computed(() => {
  const v = username.value.trim()
  if (!v) return ''
  if (v.length < 3 || v.length > 64) return '用户名需 3-64 个字符'
  if (v.includes('/') || !/^[\x20-\x7e]+$/.test(v)) return '用户名不可含 / 或不可打印字符'
  return ''
})

const passwordError = computed(() => {
  const v = password.value
  if (!v) return ''
  if (v.length < 8) return '密码至少 8 位'
  if (!/[A-Za-z]/.test(v)) return '密码需包含字母'
  if (!/[0-9]/.test(v)) return '密码需包含数字'
  return ''
})

const confirmError = computed(() => {
  if (mode.value === 'login') return ''
  if (!confirm.value) return ''
  if (confirm.value !== password.value) return '两次输入的密码不一致'
  return ''
})

const canSubmit = computed(
  () =>
    !!username.value.trim() &&
    !!password.value &&
    !usernameError.value &&
    !passwordError.value &&
    !confirmError.value &&
    lockSeconds.value === 0 &&
    !submitting.value,
)

function parseLockSeconds(msg: string): number | null {
  // 后端 423 错误形如 "账号已锁定，请 30s 后重试"
  const m = /(\d+)\s*s/.exec(msg)
  return m ? parseInt(m[1], 10) : null
}

async function onSubmit() {
  errorMsg.value = null
  if (!canSubmit.value) return
  submitting.value = true
  try {
    const name = username.value.trim()
    if (mode.value === 'login') {
      await auth.login(name, password.value)
      ElMessage.success('登录成功')
      const redirect = (router.currentRoute.value.query.redirect as string) || '/'
      router.replace(redirect)
    } else {
      await auth.register(name, password.value)
      ElMessage.success('注册成功，正在登录…')
      // 注册成功后自动登录，保持流程连贯
      await auth.login(name, password.value)
      const redirect = (router.currentRoute.value.query.redirect as string) || '/'
      router.replace(redirect)
    }
  } catch (err) {
    const code = (err as { code?: number }).code ?? 0
    const msg = (err as { message?: string }).message ?? '请求失败，请稍后重试'

    if (code === 423) {
      const secs = parseLockSeconds(msg)
      if (secs) startLockCountdown(secs)
      errorMsg.value = msg
    } else if (code === 401) {
      errorMsg.value = mode.value === 'login' ? '用户名或密码错误' : msg
    } else if (code === 409) {
      errorMsg.value = '该用户名已被占用，请更换或直接登录'
      mode.value = 'login'
    } else if (code === 400) {
      errorMsg.value = msg
    } else {
      errorMsg.value = msg || '网络异常，请检查连接后重试'
    }
  } finally {
    submitting.value = false
  }
}

function toggleMode() {
  errorMsg.value = null
  confirm.value = ''
  mode.value = mode.value === 'login' ? 'register' : 'login'
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card" shadow="always">
      <h1 class="title">{{ mode === 'login' ? '登录' : '注册' }}</h1>
      <p class="subtitle">FrontierAgent 私有部署控制台</p>

      <el-alert
        v-if="errorMsg"
        :title="errorMsg"
        type="error"
        show-icon
        :closable="false"
        class="error-alert"
      />
      <el-alert
        v-if="lockText"
        :title="lockText"
        type="warning"
        show-icon
        :closable="false"
        class="error-alert"
      />

      <el-form @submit.prevent="onSubmit" label-position="top">
        <el-form-item :error="usernameError || undefined">
          <el-input
            v-model="username"
            placeholder="用户名（3-64 个字符）"
            :prefix-icon="'User'"
            autocomplete="username"
            data-testid="username"
            @input="errorMsg = null"
          />
        </el-form-item>

        <el-form-item :error="passwordError || undefined">
          <el-input
            v-model="password"
            type="password"
            placeholder="密码（至少 8 位，含字母与数字）"
            :prefix-icon="'Lock'"
            show-password
            :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
            data-testid="password"
            @input="errorMsg = null"
            @keyup.enter="onSubmit"
          />
        </el-form-item>

        <el-form-item v-if="mode === 'register'" :error="confirmError || undefined">
          <el-input
            v-model="confirm"
            type="password"
            placeholder="再次输入密码"
            :prefix-icon="'Lock'"
            show-password
            autocomplete="new-password"
            data-testid="confirm"
            @keyup.enter="onSubmit"
          />
        </el-form-item>

        <el-button
          type="primary"
          size="large"
          class="submit-btn"
          :loading="submitting"
          :disabled="!canSubmit"
          native-type="submit"
          data-testid="submit"
        >
          {{ mode === 'login' ? '登录' : '注册并登录' }}
        </el-button>
      </el-form>

      <div class="switch-row">
        <el-link type="primary" :underline="false" data-testid="switch" @click="toggleMode">
          {{ mode === 'login' ? '没有账号？点击注册' : '已有账号？点击登录' }}
        </el-link>
      </div>

      <p class="hint">
        注册即表示你已知悉本系统为私有部署，所有 API Key 与对话数据仅存储于本服务器。
      </p>
    </el-card>

    <!-- The login page is outside AppShell, so it carries its own disclaimer. -->
    <DisclaimerBar variant="inline" />
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  /* Room for the fixed inline disclaimer (T3.7). */
  padding-bottom: 48px;
  min-height: 100vh;
  padding: 16px;
  background: var(--el-bg-color-page, #f5f7fa);
}

.login-card {
  width: 100%;
  max-width: 400px;
  border-radius: 12px;
}

.title {
  margin: 0 0 4px;
  font-size: 24px;
  font-weight: 600;
}

.subtitle {
  margin: 0 0 20px;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.error-alert {
  margin-bottom: 16px;
}

.submit-btn {
  width: 100%;
  margin-top: 8px;
}

.switch-row {
  margin-top: 16px;
  text-align: center;
}

.hint {
  margin-top: 16px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
</style>

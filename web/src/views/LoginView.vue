<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type InputInstance } from 'element-plus'
import WelcomeOrbit from '@/components/WelcomeOrbit.vue'
import DisclaimerBar from '@/components/DisclaimerBar.vue'
import { useAuthStore } from '@/stores/auth'
import { auth as authApi } from '@/api'

const auth = useAuthStore()
const router = useRouter()
const loginVisible = ref(false)
const entrance = ref<HTMLButtonElement>()
const usernameInput = ref<InputInstance>()

function revealLogin() {
  loginVisible.value = true
}

function focusUsername() {
  usernameInput.value?.focus()
}

async function returnToIntro() {
  if (submitting.value) return
  loginVisible.value = false
  password.value = ''
  confirm.value = ''
  errorMsg.value = null
  await nextTick()
  entrance.value?.focus()
}

const mode = ref<'login' | 'register'>('login')
const registrationEnabled = ref(false)
onMounted(async () => {
  try {
    const status = await authApi.registrationStatus()
    registrationEnabled.value = status.enabled === true
  } catch {
    registrationEnabled.value = false
  }
})
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
      if (!registrationEnabled.value) return
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
  if (!registrationEnabled.value) return
  errorMsg.value = null
  confirm.value = ''
  mode.value = mode.value === 'login' ? 'register' : 'login'
}
</script>

<template>
  <div class="login-page" :class="{ 'is-entered': loginVisible }">
    <header class="landing-header">
      <span class="wordmark">First Step<span>&nbsp;Agent</span><i aria-hidden="true">✳</i></span>
      <span class="header-note">独立思考 · 深入探索</span>
    </header>

    <main class="landing-main">
      <WelcomeOrbit :entered="loginVisible" />
      <Transition name="intro">
        <section v-if="!loginVisible" class="intro-copy" aria-labelledby="welcome-title">
          <p class="eyebrow"><span></span> A NEW FRONTIER OF RESEARCH</p>
          <h1 id="welcome-title">让好奇心，<br />抵达<span>更远处。</span></h1>
          <p class="intro-description">从一个问题出发，连接线索、洞察与可能。<br />你的下一次深入探索，由此开始。</p>
          <div class="enter-hint" aria-hidden="true">
            <span class="enter-arrow">↗</span>
            <span>点击画面，开启探索<small>CLICK TO EXPLORE</small></span>
          </div>
        </section>
      </Transition>
      <button
        v-if="!loginVisible"
        ref="entrance"
        type="button"
        class="entrance-trigger"
        aria-label="开启探索，显示账号登录"
        data-testid="enter-login"
        @click="revealLogin"
      ></button>

      <Transition name="aside">
        <div v-if="loginVisible" class="login-aside" aria-hidden="true">
          <p class="eyebrow">CURIOSITY HAS NO LIMITS</p>
          <p>每一个好问题，<br />都是新世界的起点。</p>
        </div>
      </Transition>

      <Transition name="login" @after-enter="focusUsername">
        <section v-if="loginVisible" class="login-card" aria-labelledby="login-title">
          <button type="button" class="back-button" :disabled="submitting" @click="returnToIntro">← 返回首页</button>
          <p class="eyebrow form-eyebrow">YOUR NEXT DISCOVERY</p>
          <h1 id="login-title" class="title">{{ mode === 'login' ? '欢迎回来。' : '开启你的探索。' }}</h1>
          <p class="subtitle">{{ mode === 'login' ? '登录账号，继续你的研究之旅。' : '创建账号，开始与 FrontierAgent 一起探索。' }}</p>

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
            <el-form-item label="账号" :error="usernameError || undefined">
              <el-input
                ref="usernameInput"
                v-model="username"
                placeholder="用户名（3-64 个字符）"
                autocomplete="username"
                data-testid="username"
                @input="errorMsg = null"
              />
            </el-form-item>

            <el-form-item label="密码" :error="passwordError || undefined">
              <el-input
                v-model="password"
                type="password"
                placeholder="密码（至少 8 位，含字母与数字）"
                show-password
                :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
                data-testid="password"
                @input="errorMsg = null"
              />
            </el-form-item>

            <el-form-item v-if="mode === 'register'" label="确认密码" :error="confirmError || undefined">
              <el-input
                v-model="confirm"
                type="password"
                placeholder="再次输入密码"
                show-password
                autocomplete="new-password"
                data-testid="confirm"
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

          <div v-if="registrationEnabled" class="switch-row">
            <el-link type="primary" :underline="false" data-testid="switch" @click="toggleMode">
              {{ mode === 'login' ? '没有账号？点击注册' : '已有账号？点击登录' }}
            </el-link>
          </div>

          <p v-if="registrationEnabled" class="hint">
            注册即表示你已知悉本系统为私有部署，所有 API Key 与对话数据仅存储于本服务器。
          </p>
          <p v-else class="hint">注册暂未开放，已有账号可正常登录。</p>
        </section>
      </Transition>
    </main>

    <footer class="landing-footer">
      <span>为深度研究而生</span>
      <span class="footer-topics">RESEARCH <i>/</i> REASONING <i>/</i> DISCOVERY</span>
      <span class="edition">FRONTIERAGENT · WORKSPACE</span>
    </footer>

    <!-- The login page is outside AppShell, so it carries its own disclaimer. -->
    <DisclaimerBar variant="inline" />
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  min-height: 100svh;
  overflow: hidden;
  padding: 0 clamp(24px, 5.4vw, 96px) 52px;
  background: #0c130f radial-gradient(ellipse at 75% 40%, #35402a24, transparent 60%);
  color: #f0efe2;
}

.login-page::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: .22;
  background-image: linear-gradient(#d3d0a00d 1px, transparent 1px), linear-gradient(90deg, #d3d0a00d 1px, transparent 1px);
  background-size: 90px 90px;
  mask-image: linear-gradient(90deg, transparent, black);
}

.landing-header, .landing-footer {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.landing-header {
  min-height: 108px;
  border-bottom: 1px solid #c9c7a61c;
}

.wordmark {
  display: flex;
  align-items: center;
  font-size: 23px;
  font-weight: 650;
  letter-spacing: -.8px;
}

.wordmark > span {
  font-weight: 350;
  color: #c8c9b9;
}

.wordmark > i {
  margin-left: 12px;
  color: #d8ca87;
  font-style: normal;
  font-size: 28px;
}

.header-note {
  color: #929c8b;
  font-size: 12px;
  letter-spacing: 3px;
}

.landing-main {
  position: relative;
  display: grid;
  align-items: center;
  flex: 1;
  min-height: 630px;
}

.intro-copy {
  position: relative;
  z-index: 1;
  padding: 70px 0 90px;
  pointer-events: none;
}

.eyebrow {
  margin: 0 0 32px;
  color: #c4bd8d;
  font: 10px/1.6 monospace;
  letter-spacing: 2.7px;
}

.eyebrow > span {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 12px;
  border-radius: 50%;
  background: #cabc76;
  box-shadow: 0 0 12px #cabc7640;
}

.intro-copy h1 {
  margin: 0;
  font-size: clamp(48px, 5.8vw, 88px);
  font-weight: 450;
  line-height: 1.35;
  letter-spacing: -.035em;
}

.intro-copy h1 span {
  color: #d6c989;
}

.intro-description {
  margin: 28px 0 0;
  color: #a7b09e;
  font-size: 15px;
  line-height: 2;
  letter-spacing: 1px;
}

.enter-hint {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-top: 48px;
  color: #e4e3cd;
  font-size: 13px;
  letter-spacing: 2px;
}

.enter-hint small {
  display: block;
  margin-top: 5px;
  color: #939e88;
  font: 9px monospace;
  letter-spacing: 2.5px;
}

.enter-arrow {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border: 1px solid #c9bf8170;
  border-radius: 50%;
  font-size: 24px;
  transition: background .3s, transform .3s;
}

.landing-main:has(.entrance-trigger:hover) .enter-arrow {
  background: #c9bf8120;
  transform: translate(3px, -3px);
}

.entrance-trigger {
  position: absolute;
  z-index: 2;
  inset: 0;
  width: 100%;
  border: 0;
  background: transparent;
  cursor: pointer;
  border-radius: 8px;
}

.entrance-trigger:focus-visible {
  outline-offset: -6px;
}

.login-aside {
  position: absolute;
  bottom: 55px;
  left: 12px;
  pointer-events: none;
}

.login-aside .eyebrow {
  margin-bottom: 14px;
  font-size: 9px;
}

.login-aside > p:last-child {
  margin: 0;
  font-size: 27px;
  line-height: 1.6;
  color: #c9cebd;
  font-weight: 350;
}

.login-card {
  position: relative;
  z-index: 3;
  justify-self: end;
  width: min(100%, 440px);
  margin: 42px 2% 42px 0;
  padding: 32px 36px;
  border: 1px solid #b6bf8b30;
  border-radius: 16px;
  background: #151e18f5;
  box-shadow: 0 30px 100px #0003;
}

.back-button {
  margin: 0 0 28px;
  padding: 0;
  border: 0;
  background: transparent;
  color: #adb59f;
  cursor: pointer;
  font-size: 12px;
}

.back-button:hover {
  color: #e0d392;
}

.back-button:disabled {
  opacity: .5;
  cursor: wait;
}

.form-eyebrow {
  margin-bottom: 9px;
  font-size: 9px;
}

.title {
  margin: 0 0 8px;
  font-size: 30px;
  font-weight: 500;
  letter-spacing: -1px;
}

.subtitle {
  margin: 0 0 28px;
  color: #a7b09e;
  font-size: 13px;
}

.error-alert {
  margin-bottom: 16px;
}

.submit-btn {
  width: 100%;
  margin-top: 10px;
  height: 46px;
  color: var(--accent-text);
  letter-spacing: 2px;
}

.switch-row {
  margin-top: 20px;
  text-align: center;
}

.hint {
  margin: 20px 0 0;
  font-size: 11px;
  color: #a0aa96;
  line-height: 1.8;
}

.login-card :deep(.el-form-item) {
  margin-bottom: 22px;
}

.login-card :deep(.el-form-item__label) {
  font-size: 12px;
  color: #c6cdbb;
}

.login-card :deep(.el-input__wrapper) {
  min-height: 44px;
  border-radius: 6px;
  background: #0f1712;
}

.login-card :deep(.el-input__inner) {
  font-size: 12px;
  color: var(--text);
}

.login-card :deep(.el-form-item__error) {
  color: var(--danger);
}

.landing-footer {
  gap: 20px;
  min-height: 70px;
  border-top: 1px solid #c9c7a61c;
  color: #939e88;
  font-size: 11px;
  letter-spacing: 2px;
}

.footer-topics, .edition {
  font: 9px monospace;
  letter-spacing: 1.5px;
}

.footer-topics i {
  margin: 0 16px;
  color: #64715c;
  font-style: normal;
}

.intro-enter-active, .intro-leave-active {
  transition: opacity .45s, transform .6s;
}

.intro-leave-active {
  position: absolute;
}

.intro-enter-from, .intro-leave-to {
  opacity: 0;
  transform: translateY(-24px);
}

.login-enter-active {
  transition: opacity .65s .18s, transform .8s .12s cubic-bezier(.22, 1, .36, 1);
}

.login-leave-active {
  transition: opacity .2s, transform .25s;
  position: absolute;
  right: 0;
}

.login-enter-from, .login-leave-to {
  opacity: 0;
  transform: translateY(24px);
}

.aside-enter-active {
  transition: opacity .8s .35s;
}

.aside-leave-active {
  transition: opacity .2s;
}

.aside-enter-from, .aside-leave-to {
  opacity: 0;
}

@media (min-width: 1500px) {
  .landing-main {
    width: 100%;
    max-width: 1440px;
    align-self: center;
  }
}

@media (max-width: 960px) {
  .login-card {
    margin-right: 0;
    width: 400px;
    padding: 28px;
  }
  .login-aside > p:last-child {
    font-size: 21px;
  }
  .edition {
    display: none;
  }
}

@media (max-width: 760px) {
  .login-page {
    padding: 0 24px 72px;
  }
  .landing-header {
    min-height: 82px;
  }
  .wordmark {
    font-size: 20px;
  }
  .header-note {
    font-size: 10px;
    letter-spacing: 1px;
  }
  .landing-main {
    min-height: 560px;
  }
  .intro-copy {
    padding: 68px 0;
  }
  .intro-copy h1 {
    font-size: clamp(42px, 8.4vw, 62px);
  }
  .eyebrow {
    font-size: 8px;
    letter-spacing: 1.8px;
  }
  .intro-description {
    font-size: 13px;
    letter-spacing: 0;
  }
  .login-aside {
    display: none;
  }
  .login-card {
    justify-self: center;
    margin: 30px 0;
    padding: 26px;
    width: min(100%, 440px);
  }
  .landing-footer {
    min-height: 55px;
    font-size: 10px;
  }
  .footer-topics {
    font-size: 8px;
    letter-spacing: 0;
  }
  .footer-topics i {
    margin: 0 5px;
  }
}

@media (max-width: 380px) {
  .header-note {
    display: none;
  }
  .login-card {
    padding: 22px 18px;
  }
  .footer-topics {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
  }
}
</style>

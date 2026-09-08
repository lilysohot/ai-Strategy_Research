/**
 * App bootstrap (T3.1).
 *
 * Order matters:
 *   1. Pinia first — the auth store is a dependency of the router guard and of
 *      the SSE client's token getter, so it must exist before either runs.
 *   2. ``auth.install()`` registers the token provider that ``api/client.ts``
 *      reads on every request; without it every call would go out anonymous.
 *   3. ``setUnauthorizedHandler`` gives the REST client one place to send a 401
 *      (clear the session, bounce to /login) instead of each view deciding.
 *   4. The router is installed last and performs the bootstrap ``/auth/me``
 *      inside its guard, before the first protected navigation resolves.
 */

import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import { setUnauthorizedHandler } from './api/client'
import router from './router'
import { useAuthStore } from './stores/auth'
import './style.css'

const app = createApp(App)

const pinia = createPinia()
app.use(pinia)

// The store is only usable after Pinia is installed on the app.
const auth = useAuthStore(pinia)
auth.install()

setUnauthorizedHandler(() => {
  // Guard against a redirect loop: if we are already on /login there is nothing
  // to bounce to, and the login call itself legitimately returns 401.
  if (router.currentRoute.value.name === 'login') return
  auth.clear()
  void router.push({ name: 'login' })
})

app.use(router)
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')

/**
 * Route table + auth guard (T3.1 skeleton).
 *
 * The guard is deliberately "wait for bootstrap, then decide": checking
 * ``auth.isAuthenticated`` before the initial ``/auth/me`` resolves would bounce
 * every reload to /login even with a valid token in storage.
 */

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('../views/AppShell.vue'),
    children: [
      {
        path: '',
        name: 'chat',
        component: () => import('../views/ChatView.vue'),
      },
      {
        path: 'models',
        name: 'models',
        component: () => import('../views/ModelConfigsView.vue'),
      },
    ],
  },
  // Anything unknown falls back into the app rather than a 404 page: the shell
  // owns the navigation, and an unknown deep link is a stale bookmark.
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  if (!auth.ready && !auth.initializing) {
    await auth.bootstrap()
  }

  if (to.meta.public) {
    // Already logged in? Skip the login page.
    if (to.name === 'login' && auth.isAuthenticated) return { name: 'chat' }
    return true
  }

  if (!auth.isAuthenticated) {
    return { name: 'login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
  }
  return true
})

export default router

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
      // Real 404 instead of a silent redirect (T12): an unknown deep link gets a
      // page that says so, with the shell nav still there as the way out.
      {
        path: ':pathMatch(.*)*',
        name: 'not-found',
        component: () => import('../views/NotFoundView.vue'),
      },
    ],
  },
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

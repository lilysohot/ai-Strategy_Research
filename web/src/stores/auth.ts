/**
 * Auth store (T3.1 skeleton + T3.2 login/register wiring): owns the JWT and is
 * the single source the REST client and the SSE client read their token from.
 *
 * Storage choice: ``localStorage``. The token is a 24h JWT and the app is a
 * single-page tool, so surviving a reload is worth more than the XSS exposure of
 * ``sessionStorage``'s shorter life — the real defence is that no api_key is
 * ever held client-side, only this bearer token.
 *
 * The store registers itself as the token provider for ``src/api/client.ts`` so
 * that nothing else has to thread the token through call sites.
 */

import { defineStore } from 'pinia'

import { auth as authApi } from '../api'
import { ApiError, setTokenProvider } from '../api/client'
import type { User } from '../types'

const TOKEN_KEY = 'frontier-agent.token'

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    // Private-mode / blocked storage must not break bootstrap.
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: readStoredToken() as string | null,
    user: null as User | null,
    /** True while the initial ``/auth/me`` probe is in flight. */
    initializing: false,
    ready: false,
  }),

  getters: {
    isAuthenticated: (state): boolean => Boolean(state.token) && Boolean(state.user),
  },

  actions: {
    /** Wire the token provider once, from main.ts, before any request fires. */
    install(): void {
      setTokenProvider(() => this.token)
    },

    setToken(token: string | null): void {
      this.token = token
      try {
        if (token) localStorage.setItem(TOKEN_KEY, token)
        else localStorage.removeItem(TOKEN_KEY)
      } catch {
        /* storage unavailable — session-only login is an acceptable fallback */
      }
    },

    async register(username: string, password: string): Promise<User> {
      return authApi.register(username, password)
    },

    async login(username: string, password: string): Promise<void> {
      const res = await authApi.login(username, password)
      this.setToken(res.access_token)
      // Fail closed: a token we cannot turn into a user is not a session.
      // If /auth/me fails (transient network blip, not a credential error),
      // drop the token we just persisted so we don't leave a zombie session.
      try {
        this.user = await authApi.me()
      } catch (err) {
        if (!(err instanceof ApiError && err.isUnauthorized)) this.clear()
        throw err
      }
    },

    /**
     * Resolve the stored token into a user, once, at bootstrap.
     *
     * A 401 here is expected (expired token) and is not an error to surface: we
     * simply drop it and let the router guard send the user to /login.
     */
    async bootstrap(): Promise<void> {
      if (!this.token) {
        this.ready = true
        return
      }
      this.initializing = true
      try {
        this.user = await authApi.me()
      } catch (err) {
        if (err instanceof ApiError && err.isUnauthorized) this.clear()
        // Any other failure leaves the token in place: a transient network error
        // on startup should not log the user out of a valid session.
      } finally {
        this.initializing = false
        this.ready = true
      }
    },

    async logout(): Promise<void> {
      try {
        if (this.token) await authApi.logout()
      } catch {
        // Server-side revocation is best-effort; the client must still drop the
        // token or "logout" would be a no-op on a network blip.
      }
      this.clear()
    },

    /** Drop the local session. Called by the 401 handler too. */
    clear(): void {
      this.setToken(null)
      this.user = null
    },
  },
})

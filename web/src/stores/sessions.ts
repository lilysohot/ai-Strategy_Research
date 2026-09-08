/**
 * Sessions store (T3.3): owns the conversation list and which session is active.
 *
 * A session is just a title + an ordered list of turns (user/assistant messages).
 * The store loads the list once on entry and the turns for the active session;
 * the live run stream lives in ``runStream`` (T3.1), so this store never holds a
 * fetch handle — it only fetches list/turns and mutates the list optimistically.
 *
 * Setup-store syntax so the plain (non-reactive) ``sessionsApi`` calls stay out of
 * the reactivity proxy; only the ref state is watched by components.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiError } from '../api/client'
import { sessions as sessionsApi } from '../api'
import type { Session, Turn } from '../types'

export const useSessionsStore = defineStore('sessions', () => {
  const list = ref<Session[]>([])
  const activeId = ref<string | null>(null)
  const activeTurns = ref<Turn[]>([])
  const loadingList = ref(false)
  const loadingTurns = ref(false)
  const error = ref<string | null>(null)

  const activeSession = computed(() =>
    list.value.find((s) => s.id === activeId.value) ?? null,
  )

  async function loadList(): Promise<void> {
    loadingList.value = true
    error.value = null
    try {
      const res = await sessionsApi.list()
      list.value = res.sessions.sort((a, b) => {
        const at = b.updated_at ?? b.created_at ?? ''
        const bt = a.updated_at ?? a.created_at ?? ''
        return at.localeCompare(bt)
      })
    } catch (err) {
      error.value = err instanceof ApiError ? err.message : '加载会话列表失败'
      throw err
    } finally {
      loadingList.value = false
    }
  }

  async function select(id: string): Promise<void> {
    if (id === activeId.value) return
    activeId.value = id
    activeTurns.value = []
    await loadTurns(id)
  }

  async function loadTurns(id: string): Promise<void> {
    loadingTurns.value = true
    error.value = null
    try {
      const res = await sessionsApi.turns(id)
      activeTurns.value = res.turns
    } catch (err) {
      error.value = err instanceof ApiError ? err.message : '加载对话记录失败'
      throw err
    } finally {
      loadingTurns.value = false
    }
  }

  /**
   * Create a session, optionally seeded with a first message. On success the new
   * session becomes active and its turns are loaded.
   */
  async function create(title?: string, firstMessage?: string): Promise<Session> {
    const created = await sessionsApi.create(title, firstMessage)
    list.value = [created, ...list.value]
    activeId.value = created.id
    if (firstMessage) {
      activeTurns.value = [
        { seq: 1, role: 'user', content: firstMessage, run_id: null, created_at: null },
      ]
    } else {
      activeTurns.value = []
    }
    return created
  }

  /** Append a local turn immediately (before the server echoes it back). */
  function appendLocalTurn(turn: Turn): void {
    activeTurns.value = [...activeTurns.value, turn]
  }

  async function remove(id: string): Promise<void> {
    try {
      await sessionsApi.remove(id)
    } catch (err) {
      // A 404 means it was already gone; that's still a successful delete from the
      // user's point of view, so don't surface it.
      if (!(err instanceof ApiError && err.status === 404)) throw err
    }
    list.value = list.value.filter((s) => s.id !== id)
    if (activeId.value === id) {
      activeId.value = null
      activeTurns.value = []
    }
  }

  function reset(): void {
    list.value = []
    activeId.value = null
    activeTurns.value = []
    error.value = null
  }

  return {
    list,
    activeId,
    activeSession,
    activeTurns,
    loadingList,
    loadingTurns,
    error,
    loadList,
    select,
    loadTurns,
    create,
    appendLocalTurn,
    remove,
    reset,
  }
})

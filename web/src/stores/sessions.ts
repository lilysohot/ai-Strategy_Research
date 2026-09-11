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

/**
 * Page sizes. Turns come back newest-last, so the first page is the end of the
 * conversation — the part the user came back for — and older pages are fetched
 * on demand instead of on every load.
 */
const SESSION_PAGE_SIZE = 50
const TURN_PAGE_SIZE = 100

export const useSessionsStore = defineStore('sessions', () => {
  const list = ref<Session[]>([])
  const activeId = ref<string | null>(null)
  const activeTurns = ref<Turn[]>([])
  const loadingList = ref(false)
  const loadingTurns = ref(false)
  /** Whether older turns exist beyond what ``activeTurns`` currently holds. */
  const hasMoreTurns = ref(false)
  const loadingOlder = ref(false)
  const error = ref<string | null>(null)

  const activeSession = computed(() =>
    list.value.find((s) => s.id === activeId.value) ?? null,
  )

  async function loadList(): Promise<void> {
    loadingList.value = true
    error.value = null
    try {
      const res = await sessionsApi.list({ limit: SESSION_PAGE_SIZE })
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

  /**
   * ``limit`` defaults to one page. Callers refreshing a conversation the user
   * has already paged through pass the current length instead, so a refresh
   * cannot quietly drop the older turns they scrolled up to read.
   */
  async function loadTurns(id: string, limit: number = TURN_PAGE_SIZE): Promise<void> {
    loadingTurns.value = true
    error.value = null
    try {
      const res = await sessionsApi.turns(id, { limit })
      activeTurns.value = res.turns
      hasMoreTurns.value = res.has_more
    } catch (err) {
      error.value = err instanceof ApiError ? err.message : '加载对话记录失败'
      throw err
    } finally {
      loadingTurns.value = false
    }
  }

  /**
   * Fetch the page of turns older than the oldest one already held.
   *
   * Prepends instead of replacing: the caller is scrolling up through history,
   * so what is on screen has to stay exactly where it is.
   */
  async function loadOlderTurns(): Promise<void> {
    const id = activeId.value
    const oldest = activeTurns.value[0]?.seq
    if (!id || loadingOlder.value || !hasMoreTurns.value || oldest === undefined) return
    loadingOlder.value = true
    error.value = null
    try {
      const res = await sessionsApi.turns(id, {
        limit: TURN_PAGE_SIZE,
        before_seq: oldest,
      })
      activeTurns.value = [...res.turns, ...activeTurns.value]
      hasMoreTurns.value = res.has_more
    } catch (err) {
      error.value = err instanceof ApiError ? err.message : '加载更早消息失败'
      throw err
    } finally {
      loadingOlder.value = false
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
    hasMoreTurns.value = false
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
      hasMoreTurns.value = false
    }
  }

  function reset(): void {
    list.value = []
    activeId.value = null
    activeTurns.value = []
    hasMoreTurns.value = false
    loadingOlder.value = false
    error.value = null
  }

  return {
    list,
    activeId,
    activeSession,
    activeTurns,
    loadingList,
    loadingTurns,
    hasMoreTurns,
    loadingOlder,
    error,
    loadList,
    select,
    loadTurns,
    loadOlderTurns,
    create,
    appendLocalTurn,
    remove,
    reset,
  }
})

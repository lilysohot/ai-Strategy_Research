import { onUnmounted, shallowRef, watch, type Ref } from 'vue'
import { superLink, type SnapshotQuery } from '../api/superLink'
import { useAuthStore } from '../stores/auth'
import { openSpaceStream } from './stream'
import { createSpaceSync, emptySpaceSyncState, type ListKind, type SpaceSync, type SpaceSyncState } from './sync'

/** Bind the framework-free space sync engine to the current route's space. */
export function useSpaceSync(spaceId: Ref<string>) {
  const auth = useAuthStore()
  const state = shallowRef<SpaceSyncState>(emptySpaceSyncState())
  let sync: SpaceSync | null = null

  const stop = () => {
    sync?.stop()
    sync = null
  }

  watch(spaceId, (id) => {
    stop()
    state.value = emptySpaceSyncState()
    if (!id) return
    sync = createSpaceSync({
      spaceId: id,
      loadSnapshot: (query: SnapshotQuery) => superLink.snapshot(id, query),
      openStream: ({ after, callbacks }) => openSpaceStream({
        url: `/api/super-link/spaces/${encodeURIComponent(id)}/events`,
        token: () => auth.token,
        after,
        callbacks,
      }),
      onState: (value) => { state.value = value },
    })
    sync.start()
  }, { immediate: true })

  onUnmounted(stop)

  return {
    state,
    retry: () => sync?.retry(),
    refreshNow: () => sync?.refreshNow(),
    returnToLatest: () => sync?.returnToLatest(),
    loadMore: (kind: ListKind) => sync?.loadMore(kind) ?? Promise.resolve(),
  }
}

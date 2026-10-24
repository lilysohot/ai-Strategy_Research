import type { RunMode } from '../types'

/** Freeze the selected mode into either transport before submitting this turn. */
export function buildRunPayload(message: string, files: File[], sessionId: string, mode: RunMode):
  { message: string; session_id: string; mode: RunMode } | FormData {
  if (!files.length) return { session_id: sessionId, message, mode }
  const form = new FormData()
  form.append('session_id', sessionId)
  form.append('message', message)
  form.append('mode', mode)
  for (const file of files) form.append('files', file)
  return form
}

/**
 * Preview render-mode selection (P2.3, cli-web-parity.md §5.4).
 *
 * The server's preview endpoint already classified the file (text | image |
 * binary | unsupported); this only decides *how* the panel renders it:
 * markdown through the sanitizer, other text as a plain <pre>, images via
 * their data URL, everything else as a download hint.
 */

export type PreviewRenderMode = 'markdown' | 'code' | 'image' | 'download'

const MARKDOWN_EXTS = new Set(['md', 'markdown'])

export function previewRenderMode(relPath: string, kind: string): PreviewRenderMode {
  if (kind === 'image') return 'image'
  if (kind === 'text') {
    const ext = relPath.split('.').pop()?.toLowerCase() ?? ''
    return MARKDOWN_EXTS.has(ext) ? 'markdown' : 'code'
  }
  return 'download'
}

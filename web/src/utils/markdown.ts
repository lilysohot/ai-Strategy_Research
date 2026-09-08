/**
 * Markdown rendering for assistant messages. Content comes from an LLM, so it is
 * untrusted and is handled in two stages:
 *
 *  1. **Redact** known credential shapes (T3.7). Model output can quote a key —
 *     from a ``read_file`` of an env file, or by simply echoing its own config —
 *     and the platform's contract is that no plaintext key ever reaches the
 *     screen. Redacting before parsing keeps a secret from being baked into the
 *     rendered HTML (and into a ``href``/``src`` we would then have to sanitize).
 *  2. **Render then sanitize** with markdown-it + DOMPurify: HTML pass-through is
 *     disabled and the result is scrubbed, so untrusted content cannot inject
 *     script or event handlers.
 */

import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'

import { redactSecrets } from './redact'

const md = new MarkdownIt({
  html: false, // do not pass raw HTML through; DOMPurify is the only HTML source
  linkify: true,
  breaks: true,
})

export function renderMarkdown(src: string): string {
  const safe = redactSecrets(src ?? '')
  const raw = md.render(safe)
  return DOMPurify.sanitize(raw)
}

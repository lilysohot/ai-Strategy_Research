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

const reportDetailTitles = new Set([
  '核验范围',
  '内容读取边界',
  'Verification scope',
  'Content access limits',
])

/** Collapse report appendices in conversation answers, including saved history. */
export function renderChatMarkdown(src: string): string {
  const container = document.createElement('div')
  container.innerHTML = renderMarkdown(src)

  // Only top-level report headings qualify; quoted examples and code stay intact.
  for (const heading of Array.from(container.children)) {
    if (
      heading.parentNode !== container ||
      heading.tagName !== 'H3' ||
      !reportDetailTitles.has(heading.textContent?.trim() ?? '')
    ) continue

    const details = document.createElement('details')
    details.className = 'report-details'
    const summary = document.createElement('summary')
    summary.textContent = heading.textContent
    details.append(summary)
    heading.replaceWith(details)

    // Keep nested subsections with their appendix, stopping at a peer or parent.
    while (details.nextSibling) {
      const next = details.nextSibling
      if (next instanceof Element && /^H[1-3]$/.test(next.tagName)) break
      details.append(next)
    }
  }
  return container.innerHTML
}

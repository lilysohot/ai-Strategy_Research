/**
 * Revert eligibility and result wording (P3.3, cli-web-parity.md §6.3).
 *
 * The rule the terminal's ``/revert`` also enforces: only the FIRST diff class
 * — files a file tool explicitly targeted, snapshotted before the write — can
 * be undone. The bash-scan class (§2.2 第二类) is display-only, because a scan
 * can see that the tree changed but never *who* changed it: the user's editor
 * or a dev server writing in the same window is indistinguishable from the
 * agent, and reverting it would destroy work that was never the agent's.
 *
 * Those rows stay visible with the reason spelled out. A checkbox that is
 * silently missing reads as a bug, so the explanation is part of the contract.
 */
import type { DiffFile, RevertResult } from '../types'

/**
 * Row key. A path is unique per source in practice (the scan skips everything a
 * file tool already covered), but keying on both keeps the list stable if that
 * ever stops holding.
 */
export function diffKey(file: DiffFile): string {
  return `${file.source}::${file.path}`
}

/** Only a file-tool write has a baseline to restore. */
export function isRevertable(file: DiffFile): boolean {
  return file.source === 'file_tool'
}

/** Why the scan class cannot be reverted — shown on every non-revertable row. */
export const REVERT_SCAN_REASON =
  '扫描发现：无法区分是 Agent 改动还是你的编辑/开发服务器写入，自动回滚会一并撤销无关工作，请手动处理'

/**
 * Paths to send for ``selected`` row keys, in list order.
 *
 * Filtering here is a UI affordance only — the server re-derives it from the
 * run's own manifest, so a crafted payload cannot widen what is revertible.
 */
export function revertTargets(files: DiffFile[], selected: Iterable<string>): string[] {
  const keys = new Set(selected)
  return files.filter((f) => keys.has(diffKey(f)) && isRevertable(f)).map((f) => f.path)
}

export interface RevertOutcome {
  reverted: number
  rejected: number
}

export function summarizeRevert(results: RevertResult[]): RevertOutcome {
  let reverted = 0
  let rejected = 0
  for (const r of results) {
    if (r.status === 'restored' || r.status === 'removed') reverted += 1
    else rejected += 1
  }
  return { reverted, rejected }
}

/** Human-readable line for one result; the server's wording wins when present. */
export function revertResultText(result: RevertResult): string {
  if (result.message) return result.message
  switch (result.status) {
    case 'restored':
      return '已还原'
    case 'removed':
      return '已删除（运行前不存在）'
    case 'failed':
      return '回滚失败'
    default:
      return '无法回滚'
  }
}

import type { DiffFile } from '@/types'

export type DiffStatus = DiffFile['status']
export type DiffSource = DiffFile['source']

export interface DiffSummary {
  files: number
  additions: number
  deletions: number
}

export function summarizeDiff(files: DiffFile[]): DiffSummary {
  return {
    files: files.length,
    additions: files.reduce((n, f) => n + (f.additions || 0), 0),
    deletions: files.reduce((n, f) => n + (f.deletions || 0), 0),
  }
}

export function diffStatusLabel(status: DiffStatus): string {
  switch (status) {
    case 'added':
      return '新增'
    case 'modified':
      return '修改'
    case 'deleted':
      return '删除'
    default:
      return status
  }
}

export function diffStatusTagType(
  status: DiffStatus,
): 'success' | 'warning' | 'danger' | 'info' {
  switch (status) {
    case 'added':
      return 'success'
    case 'modified':
      return 'warning'
    case 'deleted':
      return 'danger'
    default:
      return 'info'
  }
}

export interface DiffLine {
  type: 'meta' | 'hunk' | 'add' | 'del' | 'ctx'
  text: string
}

/** Classify a unified diff body into renderable lines (terminal 绿+/红-). */
export function classifyDiffLines(hunks: string): DiffLine[] {
  return hunks
    .split('\n')
    .filter((line, i, arr) => line.length > 0 || i < arr.length - 1)
    .map((line): DiffLine => {
      if (line.startsWith('---') || line.startsWith('+++')) {
        return { type: 'meta', text: line }
      }
      if (line.startsWith('@@')) return { type: 'hunk', text: line }
      if (line.startsWith('+')) return { type: 'add', text: line }
      if (line.startsWith('-')) return { type: 'del', text: line }
      return { type: 'ctx', text: line }
    })
}

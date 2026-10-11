import { STATUSES, STATUS_LABEL, type Status } from '../types'

const TONE: Record<Status | 'none', string> = {
  none: 'border-zinc-300 text-zinc-500 dark:border-zinc-700 dark:text-zinc-400',
  saved: 'border-sky-300 bg-sky-50 text-sky-700 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-300',
  applied: 'border-indigo-300 bg-indigo-50 text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950 dark:text-indigo-300',
  interviewing: 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300',
  offer: 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
  rejected: 'border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-300',
  hidden: 'border-zinc-300 bg-zinc-100 text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400',
}

export function StatusSelect({ value, onChange }: { value?: Status; onChange: (s: Status | null) => void }) {
  return (
    <select
      aria-label="Status"
      value={value ?? ''}
      onChange={(e) => onChange((e.target.value || null) as Status | null)}
      className={`rounded-md border bg-white px-2 py-1 text-xs font-medium dark:bg-zinc-900 ${TONE[value ?? 'none']}`}
    >
      <option value="">Track…</option>
      {STATUSES.map((s) => (
        <option key={s} value={s}>
          {STATUS_LABEL[s]}
        </option>
      ))}
    </select>
  )
}

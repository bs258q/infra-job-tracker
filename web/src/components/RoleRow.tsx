import { ExternalLink, MapPin } from 'lucide-react'
import { avatarColor, postedLabel, salaryLabel } from '../lib/format'
import type { Role, Status } from '../types'
import { StatusSelect } from './StatusSelect'

type Props = {
  role: Role
  isNew: boolean
  status?: Status
  onStatus: (s: Status | null) => void
}

export function RoleRow({ role, isNew, status, onStatus }: Props) {
  const pay = salaryLabel(role)
  const extraLocs = role.locations.length - 2

  return (
    <li
      className={`group flex gap-3 border-b border-zinc-200 px-4 py-3 last:border-0 dark:border-zinc-800 ${
        status === 'hidden' ? 'opacity-50' : ''
      } ${isNew ? 'bg-indigo-50/60 dark:bg-indigo-950/20' : ''}`}
    >
      <div className={`mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg text-sm font-semibold ${avatarColor(role.company)}`}>
        {role.company.slice(0, 1).toUpperCase()}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <a
            href={role.url}
            target="_blank"
            rel="noreferrer"
            className="font-medium text-zinc-900 hover:text-indigo-600 hover:underline dark:text-zinc-100 dark:hover:text-indigo-400"
          >
            {role.title}
            <ExternalLink className="ml-1 inline size-3 opacity-0 transition group-hover:opacity-60" />
          </a>
          {isNew && (
            <span className="rounded bg-indigo-600 px-1.5 py-px text-[10px] font-semibold tracking-wide text-white uppercase">New</span>
          )}
        </div>

        <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-sm text-zinc-500 dark:text-zinc-400">
          <span className="font-medium text-zinc-700 dark:text-zinc-300">{role.company}</span>
          <span className="flex min-w-0 items-center gap-1">
            <MapPin className="size-3 shrink-0" />
            <span className="truncate">
              {role.locations.slice(0, 2).join(' · ')}
              {extraLocs > 0 && ` +${extraLocs}`}
            </span>
          </span>
          {(role.workplace === 'Remote' || role.workplace === 'Hybrid') && (
            <span
              className={`rounded px-1.5 text-xs font-medium ${
                role.workplace === 'Remote'
                  ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400'
                  : 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400'
              }`}
            >
              {role.workplace}
            </span>
          )}
          <span>{role.level}</span>
        </div>

        <div className="mt-1.5 flex flex-wrap gap-1">
          {role.categories.map((c) => (
            <span key={c} className="rounded-full bg-zinc-100 px-2 py-px text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              {c}
            </span>
          ))}
        </div>
      </div>

      <div className="flex shrink-0 flex-col items-end gap-1.5 text-right">
        <span className={`text-sm font-semibold tabular-nums ${pay ? 'text-emerald-700 dark:text-emerald-400' : 'text-zinc-300 dark:text-zinc-700'}`}>
          {pay || '—'}
        </span>
        <span className="text-xs text-zinc-500 dark:text-zinc-400" title={role.posted ?? `First seen ${role.firstSeen}`}>
          {postedLabel(role)}
        </span>
        <StatusSelect value={status} onChange={onStatus} />
      </div>
    </li>
  )
}

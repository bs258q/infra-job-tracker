import { Search, SlidersHorizontal, Sparkles, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { applyFilters } from '../lib/filter'
import type { Filters, PostedWindow, Role, SortKey, Status, Tracked } from '../types'
import { FilterPanel } from './FilterPanel'
import { RoleRow } from './RoleRow'

const PAGE = 75
const WINDOWS: [PostedWindow, string][] = [
  ['any', 'Any time'],
  ['24h', 'Last 24h'],
  ['7d', 'Last 7 days'],
  ['30d', 'Last 30 days'],
]

type Props = {
  roles: Role[]
  filters: Filters
  setFilters: (f: Filters) => void
  tracked: Record<string, Tracked>
  setStatus: (role: Role, s: Status | null) => void
  newCutoff: string
  markAllSeen: () => void
}

export function RolesView({ roles, filters, setFilters, tracked, setStatus, newCutoff, markAllSeen }: Props) {
  const [limit, setLimit] = useState(PAGE)
  const [showFilters, setShowFilters] = useState(false)

  const results = useMemo(() => applyFilters(roles, filters, tracked, newCutoff), [roles, filters, tracked, newCutoff])
  const newCount = useMemo(() => roles.filter((r) => r.firstSeen > newCutoff).length, [roles, newCutoff])

  const update = (f: Filters) => {
    setFilters(f)
    setLimit(PAGE)
  }

  return (
    <div className="flex gap-8">
      <aside
        className={`${showFilters ? 'fixed inset-0 z-30 block overflow-y-auto bg-white p-5 dark:bg-zinc-950' : 'hidden'} lg:sticky lg:top-20 lg:block lg:max-h-[calc(100vh-6rem)] lg:w-64 lg:shrink-0 lg:overflow-y-auto lg:bg-transparent lg:p-0`}
      >
        <button onClick={() => setShowFilters(false)} className="mb-4 flex items-center gap-1 text-sm lg:hidden">
          <X className="size-4" /> Close
        </button>
        <FilterPanel roles={roles} filters={filters} setFilters={update} tracked={tracked} />
      </aside>

      <section className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-60 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-zinc-400" />
            <input
              value={filters.q}
              onChange={(e) => update({ ...filters, q: e.target.value })}
              placeholder="Search title, company, or location — e.g. inference kubernetes"
              className="w-full rounded-lg border border-zinc-300 bg-white py-2 pr-3 pl-9 text-sm shadow-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 dark:border-zinc-700 dark:bg-zinc-900"
            />
          </div>
          <button
            onClick={() => setShowFilters(true)}
            className="flex items-center gap-1.5 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm lg:hidden dark:border-zinc-700 dark:bg-zinc-900"
          >
            <SlidersHorizontal className="size-4" /> Filters
          </button>
          <select
            value={filters.sort}
            onChange={(e) => update({ ...filters, sort: e.target.value as SortKey })}
            className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          >
            <option value="newest">Newest first</option>
            <option value="salary">Highest pay</option>
            <option value="company">Company A–Z</option>
          </select>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-zinc-300 bg-white p-0.5 dark:border-zinc-700 dark:bg-zinc-900">
            {WINDOWS.map(([w, label]) => (
              <button
                key={w}
                onClick={() => update({ ...filters, posted: w })}
                className={`rounded-md px-3 py-1 text-sm transition ${
                  filters.posted === w ? 'bg-indigo-600 text-white shadow-sm' : 'text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            onClick={() => update({ ...filters, newOnly: !filters.newOnly })}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition ${
              filters.newOnly
                ? 'border-indigo-600 bg-indigo-600 text-white'
                : 'border-zinc-300 bg-white text-zinc-700 hover:border-indigo-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300'
            }`}
          >
            <Sparkles className="size-3.5" />
            New since last visit
            <span className={`rounded-full px-1.5 text-xs tabular-nums ${filters.newOnly ? 'bg-white/20' : 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300'}`}>
              {newCount}
            </span>
          </button>
          {newCount > 0 && (
            <button onClick={markAllSeen} className="text-sm text-zinc-500 hover:text-zinc-800 hover:underline dark:hover:text-zinc-200">
              Mark all seen
            </button>
          )}
          <span className="ml-auto text-sm text-zinc-500 tabular-nums">
            {results.length.toLocaleString()} role{results.length === 1 ? '' : 's'}
          </span>
        </div>

        <ul className="mt-4 overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          {results.slice(0, limit).map((r) => (
            <RoleRow
              key={r.id}
              role={r}
              isNew={r.firstSeen > newCutoff}
              status={tracked[r.id]?.status}
              onStatus={(s) => setStatus(r, s)}
            />
          ))}
          {results.length === 0 && (
            <li className="px-4 py-16 text-center text-sm text-zinc-500">No roles match these filters.</li>
          )}
        </ul>

        {results.length > limit && (
          <button
            onClick={() => setLimit(limit + PAGE)}
            className="mx-auto mt-4 block rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm hover:border-indigo-400 dark:border-zinc-700 dark:bg-zinc-900"
          >
            Show more ({(results.length - limit).toLocaleString()} left)
          </button>
        )}
      </section>
    </div>
  )
}

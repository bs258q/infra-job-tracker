import { useMemo, useState } from 'react'
import { countBy } from '../lib/filter'
import { DEFAULT_FILTERS, NOT_STATED, STATUSES, STATUS_LABEL, type Facets, type Filters, type Role, type Tracked } from '../types'

const SALARY_STEPS = [0, 100_000, 150_000, 200_000, 250_000, 300_000, 400_000]

type Props = {
  roles: Role[]
  facets: Facets
  filters: Filters
  setFilters: (f: Filters) => void
  tracked: Record<string, Tracked>
}

type ListKey = 'categories' | 'levels' | 'regions' | 'workplaces' | 'companies'

export function FilterPanel({ roles, facets, filters, setFilters, tracked }: Props) {
  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setFilters({ ...filters, [k]: v })
  const toggle = (k: ListKey, v: string) => {
    const cur = filters[k]
    set(k, cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v])
  }

  const categoryCounts = useMemo(() => countBy(roles, (r) => r.categories), [roles])
  const regionCounts = useMemo(() => countBy(roles, (r) => r.regions), [roles])
  const workplaceCounts = useMemo(() => countBy(roles, (r) => [r.workplace ?? NOT_STATED]), [roles])
  const levelCounts = useMemo(() => countBy(roles, (r) => [r.level]), [roles])
  const companyCounts = useMemo(() => countBy(roles, (r) => [r.company]), [roles])
  const statusCounts = useMemo(() => {
    const m = new Map<string, number>()
    for (const t of Object.values(tracked)) m.set(t.status, (m.get(t.status) ?? 0) + 1)
    return m
  }, [tracked])

  const [companyQuery, setCompanyQuery] = useState('')
  const companies = [...companyCounts.entries()]
    .filter(([name]) => name.toLowerCase().includes(companyQuery.toLowerCase()))
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))

  const active =
    JSON.stringify({ ...filters, q: '', sort: 'newest' }) !== JSON.stringify({ ...DEFAULT_FILTERS, sort: 'newest' })

  return (
    <div className="space-y-6 text-sm">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Filters</h2>
        {active && (
          <button
            onClick={() => setFilters({ ...DEFAULT_FILTERS, q: filters.q, sort: filters.sort })}
            className="text-xs text-indigo-600 hover:underline dark:text-indigo-400"
          >
            Reset
          </button>
        )}
      </div>

      <Section title="My status">
        <select
          value={filters.status}
          onChange={(e) => set('status', e.target.value as Filters['status'])}
          className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-900"
        >
          <option value="active">All (except not interested)</option>
          <option value="untracked">Not tracked yet</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s]} ({statusCounts.get(s) ?? 0})
            </option>
          ))}
        </select>
      </Section>

      <FacetSection title="Role type" order={facets.categories} counts={categoryCounts} selected={filters.categories} onToggle={(v) => toggle('categories', v)} />
      <FacetSection title="Workplace" order={facets.workplaces} counts={workplaceCounts} selected={filters.workplaces} onToggle={(v) => toggle('workplaces', v)} />
      <FacetSection title="Location" order={facets.regions} counts={regionCounts} selected={filters.regions} onToggle={(v) => toggle('regions', v)} />
      <FacetSection title="Level" order={facets.levels} counts={levelCounts} selected={filters.levels} onToggle={(v) => toggle('levels', v)} />

      <Section title="Salary">
        <select
          value={filters.minSalary}
          onChange={(e) => set('minSalary', Number(e.target.value))}
          className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 dark:border-zinc-700 dark:bg-zinc-900"
        >
          {SALARY_STEPS.map((s) => (
            <option key={s} value={s}>
              {s ? `Up to at least $${s / 1000}K` : 'Any salary'}
            </option>
          ))}
        </select>
        <Check label="Only roles with listed pay" checked={filters.salaryOnly} onChange={() => set('salaryOnly', !filters.salaryOnly)} />
      </Section>

      <Section title={`Company${filters.companies.length ? ` · ${filters.companies.length} selected` : ''}`}>
        <input
          value={companyQuery}
          onChange={(e) => setCompanyQuery(e.target.value)}
          placeholder="Find company…"
          className="mb-1 w-full rounded-md border border-zinc-300 bg-white px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
        />
        <div className="max-h-64 overflow-y-auto pr-1">
          {companies.map(([name, n]) => (
            <Check key={name} label={name} count={n} checked={filters.companies.includes(name)} onChange={() => toggle('companies', name)} />
          ))}
        </div>
      </Section>
    </div>
  )
}

function FacetSection({
  title,
  order,
  counts,
  selected,
  onToggle,
}: {
  title: string
  order: string[]
  counts: Map<string, number>
  selected: string[]
  onToggle: (v: string) => void
}) {
  // Values missing from `order` (e.g. older data) still show, after the ordered ones.
  const values = [...order, ...[...counts.keys()].filter((k) => !order.includes(k)).sort()].filter((v) => counts.has(v))
  if (values.length < 2 && !selected.length) return null
  return (
    <Section title={title}>
      {values.map((v) => (
        <Check key={v} label={v} count={counts.get(v)} checked={selected.includes(v)} onChange={() => onToggle(v)} />
      ))}
    </Section>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-medium tracking-wide text-zinc-500 uppercase dark:text-zinc-400">{title}</h3>
      <div className="space-y-1">{children}</div>
    </div>
  )
}

function Check({ label, count, checked, onChange }: { label: string; count?: number; checked: boolean; onChange: () => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-zinc-100 dark:hover:bg-zinc-800/60">
      <input type="checkbox" checked={checked} onChange={onChange} className="size-3.5 accent-indigo-600" />
      <span className="flex-1 truncate">{label}</span>
      {count != null && <span className="text-xs text-zinc-400 tabular-nums">{count}</span>}
    </label>
  )
}

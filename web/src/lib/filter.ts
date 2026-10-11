import type { Filters, Role, Tracked } from '../types'
import { ageDays, effectiveDate } from './format'

const WINDOW_DAYS = { any: Infinity, '24h': 1, '7d': 7, '30d': 30 } as const

export function applyFilters(
  roles: Role[],
  f: Filters,
  tracked: Record<string, Tracked>,
  newCutoff: string,
): Role[] {
  const q = f.q.trim().toLowerCase()
  const terms = q ? q.split(/\s+/) : []
  const maxAge = WINDOW_DAYS[f.posted]
  const now = Date.now()

  const out = roles.filter((r) => {
    const status = tracked[r.id]?.status
    if (f.status === 'active' && status === 'hidden') return false
    if (f.status === 'untracked' && status) return false
    if (f.status !== 'active' && f.status !== 'untracked' && status !== f.status) return false

    if (terms.length) {
      const hay = `${r.title} ${r.company} ${r.locations.join(' ')}`.toLowerCase()
      if (!terms.every((t) => hay.includes(t))) return false
    }
    if (maxAge !== Infinity && (r.postedApprox || ageDays(r, now) > maxAge)) return false
    if (f.categories.length && !r.categories.some((c) => f.categories.includes(c))) return false
    if (f.levels.length && !f.levels.includes(r.level)) return false
    if (f.regions.length && !r.regions.some((x) => f.regions.includes(x))) return false
    if (f.companies.length && !f.companies.includes(r.company)) return false
    if ((f.salaryOnly || f.minSalary) && r.salaryMax == null) return false
    if (f.minSalary && (r.salaryMax ?? 0) < f.minSalary) return false
    if (f.newOnly && r.firstSeen <= newCutoff) return false
    return true
  })

  const byDate = (a: Role, b: Role) => effectiveDate(b).getTime() - effectiveDate(a).getTime()
  if (f.sort === 'salary') {
    out.sort((a, b) => (b.salaryMax ?? -1) - (a.salaryMax ?? -1) || byDate(a, b))
  } else if (f.sort === 'company') {
    out.sort((a, b) => a.company.localeCompare(b.company) || byDate(a, b))
  } else {
    out.sort((a, b) => byDate(a, b) || b.firstSeen.localeCompare(a.firstSeen))
  }
  return out
}

export function countBy(roles: Role[], key: (r: Role) => string[]): Map<string, number> {
  const m = new Map<string, number>()
  for (const r of roles) for (const k of key(r)) m.set(k, (m.get(k) ?? 0) + 1)
  return m
}

import type { Role } from '../types'

const DAY = 24 * 60 * 60 * 1000

/** Posting date if the board gave one, else when the tracker first saw the role. */
export function effectiveDate(role: Role): Date {
  return new Date(role.posted ? `${role.posted}T12:00:00Z` : role.firstSeen)
}

export function ageDays(role: Role, now = Date.now()): number {
  return Math.max(0, Math.floor((now - effectiveDate(role).getTime()) / DAY))
}

export function postedLabel(role: Role): string {
  if (role.postedApprox) return '30+ days'
  const d = ageDays(role)
  if (d === 0) return 'Today'
  if (d === 1) return 'Yesterday'
  if (d < 30) return `${d}d ago`
  if (d < 365) return `${Math.floor(d / 30)}mo ago`
  return `${Math.floor(d / 365)}y ago`
}

export function timeAgo(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 60) return `${Math.max(1, mins)}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 48) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}

export function money(n: number): string {
  return n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(1)}M` : `$${Math.round(n / 1000)}K`
}

export function salaryLabel(role: Role): string {
  if (role.salaryMin == null || role.salaryMax == null) return /\/hr$/.test(role.salary) ? role.salary : ''
  return role.salaryMin === role.salaryMax
    ? money(role.salaryMin)
    : `${money(role.salaryMin)} – ${money(role.salaryMax)}`
}

const AVATAR_COLORS = [
  'bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300',
  'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
  'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
  'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
  'bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300',
  'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300',
  'bg-teal-100 text-teal-700 dark:bg-teal-950 dark:text-teal-300',
  'bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300',
]

export function avatarColor(name: string): string {
  let h = 0
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}

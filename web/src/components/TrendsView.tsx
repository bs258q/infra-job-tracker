import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { countBy } from '../lib/filter'
import type { HistoryPoint, Role } from '../types'

const AXIS = { fontSize: 12, fill: '#71717a' }
const TOOLTIP = { contentStyle: { borderRadius: 8, fontSize: 12 } }

export function TrendsView({ roles, history }: { roles: Role[]; history: HistoryPoint[] }) {
  const topCompanies = useMemo(
    () =>
      [...countBy(roles, (r) => [r.company]).entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 15)
        .map(([name, count]) => ({ name, count })),
    [roles],
  )
  const categories = useMemo(
    () => [...countBy(roles, (r) => r.categories).entries()].sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count })),
    [roles],
  )
  const withPay = roles.filter((r) => r.salaryMax != null)
  const medianTop = useMemo(() => {
    const xs = withPay.map((r) => r.salaryMax!).sort((a, b) => a - b)
    return xs.length ? xs[Math.floor(xs.length / 2)] : 0
  }, [withPay])

  // Biggest movers: open-role change vs. the oldest snapshot within the last 7 days.
  const movers = useMemo(() => {
    if (history.length < 2) return []
    const latest = history[history.length - 1]
    const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10)
    const base = history.find((h) => h.date >= weekAgo) ?? history[0]
    if (base === latest) return []
    const names = new Set([...Object.keys(latest.byCompany), ...Object.keys(base.byCompany)])
    return [...names]
      .map((name) => ({ name, delta: (latest.byCompany[name] ?? 0) - (base.byCompany[name] ?? 0) }))
      .filter((m) => m.delta !== 0)
      .sort((a, b) => b.delta - a.delta)
      .slice(0, 8)
  }, [history])

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Open matching roles" value={roles.length.toLocaleString()} />
        <Stat label="Companies hiring" value={String(new Set(roles.map((r) => r.company)).size)} />
        <Stat label="Roles with listed pay" value={`${Math.round((withPay.length / Math.max(1, roles.length)) * 100)}%`} />
        <Stat label="Median top of pay range" value={medianTop ? `$${Math.round(medianTop / 1000)}K` : '—'} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Open roles over time">
          {history.length < 2 ? (
            <Empty />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={history}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" />
                <XAxis dataKey="date" tick={AXIS} tickFormatter={(d: string) => d.slice(5)} />
                <YAxis tick={AXIS} width={40} />
                <Tooltip {...TOOLTIP} />
                <Line type="monotone" dataKey="total" name="Open roles" stroke="#4f46e5" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="New roles per day">
          {history.filter((h) => h.new > 0).length === 0 ? (
            <Empty />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={history}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" />
                <XAxis dataKey="date" tick={AXIS} tickFormatter={(d: string) => d.slice(5)} />
                <YAxis tick={AXIS} width={40} allowDecimals={false} />
                <Tooltip {...TOOLTIP} />
                <Bar dataKey="new" name="New roles" fill="#10b981" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Most open roles by company">
          <ResponsiveContainer width="100%" height={420}>
            <BarChart data={topCompanies} layout="vertical" margin={{ left: 20 }}>
              <XAxis type="number" tick={AXIS} allowDecimals={false} />
              <YAxis type="category" dataKey="name" tick={AXIS} width={120} interval={0} />
              <Tooltip {...TOOLTIP} />
              <Bar dataKey="count" name="Open roles" fill="#4f46e5" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <div className="space-y-6">
          <Card title="Roles by type">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={categories} layout="vertical" margin={{ left: 20 }}>
                <XAxis type="number" tick={AXIS} allowDecimals={false} />
                <YAxis type="category" dataKey="name" tick={AXIS} width={140} interval={0} />
                <Tooltip {...TOOLTIP} />
                <Bar dataKey="count" name="Roles" fill="#0ea5e9" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>

          <Card title="Biggest changes this week">
            {movers.length === 0 ? (
              <Empty />
            ) : (
              <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
                {movers.map((m) => (
                  <li key={m.name} className="flex justify-between py-1.5">
                    <span>{m.name}</span>
                    <span className={`font-medium tabular-nums ${m.delta > 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                      {m.delta > 0 ? '+' : ''}
                      {m.delta}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="text-xs text-zinc-500 dark:text-zinc-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <h3 className="mb-3 text-sm font-semibold">{title}</h3>
      {children}
    </div>
  )
}

function Empty() {
  return <p className="py-12 text-center text-sm text-zinc-400">Builds up as the tracker runs each day.</p>
}

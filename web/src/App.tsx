import { AlertTriangle, BarChart3, KanbanSquare, List } from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { PipelineView } from './components/PipelineView'
import { RolesView } from './components/RolesView'
import { timeAgo } from './lib/format'
import { useLocalStorage, useNewCutoff } from './lib/storage'
import { DEFAULT_FILTERS, type HistoryPoint, type JobsData, type Role, type Status, type Tracked } from './types'

const TrendsView = lazy(() => import('./components/TrendsView').then((m) => ({ default: m.TrendsView })))

type Tab = 'roles' | 'pipeline' | 'trends'

export default function App() {
  const [data, setData] = useState<JobsData | null>(null)
  const [history, setHistory] = useState<HistoryPoint[]>([])
  const [error, setError] = useState('')
  const [tab, setTab] = useState<Tab>(() => (location.hash.slice(1) as Tab) || 'roles')

  const [filters, setFilters] = useLocalStorage('infra-roles:filters', DEFAULT_FILTERS)
  const [tracked, setTracked] = useLocalStorage<Record<string, Tracked>>('infra-roles:tracked', {})
  const [newCutoff, markAllSeen] = useNewCutoff()

  useEffect(() => {
    Promise.all([
      fetch('/data/jobs.json', { cache: 'no-cache' }).then((r) => (r.ok ? r.json() : Promise.reject(r.statusText))),
      fetch('/data/history.json', { cache: 'no-cache' }).then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([jobs, hist]) => {
        setData(jobs)
        setHistory(hist)
      })
      .catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    window.location.hash = tab
  }, [tab])

  const setStatus = (role: Role, status: Status | null) => {
    const next = { ...tracked }
    if (status) {
      next[role.id] = {
        ...next[role.id],
        status,
        updatedAt: new Date().toISOString(),
        company: role.company,
        title: role.title,
        url: role.url,
      }
    } else {
      delete next[role.id]
    }
    setTracked(next)
  }

  const liveIds = useMemo(() => new Set(data?.roles.map((r) => r.id)), [data])
  const pipelineCount = Object.values(tracked).filter((t) => t.status !== 'hidden').length
  const errorCount = data ? Object.keys(data.errors).length : 0

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-zinc-200 bg-white/85 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/85">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <img src="/favicon.svg" alt="" className="size-7" />
            <div>
              <h1 className="leading-tight font-semibold">Infra Roles</h1>
              {data && (
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  Updated {timeAgo(data.generatedAt)} · {data.companiesTracked} companies · Bay Area + US remote
                </p>
              )}
            </div>
          </div>

          <nav className="flex gap-1 rounded-lg bg-zinc-100 p-1 text-sm dark:bg-zinc-900">
            <TabButton active={tab === 'roles'} onClick={() => setTab('roles')} icon={<List className="size-4" />} label="Roles" badge={data?.roles.length} />
            <TabButton active={tab === 'pipeline'} onClick={() => setTab('pipeline')} icon={<KanbanSquare className="size-4" />} label="Pipeline" badge={pipelineCount || undefined} />
            <TabButton active={tab === 'trends'} onClick={() => setTab('trends')} icon={<BarChart3 className="size-4" />} label="Trends" />
          </nav>

          {errorCount > 0 && (
            <span
              title={Object.entries(data!.errors).map(([c, e]) => `${c}: ${e}`).join('\n')}
              className="ml-auto inline-flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400"
            >
              <AlertTriangle className="size-3.5" /> {errorCount} board{errorCount > 1 ? 's' : ''} failed to load
            </span>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {error && <p className="rounded-lg bg-rose-50 p-4 text-sm text-rose-700">Couldn't load jobs data: {error}</p>}
        {!data && !error && <p className="py-24 text-center text-sm text-zinc-500">Loading roles…</p>}
        {data && tab === 'roles' && (
          <RolesView
            roles={data.roles}
            filters={filters}
            setFilters={setFilters}
            tracked={tracked}
            setStatus={setStatus}
            newCutoff={newCutoff}
            markAllSeen={markAllSeen}
          />
        )}
        {data && tab === 'pipeline' && <PipelineView tracked={tracked} setTracked={setTracked} liveIds={liveIds} />}
        {data && tab === 'trends' && (
          <Suspense fallback={<p className="py-24 text-center text-sm text-zinc-500">Loading charts…</p>}>
            <TrendsView roles={data.roles} history={history} />
          </Suspense>
        )}
      </main>
    </div>
  )
}

function TabButton({ active, onClick, icon, label, badge }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string; badge?: number }) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 transition ${
        active ? 'bg-white font-medium text-zinc-900 shadow-sm dark:bg-zinc-800 dark:text-zinc-100' : 'text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100'
      }`}
    >
      {icon}
      {label}
      {badge != null && <span className="text-xs text-zinc-400 tabular-nums">{badge.toLocaleString()}</span>}
    </button>
  )
}

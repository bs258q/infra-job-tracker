import { Download, Upload } from 'lucide-react'
import { useRef } from 'react'
import { avatarColor } from '../lib/format'
import { STATUS_LABEL, type Status, type Tracked } from '../types'
import { StatusSelect } from './StatusSelect'

const COLUMNS: Status[] = ['saved', 'applied', 'interviewing', 'offer', 'rejected']

type Props = {
  tracked: Record<string, Tracked>
  setTracked: (t: Record<string, Tracked>) => void
  liveIds: Set<string>
}

export function PipelineView({ tracked, setTracked, liveIds }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  const entries = Object.entries(tracked)

  const update = (id: string, patch: Partial<Tracked> | null) => {
    const next = { ...tracked }
    if (patch === null) delete next[id]
    else next[id] = { ...next[id], ...patch, updatedAt: new Date().toISOString() }
    setTracked(next)
  }

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(tracked, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `infra-roles-pipeline-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const importJson = async (file: File) => {
    try {
      const data = JSON.parse(await file.text()) as Record<string, Tracked>
      setTracked({ ...tracked, ...data })
    } catch {
      alert('That file is not a pipeline export.')
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <p className="mr-auto text-sm text-zinc-500 dark:text-zinc-400">
          Saved in this browser. Export to back up or move to another device.
        </p>
        <button onClick={exportJson} className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm hover:border-indigo-400 dark:border-zinc-700 dark:bg-zinc-900">
          <Download className="size-4" /> Export
        </button>
        <button onClick={() => fileRef.current?.click()} className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm hover:border-indigo-400 dark:border-zinc-700 dark:bg-zinc-900">
          <Upload className="size-4" /> Import
        </button>
        <input ref={fileRef} type="file" accept="application/json" hidden onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])} />
      </div>

      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-5">
        {COLUMNS.map((col) => {
          const items = entries.filter(([, t]) => t.status === col).sort((a, b) => b[1].updatedAt.localeCompare(a[1].updatedAt))
          return (
            <div key={col} className="rounded-xl border border-zinc-200 bg-zinc-100/60 p-2 dark:border-zinc-800 dark:bg-zinc-900/40">
              <h3 className="flex items-center justify-between px-2 py-1 text-sm font-semibold">
                {STATUS_LABEL[col]}
                <span className="text-xs font-normal text-zinc-500 tabular-nums">{items.length}</span>
              </h3>
              <div className="mt-1 space-y-2">
                {items.map(([id, t]) => (
                  <div key={id} className="rounded-lg border border-zinc-200 bg-white p-3 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
                    <div className="flex items-start gap-2">
                      <div className={`flex size-6 shrink-0 items-center justify-center rounded text-xs font-semibold ${avatarColor(t.company)}`}>
                        {t.company.slice(0, 1).toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <a href={t.url} target="_blank" rel="noreferrer" className="text-sm leading-snug font-medium hover:text-indigo-600 hover:underline dark:hover:text-indigo-400">
                          {t.title}
                        </a>
                        <div className="text-xs text-zinc-500">{t.company}</div>
                      </div>
                    </div>
                    {!liveIds.has(id) && <div className="mt-2 text-xs text-amber-700 dark:text-amber-400">No longer listed</div>}
                    <textarea
                      defaultValue={t.note ?? ''}
                      onBlur={(e) => e.target.value !== (t.note ?? '') && update(id, { note: e.target.value })}
                      placeholder="Notes — recruiter, dates, referral…"
                      rows={2}
                      className="mt-2 w-full resize-none rounded border border-zinc-200 bg-transparent px-2 py-1 text-xs outline-none focus:border-indigo-400 dark:border-zinc-700"
                    />
                    <div className="mt-1 flex items-center justify-between">
                      <span className="text-[11px] text-zinc-400">{new Date(t.updatedAt).toLocaleDateString()}</span>
                      <StatusSelect value={t.status} onChange={(s) => update(id, s ? { status: s } : null)} />
                    </div>
                  </div>
                ))}
                {items.length === 0 && <p className="px-2 py-4 text-center text-xs text-zinc-400">Nothing here yet</p>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

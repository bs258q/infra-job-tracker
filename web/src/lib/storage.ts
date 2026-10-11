import { useCallback, useEffect, useState } from 'react'

export function useLocalStorage<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw ? { ...initialObject(initial), ...JSON.parse(raw) } : initial
    } catch {
      return initial
    }
  })

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(value))
  }, [key, value])

  return [value, setValue] as const
}

// Merging keeps newly added filter fields when an older saved object is loaded.
function initialObject<T>(initial: T) {
  return initial && typeof initial === 'object' && !Array.isArray(initial) ? initial : {}
}

const SESSION_GAP_MS = 2 * 60 * 60 * 1000

/** localStorage key prefix per profile; "infra-roles" predates profiles and is kept so saved state survives. */
export const storagePrefix = (profileId: string) => `${profileId}-roles`

/**
 * Roles first seen after the cutoff count as "new since last visit".
 * A visit starts after 2h of inactivity, so refreshing doesn't clear highlights.
 */
export function useNewCutoff(prefix: string) {
  const LAST_VISIT = `${prefix}:last-visit`
  const CUTOFF = `${prefix}:new-cutoff`
  const [cutoff, setCutoff] = useState<string>(() => {
    const now = Date.now()
    const last = Number(localStorage.getItem(LAST_VISIT) || 0)
    let value = localStorage.getItem(CUTOFF)
    if (last && now - last > SESSION_GAP_MS) {
      value = new Date(last).toISOString()
    }
    value ??= new Date(now).toISOString()
    localStorage.setItem(CUTOFF, value)
    localStorage.setItem(LAST_VISIT, String(now))
    return value
  })

  useEffect(() => {
    const touch = () => localStorage.setItem(LAST_VISIT, String(Date.now()))
    const id = window.setInterval(touch, 60_000)
    window.addEventListener('beforeunload', touch)
    return () => {
      window.clearInterval(id)
      window.removeEventListener('beforeunload', touch)
    }
  }, [LAST_VISIT])

  const markAllSeen = useCallback(() => {
    const now = new Date().toISOString()
    localStorage.setItem(CUTOFF, now)
    setCutoff(now)
  }, [CUTOFF])

  return [cutoff, markAllSeen] as const
}

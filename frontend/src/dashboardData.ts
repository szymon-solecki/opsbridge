import { useEffect, useState } from 'react'
import { apiFetch } from './session'

export async function read<T>(path: string, signal: AbortSignal, base = '/api/dashboard'): Promise<T> {
  const response = await apiFetch(base + path, { signal })
  if (!response.ok) throw new Error('Dashboard request failed')
  return response.json()
}

export function useResource<T>(path: string | undefined, revision: number, base = '/api/dashboard') {
  const [state, setState] = useState<{ path: string; data?: T; error?: boolean; updated?: string }>()
  useEffect(() => {
    if (!path) return
    const request = new AbortController()
    setState(previous => previous?.path === path ? { ...previous, error: false } : undefined)
    read<T>(path, request.signal, base)
      .then(data => { if (!request.signal.aborted) setState({ path, data, updated: new Date().toISOString() }) })
      .catch(() => { if (!request.signal.aborted) setState(previous => ({ ...(previous?.path === path ? previous : {}), path, error: true })) })
    return () => request.abort()
  }, [base, path, revision])
  return state?.path === path ? state : undefined
}


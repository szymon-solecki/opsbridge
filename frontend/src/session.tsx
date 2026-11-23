import { type ReactNode, useEffect, useState } from 'react'

type Role = 'VIEWER' | 'OPERATOR' | 'ADMIN'
type Account = { id: string; username: string; role: Role; active: boolean }
export type Session = Omit<Account, 'active'> & { csrf: string; expires_at: string }
export type SessionControls = { signOut: () => void; signingOut: boolean; sessionError: string }
let csrf = ''
export const sessionExpired = () => window.dispatchEvent(new Event('opsbridge:expired'))

export async function apiFetch(path: string, init?: RequestInit) {
  const headers = new Headers(init?.headers)
  const method = init?.method ?? 'GET'
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrf) headers.set('X-CSRF-Token', csrf)
  const response = await fetch(path, { ...init, headers })
  if (response.status === 401 && path !== '/api/auth/session') sessionExpired()
  if (response.status === 403) window.dispatchEvent(new Event('opsbridge:forbidden'))
  return response
}

export function SessionGate({ children }: { children: (session: Session, controls: SessionControls) => ReactNode }) {
  const [session, setSession] = useState<Session | null | undefined>()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  function accept(next: Session | null) {
    csrf = next?.csrf ?? ''
    setSession(next)
  }

  useEffect(() => {
    const controller = new AbortController()
    const expired = () => { accept(null); setError('Your session expired. Sign in again.') }
    const forbidden = () => setError('Permission denied.')
    window.addEventListener('opsbridge:expired', expired)
    window.addEventListener('opsbridge:forbidden', forbidden)
    void apiFetch('/api/auth/session', { signal: controller.signal }).then(async response => {
      const next = response.ok ? await response.json() : null
      if (controller.signal.aborted) return
      accept(next)
      if (!response.ok && response.status !== 401) setError('The sign-in service is unavailable.')
    }).catch(() => {
      if (!controller.signal.aborted) { accept(null); setError('The sign-in service is unavailable.') }
    })
    return () => {
      controller.abort()
      window.removeEventListener('opsbridge:expired', expired)
      window.removeEventListener('opsbridge:forbidden', forbidden)
    }
  }, [])

  useEffect(() => {
    if (!session) return
    const expiry = Date.parse(session.expires_at)
    if (!Number.isFinite(expiry)) return
    const timer = window.setTimeout(sessionExpired, Math.max(0, expiry - Date.now()))
    return () => window.clearTimeout(timer)
  }, [session])

  if (session === undefined) return <main><p role="status">Checking your session…</p></main>
  if (!session) return <main className="sign-in"><section className="panel">
    <h1>Sign in to OpsBridge</h1>
    <form onSubmit={async event => {
      event.preventDefault()
      setPending(true); setError('')
      try {
        const response = await fetch('/api/auth/login', {
          method: 'POST', body: JSON.stringify({ username, password }),
          headers: { 'Content-Type': 'application/json', 'X-OpsBridge-Login': '1' },
        })
        if (response.ok) { accept(await response.json()); setPassword('') }
        else setError(response.status === 429 ? 'Too many attempts. Try again later.' : 'Sign-in failed. Check your credentials.')
      } catch {
        setError('The sign-in service is unavailable.')
      } finally {
        setPending(false)
      }
    }}>
      <label>Username <input value={username} onChange={event => setUsername(event.target.value)}
        autoComplete="username" required maxLength={64}/></label>
      <label>Password <input value={password} onChange={event => setPassword(event.target.value)}
        type="password" autoComplete="current-password" required maxLength={256}/></label>
      <button disabled={pending}>{pending ? 'Signing in…' : 'Sign in'}</button>
    </form>
    {error && <p role="alert">{error}</p>}
  </section></main>
  async function signOut() {
    if (pending) return
    setPending(true); setError('')
    try {
      const response = await apiFetch('/api/auth/logout', { method: 'POST' })
      if (response.ok || response.status === 401) { accept(null); setError('') }
      else setError('Could not sign out. Try again.')
    } catch {
      setError('Could not sign out. Try again.')
    } finally {
      setPending(false)
    }
  }
  return children(session, { signOut, signingOut: pending, sessionError: error })
}

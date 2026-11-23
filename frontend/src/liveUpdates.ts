import { useEffect, useState } from 'react'
import { sessionExpired } from './session'

const pollEveryMs = 15_000
const refreshIntervalMs = 2_000

export function useLiveUpdates(refresh: () => void) {
  const [connection, setConnection] = useState('Connecting')

  useEffect(() => {
    let stream: EventSource | undefined
    let refreshTimer: ReturnType<typeof setTimeout> | undefined
    let poll: ReturnType<typeof setInterval> | undefined
    let deadline: ReturnType<typeof setTimeout> | undefined
    let reconnect: ReturnType<typeof setTimeout> | undefined

    function scheduleRefresh() {
      refreshTimer ??= setTimeout(() => {
        refreshTimer = undefined
        refresh()
      }, refreshIntervalMs)
    }

    function fallback() {
      setConnection('Polling fallback')
      poll ??= setInterval(scheduleRefresh, pollEveryMs)
    }

    function watchForSignals(timeout: number) {
      clearTimeout(deadline)
      deadline = setTimeout(() => {
        fallback()
        stream?.close()
        reconnect = setTimeout(connect, 3_000)
      }, timeout)
    }

    function connect() {
      stream = new EventSource('/api/dashboard/stream')
      watchForSignals(5_000)
      stream.addEventListener('invalidate', () => {
        setConnection('Live')
        clearInterval(poll)
        poll = undefined
        watchForSignals(25_000)
        scheduleRefresh()
      })
      stream.addEventListener('heartbeat', () => watchForSignals(25_000))
      stream.addEventListener('unavailable', fallback)
      stream.addEventListener('session-expired', sessionExpired)
      stream.onerror = fallback
    }

    if (typeof EventSource === 'function') connect()
    else fallback()

    return () => {
      stream?.close()
      clearTimeout(deadline)
      clearTimeout(reconnect)
      clearTimeout(refreshTimer)
      clearInterval(poll)
    }
  }, [refresh])

  return connection
}

import { Activity, ExternalLink, Layers3, Radio } from 'lucide-react'
import { useEffect, useState } from 'react'
import { RouteLink, routeId } from './navigation'
import { useResource } from './dashboardData'
import { timestamp, type ActivityPage, type Overview } from './Operations'
import './operational-experience.css'

function monitoringUrl(value: unknown) {
  if (typeof value !== 'string' || !/^https?:\/\//.test(value)) return
  try {
    const url = new URL(value)
    if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) return url.href
  } catch {
    return
  }
}

export function Monitoring({ connection, revision, refresh }: { connection: string; revision: number; refresh: () => void }) {
  const summary = useResource<Overview>('/overview', revision)
  const activity = useResource<ActivityPage>('/activity?limit=1', revision)
  const [destinations, setDestinations] = useState<{ grafana?: string; prometheus?: string }>()
  useEffect(() => {
    const request = new AbortController()
    void fetch('/opsbridge-monitoring.json', { signal: request.signal, cache: 'no-store' })
      .then(response => response.ok ? response.json() : null)
      .then(data => {
        if (!request.signal.aborted) setDestinations({ grafana: monitoringUrl(data?.grafana), prometheus: monitoringUrl(data?.prometheus) })
      }).catch(() => { if (!request.signal.aborted) setDestinations({}) })
    return () => request.abort()
  }, [])
  const counts = summary?.data?.counts
  const latest = activity?.data?.items[0]
  const lastRead = summary?.updated
  const run = routeId(latest?.payload?.reconciliation_run_id ?? null)
  const delivery = routeId(latest?.delivery_expectation_id ?? null)
  return <div className="experience-layout monitoring-workspace">
    <section className="experience-panel monitoring-observation" aria-labelledby="monitor-title">
      <h2 id="monitor-title"><Radio size={19} aria-hidden="true"/> Workspace observation</h2>
      <dl><div><dt>Browser updates</dt><dd>{connection}</dd></div>
        <div><dt>Dashboard API</dt><dd>{summary?.error ? 'Unavailable' : lastRead ? 'Last read succeeded' : 'Checking…'}</dd></div>
        <div><dt>Last successful overview read</dt><dd>{lastRead ? timestamp(lastRead) + ' UTC' : 'Unavailable'}</dd></div>
        <div><dt>Database, schema and broker readiness</dt><dd>Unavailable in workspace</dd></div></dl>
      <p>The browser update channel and overview read describe this workspace. Service readiness and worker telemetry are measured in the monitoring stack.</p>
      <button className="command-button" onClick={refresh}>Refresh observations</button>
    </section>
    <aside className="experience-panel monitoring-tools" aria-labelledby="tools-title">
      <h2 id="tools-title"><ExternalLink size={19} aria-hidden="true"/> Monitoring tools</h2>
      {(['grafana', 'prometheus'] as const).map(key => <div key={key}>
        <h3>{key === 'grafana' ? 'Grafana' : 'Prometheus'}</h3>
        <p>{key === 'grafana' ? 'Service dashboards, operational trends and worker readiness.' : 'Scrape targets and queue, API and worker metrics.'}</p>
        {destinations?.[key] ? <a className="command-text-link" href={destinations[key]} target="_blank" rel="noopener noreferrer">
          Open {key === 'grafana' ? 'Grafana' : 'Prometheus'} (new tab)</a>
          : <p className="experience-caption">{destinations ? 'Destination not configured or invalid' : 'Checking configuration…'}</p>}
      </div>)}
      <details><summary>Deployment configuration</summary><p>Set the public browser destinations with <code>OPSBRIDGE_GRAFANA_URL</code> and <code>OPSBRIDGE_PROMETHEUS_URL</code> on the dashboard container.</p></details>
    </aside>
    <section className="experience-panel" aria-labelledby="monitor-processing">
      <h2 id="monitor-processing"><Layers3 size={19} aria-hidden="true"/> Delivery processing</h2>
      <p>{summary?.error && counts ? 'Last successful snapshot. Refresh to check for updates.' : 'Current delivery states from the operational overview.'}</p>
      <dl><div><dt>Received</dt><dd>{counts ? counts.RECEIVED ?? 0 : 'Unavailable'}</dd></div>
        <div><dt>Processing</dt><dd>{counts ? counts.PROCESSING ?? 0 : 'Unavailable'}</dd></div>
        <div><dt>Processing failed</dt><dd>{counts ? counts.PROCESSING_FAILED ?? 0 : 'Unavailable'}</dd></div>
        <div><dt>Outbox and broker backlog</dt><dd>Unavailable in workspace</dd></div></dl>
      <RouteLink className="command-text-link" href="/deliveries">View delivery queue</RouteLink>
    </section>
    <section className="experience-panel" aria-labelledby="monitor-activity">
      <h2 id="monitor-activity"><Activity size={19} aria-hidden="true"/> Last recorded activity</h2>
      {latest ? <><p><strong>{latest.summary}</strong></p><p>{timestamp(latest.occurred_at)} UTC · Activity projection</p>
        {activity?.error && <p>The latest activity refresh is unavailable.</p>}
        {run ? <RouteLink className="command-text-link" href={'/reconciliation/runs/' + run}>Open run evidence</RouteLink>
          : delivery && <RouteLink className="command-text-link" href={'/deliveries/' + delivery} detail>Open delivery evidence</RouteLink>}</>
        : <p>{activity?.error ? 'Activity is unavailable.' : activity?.data ? 'No projected activity is recorded.' : 'Loading activity…'}</p>}
      <p><RouteLink className="command-text-link" href="/overview/activity">View activity history</RouteLink></p>
    </section>
  </div>
}

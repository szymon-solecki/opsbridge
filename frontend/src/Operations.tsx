import type { ReactNode } from 'react'
import { Activity, CalendarClock, CheckCircle2, CircleAlert, GitCompareArrows, ListChecks, Search } from 'lucide-react'
import { RouteLink, routeId } from './navigation'
import { SectionState, SeverityIndicator } from './Shell'

export const labels = {
  EXPECTED: 'Expected', RECEIVED: 'Received', VALIDATION_FAILED: 'Validation failed',
  PROCESSING: 'Processing', PROCESSING_FAILED: 'Processing failed', COMPLETED: 'Completed',
} as const
export type Status = keyof typeof labels
export type Integration = { id: string; name: string; source_name: string; active: boolean }
type Metrics = { total: number; received: number; validation_failed: number; pending: number; overdue: number; breached: number; on_time: number }
export type Overview = {
  integrations: Integration[]
  counts?: Partial<Record<Status, number>>
  as_of?: string
  metrics?: Metrics
  activity?: Record<string, Metrics & { failed: number; active_incidents?: number; last_arrival?: string | null }>
  incidents_by_type?: Record<string, number>
  reprocessing_enabled?: boolean
}
export type Attention = {
  delivery_id: string; integration_id: string; delivery_type: string; business_date: string; status: Status
  kind: string; key: string; reason: string | null; action: string; deadline_at: string; at: string | null
  recorded_incident: boolean
}
type ActivityItem = {
  source_event_id: string; delivery_expectation_id: string; event_type: string; summary: string; occurred_at: string
  payload: null | { filename?: string; error_code?: string; attempt_series?: number; attempt_count_in_series?: number
    reconciliation_run_id?: string }
}
export type ActivityPage = { items: ActivityItem[]; next_before_at: string | null; next_before_id: string | null }
type Resource<T> = { data?: T; error?: boolean }

export const problemLabels: Record<string, string> = {
  MISSING_FILE: 'Missing or overdue', VALIDATION_FAILURE: 'Validation failure',
  PROCESSING_FAILURE: 'Processing failure', SOURCE_DELIVERY_ID_CONFLICT: 'Source delivery ID conflict',
  RECONCILIATION_FAILURE: 'Reconciliation failure',
}
// The attention response omits severity. Keep this display mapping aligned with the backend's incident policy.
const incidentSeverity: Readonly<Record<string, string>> = {
  SOURCE_DELIVERY_ID_CONFLICT: 'CRITICAL', PROCESSING_FAILURE: 'HIGH', MISSING_FILE: 'HIGH',
  RECONCILIATION_FAILURE: 'HIGH', VALIDATION_FAILURE: 'MEDIUM',
}
const bands = ['Critical incidents', 'High-priority incidents', 'Overdue or missing', 'Other operational issues']
export const queueLimit = 40
const previewLimit = 5

export const timestamp = (value: string) => new Intl.DateTimeFormat('en-GB', {
  dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC',
}).format(new Date(value))
export const title = (value: string) => value.toLowerCase().replaceAll('_', ' ').replace(/^./, c => c.toUpperCase())
const count = new Intl.NumberFormat('en-GB')
const number = (value?: number) => typeof value === 'number' ? count.format(value) : '—'

export function Badge({ status }: { status: Status }) {
  return <span className={'badge ' + status.toLowerCase()}>{labels[status]}</span>
}

function severity(item: Attention) {
  return item.recorded_incident ? incidentSeverity[item.kind] : undefined
}

function band(item: Attention) {
  const priority = severity(item)
  return priority === 'CRITICAL' ? 0 : priority === 'HIGH' ? 1 : !item.recorded_incident && item.kind === 'MISSING_FILE' ? 2 : 3
}

function priorityItems(items: Attention[]) {
  return items.slice(0, queueLimit).sort((a, b) => band(a) - band(b))
}

function DateTime({ value }: { value: string }) {
  return <time dateTime={value}>{timestamp(value)} UTC</time>
}

function WorkItem({ item, integration, preview = false }: { item: Attention; integration: string; preview?: boolean }) {
  const priority = severity(item)
  const reason = item.reason && (/^[A-Z0-9_]+$/.test(item.reason) ? title(item.reason) : item.reason)
  const reconciliation = item.kind === 'RECONCILIATION_FAILURE'
  const heading = reconciliation ? 'Reconciliation exception' : problemLabels[item.kind] ?? title(item.kind)
  const Heading = preview ? 'h3' : 'h4'
  const investigation = item.recorded_incident ? reconciliation ? 'Review reconciliation incident' : 'Investigate incident' : 'View delivery evidence'
  const deliveryPath = '/deliveries/' + item.delivery_id + (item.recorded_incident ? '/incidents/' + item.key : '')
  const showEventTime = item.at && (!preview || item.kind !== 'MISSING_FILE')
  const timeLabel = !item.recorded_incident && item.kind === 'MISSING_FILE' ? 'Deadline passed'
    : showEventTime ? item.recorded_incident ? 'Incident opened' : 'Failure recorded' : 'Delivery deadline'

  return <li className="ops-work-item" data-priority={band(item)}>
    <div className="ops-work-title">
      <div className="ops-work-flags">
        {priority ? <SeverityIndicator severity={priority}/> : <span className="ops-incident-state">{item.recorded_incident ? 'Severity unavailable' : 'Needs attention'}</span>}
        {!preview && <span className="ops-incident-state">{item.recorded_incident ? 'Active incident' : 'Detected problem'}</span>}
      </div>
      <Heading>{heading}</Heading>
      <p>{integration} · {title(item.delivery_type)}</p>
      {!preview && <div className="ops-delivery-status">Delivery status <Badge status={item.status}/></div>}
    </div>
    <div className="ops-work-evidence">
      <p>{reason || 'Review the available delivery evidence for the cause.'}</p>
      {!preview && <p className="ops-next"><strong>Next step</strong> {item.action}</p>}
    </div>
    <div className="ops-work-action">
      <span>{timeLabel}</span>
      <DateTime value={showEventTime ? item.at! : item.deadline_at}/>
      {!preview && showEventTime && timeLabel !== 'Deadline passed' && <small>Deadline <DateTime value={item.deadline_at}/></small>}
      <RouteLink className="command-button ops-evidence-link" href={deliveryPath} detail>{investigation}</RouteLink>
    </div>
  </li>
}

function Snapshot({ overview }: { overview: Overview }) {
  const totals = overview.incidents_by_type
  const metrics = overview.metrics
  const statuses = overview.counts
  const active = totals && Object.values(totals).reduce((sum, value) => sum + value, 0)
  const critical = totals?.SOURCE_DELIVERY_ID_CONFLICT ?? 0
  const high = Object.entries(totals ?? {}).reduce((sum, [kind, value]) => sum + (incidentSeverity[kind] === 'HIGH' ? value : 0), 0)
  const onTime = metrics?.received ? Math.round(metrics.on_time * 100 / metrics.received) + '%' : '—'
  return <section className="ops-snapshot" aria-labelledby="shift-snapshot">
    <div className="ops-snapshot-heading"><h2 id="shift-snapshot">Operational snapshot</h2>
      <span>All integrations{overview.as_of && <> · <DateTime value={overview.as_of}/></>}</span></div>
    <div className="ops-metrics">
      <div><h3><CircleAlert aria-hidden="true"/> Active incidents</h3><strong>{number(active)}</strong>
        <p>{totals ? <>{number(critical)} critical · {number(high)} high priority</> : 'Incident totals unavailable'}</p></div>
      <div><h3><CalendarClock aria-hidden="true"/> Currently overdue</h3><strong>{number(metrics?.overdue)}</strong>
        <p>No recorded arrival by deadline</p></div>
      <div><h3><Activity aria-hidden="true"/> On-time receipt</h3><strong>{onTime}</strong>
        <p>{metrics?.received ? <>{number(metrics.on_time)} of {number(metrics.received)} recorded arrivals</> : 'No recorded arrivals for this rate'}</p></div>
      <div><h3><CheckCircle2 aria-hidden="true"/> Completed deliveries</h3><strong>{number(statuses && (statuses.COMPLETED ?? 0))}</strong>
        <p>{statuses ? <>{number(statuses.PROCESSING ?? 0)} processing · {number(statuses.PROCESSING_FAILED ?? 0)} processing failed</> : 'Processing totals unavailable'}</p></div>
    </div>
  </section>
}

function IntegrationHealth({ overview }: { overview: Overview }) {
  const stats = overview.activity ?? {}
  const integrations = [...overview.integrations].sort((a, b) =>
    (stats[b.id]?.active_incidents ?? 0) - (stats[a.id]?.active_incidents ?? 0)
    || (stats[b.id]?.overdue ?? 0) - (stats[a.id]?.overdue ?? 0)
    || (stats[b.id]?.validation_failed ?? 0) - (stats[a.id]?.validation_failed ?? 0))
  const rows = integrations.slice(0, 6)
  const largest = Math.max(1, ...rows.map(row => stats[row.id]?.active_incidents ?? 0))
  return <section className="ops-panel ops-integrations" aria-labelledby="integration-health">
    <header className="ops-panel-head"><div><h2 id="integration-health">Integration health</h2><p>Current operational conditions by integration</p></div></header>
    {rows.length ? <ul className="ops-health-list">{rows.map(row => {
      const facts = stats[row.id]
      const incidents = overview.activity ? facts?.active_incidents ?? 0 : undefined
      return <li key={row.id}>
        <div className="ops-health-header"><RouteLink href={'/deliveries?integration=' + encodeURIComponent(row.id)}>{row.name}</RouteLink>
          {!row.active && <span className="ops-incident-state">Inactive</span>}</div>
        <dl><div><dt>Incidents</dt><dd>{number(incidents)}</dd></div>
          <div><dt>Overdue</dt><dd>{number(overview.activity ? facts?.overdue ?? 0 : undefined)}</dd></div>
          <div><dt>Validation failed</dt><dd>{number(overview.activity ? facts?.validation_failed ?? 0 : undefined)}</dd></div></dl>
        <div className="ops-health-bar" aria-hidden="true"><span style={{ width: ((incidents ?? 0) / largest * 100) + '%' }}/></div>
        <p>{facts?.last_arrival ? <>Last arrival <DateTime value={facts.last_arrival}/></> : overview.activity ? 'No arrival recorded' : 'Arrival data unavailable'}</p>
      </li>
    })}</ul> : <SectionState heading="No integrations configured"/>}
    <footer className="ops-panel-footer"><span>{number(rows.length)} of {number(integrations.length)} integrations</span>
      <RouteLink className="command-text-link" href="/deliveries">View integrations in Deliveries</RouteLink></footer>
  </section>
}

function ActivityPreview({ source, refresh }: { source?: Resource<ActivityPage>; refresh: () => void }) {
  return <section className="ops-panel ops-activity" aria-labelledby="recent-changes">
    <header className="ops-panel-head"><div><h2 id="recent-changes">Recent activity</h2><p>Latest recorded changes from the activity feed</p></div>
      <RouteLink className="command-button" href="/overview/activity">View activity</RouteLink></header>
    {source?.error && <SectionState kind="error" heading="Activity is unavailable" retry={refresh}/>}
    {source?.data?.items.length ? <ul className="ops-activity-list">{source.data.items.slice(0, previewLimit).map(item => {
      const run = routeId(item.payload?.reconciliation_run_id ?? null)
      return <li key={item.source_event_id}>
        {run ? <GitCompareArrows aria-hidden="true"/> : <Activity aria-hidden="true"/>}
        <div><strong>{item.summary}</strong><p><DateTime value={item.occurred_at}/></p></div>
        <RouteLink className="command-text-link" href={run ? '/reconciliation/runs/' + run : '/deliveries/' + item.delivery_expectation_id} detail={!run}>
          {run ? 'View run evidence' : 'View delivery evidence'}
        </RouteLink>
      </li>
    })}</ul> : !source?.error && <SectionState kind={source?.data ? 'empty' : 'loading'}
      heading={source?.data ? 'No activity has been projected' : 'Loading recent activity…'}/>}
  </section>
}

export function OperationsOverview({ summary, attention, activity, refresh }: {
  summary?: Resource<Overview>; attention?: Resource<Attention[]>; activity?: Resource<ActivityPage>; refresh: () => void
}) {
  const overview = summary?.data
  const priorities = priorityItems(attention?.data ?? []).slice(0, previewLimit)
  const names = new Map(overview?.integrations.map(item => [item.id, item.name]))
  return <div className="ops-briefing">
    {summary?.error && <SectionState kind="error" heading={overview ? 'Operational snapshot may be out of date' : 'Operational snapshot is unavailable'} retry={refresh}/>}
    {overview ? <Snapshot overview={overview}/> : !summary?.error && <SectionState kind="loading" heading="Loading operational snapshot…"/>}
    <div className="ops-briefing-grid">
      <div className="ops-stack">
        <section className="ops-panel ops-priorities" aria-labelledby="briefing-priorities">
          <header className="ops-panel-head"><div><h2 id="briefing-priorities">Needs attention</h2><p>Priority issues to review at the start of your shift</p></div>
            <RouteLink className="command-button command-primary" href="/action-center">Open Action Center</RouteLink></header>
          {attention?.error && <SectionState kind="error" heading="Priority issues are unavailable" retry={refresh}/>}
          {priorities.length ? <ul className="ops-work-list">{priorities.map(item =>
            <WorkItem key={item.kind + item.key} item={item} integration={names.get(item.integration_id) ?? 'Integration name unavailable'} preview/>)}</ul>
            : !attention?.error && <SectionState kind={attention?.data ? 'empty' : 'loading'} heading={attention?.data ? 'No priority issues in this view' : 'Checking priority issues…'}/>}
        </section>
        <ActivityPreview source={activity} refresh={refresh}/>
      </div>
      <div className="ops-stack">
        {overview?.metrics && <section className="ops-panel ops-sla" aria-labelledby="sla-history">
          <header className="ops-panel-head"><div><h2 id="sla-history">SLA history</h2><p>Across recorded deliveries</p></div><CalendarClock aria-hidden="true"/></header>
          <div className="ops-sla-value"><strong>{number(overview.metrics.breached)}</strong><span>Recorded SLA breaches</span></div>
          <p>A recorded breach remains in history after the file arrives or the incident is resolved.</p>
        </section>}
        {overview && <IntegrationHealth overview={overview}/>}
      </div>
    </div>
  </div>
}

export function ActionCenter({ source, integrations, integration, issueFilter, filter, refresh, children }: {
  source?: Resource<Attention[]>; integrations: Integration[]; integration: string; issueFilter: string
  filter: (changes: Record<string, string>) => void; refresh: () => void; children: ReactNode
}) {
  const ordered = priorityItems(source?.data ?? [])
  const items = ordered.filter(item => issueFilter === 'recorded' ? item.recorded_incident
    : issueFilter === 'detected' ? !item.recorded_incident
    : issueFilter === 'reconciliation' ? item.kind === 'RECONCILIATION_FAILURE' : true)
  const names = new Map(integrations.map(item => [item.id, item.name]))
  const limited = (source?.data?.length ?? 0) > queueLimit
  return <div className="ops-action-layout">
    <section className="ops-panel ops-action-queue" aria-labelledby="attention-title">
      <header className="ops-panel-head"><div><h2 id="attention-title">Requires attention</h2><p>{integration ? names.get(integration) ?? 'Selected integration' : 'All integrations'}</p></div></header>
      <div className="ops-queue-filters">
        <label><span id="queue-integration-label">Integration</span><select aria-labelledby="queue-integration-label" value={integration} onChange={event => filter({ integration: event.target.value })}>
          <option value="">All integrations</option>{integrations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <label><span id="queue-scope-label">Issue scope</span><select aria-labelledby="queue-scope-label" value={issueFilter} onChange={event => filter({ issues: event.target.value })}>
          <option value="">All issues</option><option value="recorded">Recorded incidents</option>
          <option value="detected">Detected problems</option><option value="reconciliation">Reconciliation exceptions</option>
        </select></label>
      </div>
      {source?.data && <p className="ops-scope" role="status">{number(items.length)} shown of {number(ordered.length)} loaded
        {limited ? ' · Queue limited to the first 40 server results. Select an integration to narrow the scope.' : ' · Issue scope applies to loaded results.'}</p>}
      {source?.error && <SectionState kind="error" heading={source.data ? 'The queue may be out of date' : 'Attention items are unavailable'} retry={refresh}/>}
      {items.length ? bands.map((label, index) => {
        const group = items.filter(item => band(item) === index)
        return group.length > 0 && <section className="ops-band" key={label} data-priority={index} aria-label={label}>
          <h3>{label}<span>{number(group.length)}</span></h3>
          <ul className="ops-work-list">{group.map(item =>
            <WorkItem key={item.kind + item.key} item={item} integration={names.get(item.integration_id) ?? 'Integration name unavailable'}/>)}</ul>
        </section>
      }) : !source?.error && <SectionState kind={source?.data ? 'empty' : 'loading'}
        heading={source?.data ? 'No issues match this view' : 'Checking exceptions…'} detail={source?.data ? 'Try another integration or issue scope.' : undefined}/>}
    </section>
    <aside className="ops-workflow" aria-labelledby="workflow-title">
      <header><ListChecks aria-hidden="true"/><h2 id="workflow-title">Investigation workflow</h2></header>
      <ol>
        <li><strong>Detect</strong><p>Start with the highest-priority issue in your integration scope.</p></li>
        <li><strong>Investigate</strong><p>Open the incident or delivery from the queue.</p></li>
        <li><strong>Review evidence</strong><p>Check the file, delivery history, or linked reconciliation run.</p></li>
        <li><strong>Take permitted action</strong><p>Eligible operators can acknowledge an open recorded incident in its detail view.</p></li>
        <li><strong>Track the outcome</strong><p>Check the incident state and history. An acknowledged incident can still be active.</p></li>
      </ol>
      <div className="ops-workflow-tip"><Search aria-hidden="true"/><p>The evidence view confirms whether an active incident is open or acknowledged.</p></div>
      {children}
    </aside>
  </div>
}

import { type Session, type SessionControls, SessionGate } from './session'
import { useCallback, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, ArrowRight } from 'lucide-react'
import '@fontsource-variable/dm-sans'
import './styles.css'
import './shell.css'
import { useLiveUpdates } from './liveUpdates'
import { Copilot } from './Copilot'
import { Monitoring } from './Monitoring'
import { Administration } from './Administration'
import { Reconciliation } from './Reconciliation'
import { NavigationProvider, RouteLink, routeId, useNavigation } from './navigation'
import { CommandShell, SectionState } from './Shell'
import { ActionCenter, OperationsOverview, labels, problemLabels, queueLimit, timestamp, title,
  type ActivityPage, type Attention, type Overview } from './Operations'
import './operations.css'

import { read, useResource } from './dashboardData'
import { DeliveryQueue, DeliveryWorkspace, type Delivery, eventDescriptions, pageSize } from './DeliveryWorkspace'

function App({ session, controls }: { session: Session; controls: SessionControls }) {
  const { route, query, navigate } = useNavigation()
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision(value => value + 1), [])
  const connection = useLiveUpdates(refresh)
  const deliverySection = route.section === 'deliveries'
  const attentionSection = route.section === 'action-center'
  const briefingSection = route.section === 'overview' && !route.activity
  const requestedIssues = query.get('issues') ?? ''
  const issueFilter = ['recorded', 'detected', 'reconciliation'].includes(requestedIssues) ? requestedIssues : ''
  const integration = routeId(query.get('integration'))
  const requestedStatus = query.get('status') ?? ''
  const status = Object.hasOwn(labels, requestedStatus) ? requestedStatus : ''
  const sort = query.get('sort') === 'deadline' ? 'deadline' : 'newest'
  const requestedPage = Number(query.get('page'))
  const page = Number.isSafeInteger(requestedPage) && requestedPage > 1 ? Math.min(requestedPage - 1, 10000) : 0
  const deliveryParams = new URLSearchParams({ offset: String(page * pageSize), limit: String(pageSize + 1), sort })
  const attentionParams = new URLSearchParams({ limit: String(queueLimit + 1) })
  if (integration) {
    deliveryParams.set('integration_id', integration)
    if (attentionSection) attentionParams.set('integration_id', integration)
  }
  if (status) deliveryParams.set('status', status)

  const summary = useResource<Overview>(route.section === 'overview' || deliverySection || attentionSection ? '/overview' : undefined, revision)
  const results = useResource<Delivery[]>(deliverySection && !route.delivery ? '/deliveries?' + deliveryParams : undefined, revision)
  const attention = useResource<Attention[]>(attentionSection || briefingSection ? '/attention?' + attentionParams : undefined, revision)
  const activityPreview = useResource<ActivityPage>(briefingSection ? '/activity?limit=5' : undefined, revision)
  const detailResult = useResource<Delivery>(route.delivery ? '/deliveries/' + route.delivery : undefined, revision)
  const overview = summary?.data
  const detail = detailResult?.data
  const displayed = attentionSection ? attention : deliverySection ? detailResult ?? results : route.section === 'overview' && !route.activity ? summary : undefined
  const integrations = overview?.integrations ?? []
  const name = (id: string) => integrations.find(item => item.id === id)?.name ?? 'Unknown integration'
  function filter(changes: Record<string, string>) {
    const params = new URLSearchParams(query)
    for (const [key, value] of Object.entries(changes)) {
      if (value) params.set(key, value)
      else params.delete(key)
    }
    navigate('/' + route.section + (params.size ? '?' + params : ''), { replace: Object.hasOwn(changes, 'search') })
  }
  const openRun = (id: string) => navigate('/reconciliation/runs/' + encodeURIComponent(id))
  const openDetail = (id: string, incident?: string) => navigate('/deliveries/' + encodeURIComponent(id)
    + (incident ? '/incidents/' + encodeURIComponent(incident) : '') + (deliverySection && query.size ? '?' + query : ''), { detail: true })

  return <CommandShell session={session} {...controls} connection={connection} refresh={refresh}
    updated={displayed?.updated ? timestamp(displayed.updated) : undefined}>
      {route.section === 'overview' && (route.activity ? <ActivityFeed key={integration} integration={integration} revision={revision} onOpen={openDetail} onRun={openRun}/>
        : <OperationsOverview summary={summary} attention={attention} activity={activityPreview} refresh={refresh}/>)}
      {attentionSection && <ActionCenter source={attention} integrations={integrations} integration={integration}
        issueFilter={issueFilter} filter={filter} refresh={refresh}><NotificationPolicies/></ActionCenter>}
      {deliverySection && !route.delivery && <DeliveryQueue results={results} integrations={integrations}
        integration={integration} status={status} sort={sort} page={page} filter={filter} refresh={refresh}/>}
      {route.delivery && <DeliveryWorkspace key={route.delivery} deliveryId={route.delivery} selectedIncident={route.incident}
        delivery={detail} failed={detailResult?.error} integrationName={detail ? name(detail.integration_id) : undefined}
        revision={revision} refresh={refresh} canOperate={session.role !== 'VIEWER'}
        reprocessingEnabled={Boolean(overview?.reprocessing_enabled)}/>}
      {route.section === 'reconciliation' && <Reconciliation revision={revision} refresh={refresh} canOperate={session.role !== 'VIEWER'}/>}
      {route.section === 'copilot' && <Copilot standalone/>}
      {route.section === 'monitoring' && <Monitoring connection={connection} revision={revision} refresh={refresh}/>}
      {route.section === 'administration' && (session.role === 'ADMIN' ? <Administration ownId={session.id}/>
        : <SectionState kind="error" heading="Access denied" detail="Administration requires the Admin role."/>)}
      {route.section === 'not-found' && <><SectionState heading="This workspace page is unavailable."/>
        <RouteLink href="/overview" className="command-button command-primary">Return to Overview</RouteLink></>}
  </CommandShell>
}

function ActivityFeed({ integration, revision, onOpen, onRun }: {
  integration: string; revision: number; onOpen: (id: string) => void; onRun: (id: string) => void
}) {
  const [kind, setKind] = useState('')
  const [pagination, setPagination] = useState<{ at: string; id: string; revision: number }>()
  const cursor = pagination?.revision === revision ? pagination : undefined
  const [items, setItems] = useState<ActivityPage['items']>([])
  const [next, setNext] = useState<{ at: string; id: string }>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const request = new AbortController()
    const query = new URLSearchParams({ limit: '10' })
    if (kind) query.set('event_type', kind)
    if (integration) query.set('integration_id', integration)
    if (cursor) {
      query.set('before_at', cursor.at)
      query.set('before_id', cursor.id)
    }
    setLoading(true)
    setError(false)
    read<ActivityPage>('/activity?' + query, request.signal)
      .then(page => {
        if (request.signal.aborted) return
        setItems(existing => cursor ? [...existing, ...page.items] : page.items)
        setNext(page.next_before_at && page.next_before_id ? { at: page.next_before_at, id: page.next_before_id } : undefined)
      })
      .catch(() => { if (!request.signal.aborted) setError(true) })
      .finally(() => { if (!request.signal.aborted) setLoading(false) })
    return () => request.abort()
  }, [kind, cursor, integration, retry, revision])

  return <section className="panel activity-feed" aria-labelledby="activity-title">
    <div className="section-head"><div><h2 id="activity-title">Activity feed</h2><p>Projected delivery events · Times in UTC</p></div>
    <label>Event type <select value={kind} onChange={event => {
      setItems([]); setNext(undefined); setPagination(undefined); setKind(event.target.value)
    }}>
      <option value="">All events</option>
      {Object.keys(eventDescriptions).map(value => <option key={value} value={value}>{value.replace(/([a-z])([A-Z])/g, '$1 $2')}</option>)}
    </select></label></div>
    <ul>{items.map(item => <li key={item.source_event_id}>
      <div><strong>{item.summary}</strong><small>{timestamp(item.occurred_at)} UTC</small></div>
      <div>
        <button className="row-button" onClick={() => onOpen(item.delivery_expectation_id)}>View delivery <ArrowRight size={13}/></button>
        {item.payload?.reconciliation_run_id &&
          <button className="row-button" onClick={() => onRun(item.payload!.reconciliation_run_id!)}>View run <ArrowRight size={13}/></button>}
        {item.payload?.filename && <small>{item.payload.filename}</small>}
        {item.payload?.error_code && <small>{title(item.payload.error_code)}</small>}
        {item.payload?.attempt_series && <small>Series {item.payload.attempt_series} · Attempt {item.payload.attempt_count_in_series}</small>}
      </div>
    </li>)}</ul>
    {loading ? <p className="activity-note" role="status">Loading activity…</p> : error
      ? <p className="activity-note" role="alert">Unable to load activity. <button onClick={() => setRetry(value => value + 1)}>Retry activity</button></p>
      : next ? <div className="activity-note"><button onClick={() => setPagination({ ...next, revision })}>Load older activity</button></div>
      : !items.length && <p className="activity-note">No projected events match this view.</p>}
  </section>
}

type PolicyRecipient = { owner: string; email: string }
type Policy = { integration_id: string | null; incident_type: string | null; severity: string | null
  opened: PolicyRecipient[] | null; resolved: PolicyRecipient[] | null
  escalations: { after_seconds: number; recipients: PolicyRecipient[] }[] | null }

function NotificationPolicies() {
  const [visible, setVisible] = useState(false)
  const [rules, setRules] = useState<Policy[]>()
  const [error, setError] = useState(false)
  const owners = (entries: PolicyRecipient[] | null) => entries?.map(entry => entry.owner).join(', ') || 'None'
  useEffect(() => {
    if (!visible) return
    const request = new AbortController()
    setError(false)
    read<{ rules: Policy[] }>('/notification-policies', request.signal)
      .then(result => { if (!request.signal.aborted) setRules(result.rules) })
      .catch(() => { if (!request.signal.aborted) setError(true) })
    return () => request.abort()
  }, [visible])
  return <details className="panel policy-panel" onToggle={event => setVisible(event.currentTarget.open)}>
    <summary>Notification policies</summary>
    {error ? <p role="alert">Policies are unavailable. Close and reopen to retry.</p>
      : !rules ? <p role="status">Loading policies…</p>
      : !rules.length ? <p>No notification rules configured.</p>
      : <ul>{rules.map((rule, index) => <li key={index}>
        <strong>{rule.incident_type ? problemLabels[rule.incident_type] ?? title(rule.incident_type) : 'All incident types'}
          {' · '}{rule.severity ? title(rule.severity) : 'All severities'}</strong>
        <p>Integration · {rule.integration_id ?? 'All integrations'}</p>
        <p>Opened · {rule.opened ? owners(rule.opened) : 'Inherits matching rule'}</p>
        <p>Resolved · {rule.resolved ? owners(rule.resolved) : 'Inherits matching rule'}</p>
        {rule.escalations?.map((step, level) => <p key={level}>Level {level + 1} · After {step.after_seconds} seconds · {owners(step.recipients)}</p>)}
      </li>)}</ul>}
  </details>
}

createRoot(document.getElementById('root')!).render(<NavigationProvider><SessionGate>{(session, controls) =>
  <App session={session} controls={controls}/>}</SessionGate></NavigationProvider>)

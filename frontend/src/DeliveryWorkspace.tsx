import { useEffect, useRef, useState } from 'react'
import { CalendarClock, FileText, History, Inbox, ShieldAlert } from 'lucide-react'
import { apiFetch } from './session'
import { read, useResource } from './dashboardData'
import { RouteLink, useNavigation, routeId } from './navigation'
import { Badge, labels, problemLabels, timestamp, title, type Status, type Integration } from './Operations'
import { SectionState, SeverityIndicator } from './Shell'
import { Copilot } from './Copilot'
import './deliveries.css'

type DeliveryEvent = {
  id: string; delivery_id: string; event_type: string; occurred_at: string; file_id: string | null
  filename: string | null; replaces_file_id: string | null
  actor_reference: string | null
  details: { error_code?: string; record_count?: number; existing_file_id?: string; attempt_series?: number
    attempt_count_in_series?: number; failure_reason?: string; next_retry_at?: string
    reconciliation_run_id?: string; exception_count?: number
    debit_count?: number; credit_count?: number; zero_count?: number }
}
type NotificationAttempt = { number: number; status: string; started_at: string; error_code: string | null }
type NotificationJob = { id: string; event: string; level: number; owner: string; recipient: string; status: string
  scheduled_at: string; next_attempt_at: string; finished_at: string | null; attempts: NotificationAttempt[] }
type Incident = { id: string; incident_type: string; status: string; severity?: string; reason: string; opened_at: string
  reconciliation_run_id?: string | null
  resolved_at: string | null; resolution_reason: string | null; acknowledged_at?: string | null
  operator?: string | null; acknowledgement_comment?: string | null; acknowledgement_enabled?: boolean
  notifications?: NotificationJob[] }
export const eventDescriptions: Record<string, string> = {
  DeliveryExpectationCreated: 'The system recorded the expected delivery.',
  FileReceived: 'Intake accepted the file.',
  FileValidationFailed: 'Intake recorded the file and rejected its contents during validation.',
  SourceDeliveryIdConflict: 'Intake quarantined a submission that reused the same source delivery ID for different content.',
  DeliveryOverdue: 'The system recorded an SLA breach.',
  FileProcessingStarted: 'The worker started a processing attempt.',
  FileProcessingCompleted: 'The worker finished processing the accepted file and recorded its result.',
  FileProcessingFailed: 'The worker recorded a failed processing attempt.',
  ManualReprocessingRequested: 'An operator queued a new attempt series.',
  ReconciliationQueued: 'A reconciliation run was queued.',
  ReconciliationStarted: 'The reconciliation worker started an attempt.',
  ReconciliationSourceMissing: 'A required source missed its arrival deadline.',
  ReconciliationRetryScheduled: 'A retry was scheduled for this reconciliation.',
  ReconciliationCompleted: 'The comparison results were committed.',
  ReconciliationFailed: 'The reconciliation could not complete.',
}
export type Delivery = {
  id: string; integration_id: string; status: Status; delivery_type: string; business_date: string
  deadline_at: string; overdue_at: string | null; expected_pattern: string
  current_file: null | { id: string; original_name: string; size_bytes: number; received_at: string; content_hash: string
    validation_error_code: string | null; processing_error_code: string | null; replaces_file_id: string | null
    processing_error_message: string | null; next_retry_at: string | null; can_reprocess: boolean
    status?: Status; processed_at?: string | null; attempt_series: number; attempt_count_in_series: number }
}

export const pageSize = 20
type Results = { data?: Delivery[]; error?: boolean }
const utc = (value: string) => <time dateTime={value}>{timestamp(value)} UTC</time>

export function DeliveryQueue({ results, integrations, integration, status, sort, page, filter, refresh }: {
  results?: Results; integrations: Integration[]; integration: string; status: string; sort: string; page: number
  filter: (changes: Record<string, string>) => void; refresh: () => void
}) {
  const { query, navigate } = useNavigation()
  const [lookup, setLookup] = useState('')
  const [lookupError, setLookupError] = useState(false)
  const search = query.get('search') ?? ''
  const loaded = results?.data?.slice(0, pageSize) ?? []
  const names = new Map(integrations.map(item => [item.id, item.name]))
  const rows = loaded.filter(row => [title(row.delivery_type), row.delivery_type, row.business_date, row.current_file?.original_name]
    .some(value => value?.toLowerCase().includes(search.trim().toLowerCase())))
  const next = (results?.data?.length ?? 0) > pageSize
  const suffix = query.size ? '?' + query : ''
  return <div className="delivery-queue">
    <div className="delivery-queue-filters">
      <fieldset><legend>Integration</legend><div className="delivery-integration-pills">
        <button aria-pressed={!integration} onClick={() => filter({ integration: '', page: '' })}>All integrations</button>
        {integrations.map(item => <button key={item.id} aria-pressed={integration === item.id}
          onClick={() => filter({ integration: item.id, page: '' })}>{item.name}</button>)}
      </div>
        <select className="delivery-integration-select" aria-label="Integration" value={integration}
          onChange={event => filter({ integration: event.target.value, page: '' })}>
          <option value="">All integrations</option>
          {integrations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </fieldset>
      <div className="delivery-selects">
        <label><span id="delivery-status-label">Status</span><select aria-labelledby="delivery-status-label" value={status}
          onChange={event => filter({ status: event.target.value, page: '' })}>
          <option value="">All statuses</option>{Object.entries(labels).map(([key, value]) => <option key={key} value={key}>{value}</option>)}
        </select></label>
        <label><span id="delivery-sort-label">Sort</span><select aria-labelledby="delivery-sort-label" value={sort}
          onChange={event => filter({ sort: event.target.value, page: '' })}>
          <option value="newest">Newest first</option><option value="deadline">Earliest deadline</option>
        </select></label>
        <label>Search this page<input type="search" value={search} maxLength={120}
          onChange={event => filter({ search: event.target.value })} placeholder="Delivery, date or filename"/></label>
      </div>
      <details className="delivery-lookup"><summary>Open by delivery ID</summary>
        <form onSubmit={event => {
          event.preventDefault()
          const id = routeId(lookup.trim())
          setLookupError(!id)
          if (id) navigate('/deliveries/' + id + suffix, { detail: true })
        }}>
          <label>Delivery ID <input value={lookup} onChange={event => { setLookup(event.target.value); setLookupError(false) }} required/></label>
          <button className="command-button">Open delivery</button>
          {lookupError && <span role="alert">Enter a valid delivery UUID.</span>}
        </form>
      </details>
    </div>
    <section className="delivery-results" aria-labelledby="delivery-queue-title">
      <header><h2 id="delivery-queue-title">Delivery queue</h2>
        <p>{names.get(integration) ?? (integration ? 'Selected integration' : 'All integrations')} · Times in UTC</p>
        {results?.data && <p className="delivery-result-count" role="status">
          Page {page + 1} · {rows.length} shown of {loaded.length} loaded{search.trim() ? ' · Search applies to this page' : ''}
        </p>}
      </header>
      {results?.error && <SectionState kind="error" heading={results.data ? 'Deliveries may be out of date' : 'Could not load deliveries'} retry={refresh}/>}
      {!results?.data ? !results?.error && <SectionState kind="loading" heading="Loading deliveries…"/>
        : rows.length === 0 ? <SectionState heading="No matching deliveries"
          detail={search ? 'Try another term or clear the page search.' : integration || status ? 'Choose another integration or status.' : 'Delivery expectations will appear here when they are created.'}/>
        : <div className="delivery-table" role="region" aria-label="Delivery results"><table>
          <thead><tr><th scope="col">Delivery</th><th scope="col">Status</th><th scope="col">Current file</th><th scope="col">Deadline</th></tr></thead>
          <tbody>{rows.map(row => <tr key={row.id}
            data-attention={Boolean(row.overdue_at || ['VALIDATION_FAILED', 'PROCESSING_FAILED'].includes(row.status))}>
            <td><RouteLink className="command-text-link" href={'/deliveries/' + row.id + suffix} detail>{title(row.delivery_type)}</RouteLink>
              <small>{names.get(row.integration_id) ?? 'Integration unavailable'} · {row.business_date}</small></td>
            <td><span className="delivery-cell-label" aria-hidden="true">Status</span><Badge status={row.status}/></td>
            <td><span className="delivery-cell-label" aria-hidden="true">Current file</span>{row.current_file?.original_name ?? 'No current file'}</td>
            <td><span className="delivery-cell-label" aria-hidden="true">Deadline</span>{utc(row.deadline_at)}
              {row.overdue_at && <small className="negative">SLA breach recorded</small>}</td>
          </tr>)}</tbody>
        </table></div>}
      {results?.data && (page > 0 || next) && <nav className="pages" aria-label="Delivery pagination">
        <button disabled={page === 0} onClick={() => filter({ page: page > 1 ? String(page) : '' })}>Previous</button>
        <span>Page {page + 1}</span><button disabled={!next || page >= 10000} onClick={() => filter({ page: String(page + 2) })}>Next</button>
      </nav>}
    </section>
  </div>
}

export function DeliveryWorkspace({ deliveryId, selectedIncident, delivery, failed, integrationName, revision, refresh,
  canOperate, reprocessingEnabled }: {
  deliveryId: string; selectedIncident?: string; delivery?: Delivery; failed?: boolean; integrationName?: string
  revision: number; refresh: () => void; canOperate: boolean; reprocessingEnabled: boolean
}) {
  const { deliveryOrigin, query, pathname, navigate } = useNavigation()
  const heading = useRef<HTMLHeadingElement>(null)
  const [notice, setNotice] = useState('')
  const [incidentLimit, setIncidentLimit] = useState(21)
  const requestedOffset = Number(query.get('incident_offset'))
  const offset = Number.isSafeInteger(requestedOffset) && requestedOffset > 0 && requestedOffset <= 10000 && requestedOffset % 100 === 0
    ? requestedOffset : 0
  const limit = selectedIncident || offset ? 100 : incidentLimit
  const incidents = useResource<Incident[]>('/deliveries/' + deliveryId + '/incidents?limit=' + limit + '&offset=' + offset, revision)
  const file = delivery?.current_file
  const head = delivery ? title(delivery.delivery_type) : 'Delivery evidence'
  const queueQuery = new URLSearchParams(query)
  queueQuery.delete('incident_offset')
  const returnPath = deliveryOrigin ?? '/deliveries' + (queueQuery.size ? '?' + queueQuery : '')
  const returnLabel = returnPath.startsWith('/action-center') ? 'Action Center'
    : returnPath.startsWith('/reconciliation') ? 'Reconciliation'
      : returnPath.startsWith('/copilot') ? 'AI Copilot'
        : returnPath.startsWith('/monitoring') ? 'Monitoring'
          : returnPath.startsWith('/overview/activity') ? 'Recent activity' : returnPath.startsWith('/overview') ? 'Overview' : 'Delivery queue'

  function incidentPage(next: number) {
    const params = new URLSearchParams(query)
    if (next) params.set('incident_offset', String(next))
    else params.delete('incident_offset')
    navigate(pathname + (params.size ? '?' + params : ''), { detail: true })
  }

  useEffect(() => {
    if (!selectedIncident) heading.current?.focus()
  }, [head, selectedIncident])

  return <article className="delivery-workspace" aria-labelledby="delivery-identity">
    <header className="delivery-identity">
      <RouteLink className="command-text-link" href={returnPath}>Back to {returnLabel}</RouteLink>
      <h1 id="delivery-identity" ref={heading} tabIndex={-1}>{head}</h1>
      {delivery && <div className="delivery-identity-context"><span>{integrationName}</span>
        <span>Business date <time dateTime={delivery.business_date}>{delivery.business_date}</time></span>
        <Badge status={delivery.status}/></div>}
    </header>
    {failed && <SectionState kind="error" heading={delivery ? 'Delivery evidence may be out of date' : 'Could not load this delivery'} retry={refresh}/>}
    {!delivery ? !failed && <SectionState kind="loading" heading="Loading delivery evidence…"/> : <>
      <nav className="delivery-evidence-nav" aria-label="Delivery evidence sections">
        {['Summary', 'Incidents', 'Timeline'].map(label => {
          const id = 'delivery-' + label.toLowerCase()
          return <a key={id} href={'#' + id} onClick={event => {
            if (event.button || event.metaKey || event.altKey || event.ctrlKey || event.shiftKey) return
            const section = document.getElementById(id)
            if (!section) return
            event.preventDefault()
            section.focus()
            section.scrollIntoView({ block: 'start' })
          }}>{label}</a>
        })}
      </nav>
      <section className="delivery-summary" id="delivery-summary" aria-labelledby="delivery-summary-title" tabIndex={-1}>
        <h2 id="delivery-summary-title">Arrival and SLA</h2>
        <dl>
          <div><dt><CalendarClock size={17} aria-hidden="true"/> Deadline</dt><dd>{utc(delivery.deadline_at)}</dd></div>
          <div><dt><Inbox size={17} aria-hidden="true"/> Current file receipt</dt><dd>{file ? utc(file.received_at) : 'No current file attached'}</dd></div>
          <div><dt><History size={17} aria-hidden="true"/> SLA outcome</dt><dd>{delivery.overdue_at ? 'Recorded breach' : 'No breach recorded'}</dd>
            {delivery.overdue_at && <dd>{utc(delivery.overdue_at)}</dd>}</div>
          <div><dt><ShieldAlert size={17} aria-hidden="true"/> Active incidents</dt><dd>{incidents?.data
            ? incidents.data.filter(row => row.status === 'OPEN' || row.status === 'ACKNOWLEDGED').length : incidents?.error ? 'Unavailable' : 'Loading…'}</dd>
            {incidents?.data && (offset > 0 || incidents.data.length === limit) && <dd>From loaded incident history</dd>}</div>
        </dl>
      </section>
      <div className="delivery-evidence-layout">
        <div className="delivery-evidence-stack">
          <section className="delivery-panel" aria-labelledby="current-file-title">
            <h2 id="current-file-title"><FileText size={20} aria-hidden="true"/> Current file</h2>
            {file ? <>
              <strong className="delivery-file-name">{file.original_name}</strong>
              <dl className="delivery-facts"><dt>File size</dt><dd>{file.size_bytes.toLocaleString('en-GB')} bytes</dd>
                <dt>Validation</dt><dd>{file.validation_error_code ? title(file.validation_error_code)
                  : file.status === 'VALIDATION_FAILED' ? 'Validation failed'
                    : file.status === 'RECEIVED' || file.status === 'PROCESSING' || file.status === 'PROCESSING_FAILED' || file.status === 'COMPLETED'
                    ? 'Accepted for processing' : 'No validation failure recorded'}</dd>
                {file.processing_error_code && <><dt>Processing error</dt><dd>{title(file.processing_error_code)}</dd></>}
                {file.processing_error_message && <><dt>Failure reason</dt><dd>{file.processing_error_message}</dd></>}
                {file.attempt_series > 0 && <><dt>Processing attempts</dt><dd>Series {file.attempt_series} · {file.attempt_count_in_series} of 3</dd></>}
                {file.processed_at && <><dt>Last processing outcome</dt><dd>{utc(file.processed_at)}</dd></>}
                {file.next_retry_at && <><dt>Next eligible retry</dt><dd>{utc(file.next_retry_at)}</dd></>}
              </dl>
              <details className="delivery-disclosure"><summary>File identifiers and integrity</summary><dl className="delivery-facts">
                <dt>Expected filename</dt><dd>{delivery.expected_pattern}</dd><dt>File ID</dt><dd><code>{file.id}</code></dd>
                <dt>SHA-256</dt><dd><code>{file.content_hash}</code></dd>
                {file.replaces_file_id && <><dt>Replaces file</dt><dd><code>{file.replaces_file_id}</code></dd></>}
              </dl></details>
            </> : <p>The current file is unavailable. Check the incident and event history for evidence of arrival.</p>}
            <details className="delivery-disclosure"><summary>Delivery identifiers</summary><dl className="delivery-facts">
              <dt>Delivery ID</dt><dd><code>{delivery.id}</code></dd>
              {!file && <><dt>Expected filename</dt><dd>{delivery.expected_pattern}</dd></>}
            </dl></details>
            {notice && <p className="notice" role="status">{notice}</p>}
            {canOperate && reprocessingEnabled && file?.can_reprocess &&
              <ReprocessingForm key={file.id + ':' + file.attempt_series} delivery={delivery}
                onQueued={() => { setNotice('A new processing series was queued.'); refresh() }} onConflict={refresh}/>}
          </section>
          <Timeline deliveryId={delivery.id} revision={revision}/>
        </div>
        <Incidents rows={incidents?.data} failed={incidents?.error} selectedIncident={selectedIncident} refresh={refresh}
          canOperate={canOperate} limit={limit} offset={offset} openPage={incidentPage}
          more={() => setIncidentLimit(value => Math.min(100, value + 20))}/>
      </div>
    </>}
  </article>
}

function ReprocessingForm({ delivery, onQueued, onConflict }: { delivery: Delivery; onQueued: () => void; onConflict: () => void }) {
  const [confirmed, setConfirmed] = useState(false)
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState(false)
  return <form className="reprocess" onSubmit={async event => {
    event.preventDefault()
    if (!delivery.current_file || !confirmed || sending) return
    setSending(true)
    setFailed(false)
    try {
      const response = await apiFetch(`/api/dashboard/deliveries/${delivery.id}/reprocess`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmed, file_id: delivery.current_file.id,
          attempt_series: delivery.current_file.attempt_series }),
      })
      if (response.status === 409) {
        setConfirmed(false)
        onConflict()
      }
      if (!response.ok) throw new Error('Reprocessing request failed')
      onQueued()
    } catch {
      setFailed(true)
    } finally {
      setSending(false)
    }
  }}>
    <h3>Manual reprocessing</h3>
    <label><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/> Confirm a new processing series</label>
    <button type="submit" disabled={!confirmed || sending}>{sending ? 'Queuing…' : 'Queue reprocessing'}</button>
    {failed && <p role="alert">Could not queue this file. Refresh the delivery before trying again.</p>}
  </form>
}

function Incidents({ rows, failed, selectedIncident, canOperate, limit, offset, openPage, more, refresh }: {
  rows?: Incident[]; failed?: boolean; selectedIncident?: string; canOperate: boolean
  limit: number; offset: number; openPage: (offset: number) => void; more: () => void; refresh: () => void
}) {
  const { route, query } = useNavigation()
  const selected = useRef<HTMLLIElement>(null)
  const found = Boolean(selectedIncident && rows?.some(row => row.id === selectedIncident))
  const suffix = query.size ? '?' + query : ''
  useEffect(() => {
    if (found) selected.current?.focus()
  }, [found, selectedIncident])
  return <section className="delivery-panel delivery-incidents" id="delivery-incidents" tabIndex={-1} aria-labelledby="incidents-title">
    <h2 id="incidents-title"><ShieldAlert size={20} aria-hidden="true"/> Incidents</h2>
    <p>Incident lifecycle and severity are tracked separately from delivery processing.</p>
    {failed && <SectionState kind="error" heading="Incident history unavailable" retry={refresh}/>}
    {selectedIncident && rows && !found && <p role="status">The linked incident is outside the loaded records or is unavailable.</p>}
    {rows?.length ? <ul className="delivery-incident-list">{rows.map(row => <li key={row.id} ref={row.id === selectedIncident ? selected : undefined}
      className={row.id === selectedIncident ? 'selected-incident' : undefined} tabIndex={row.id === selectedIncident ? -1 : undefined}>
      <div className="delivery-incident-header">
        <h3>{problemLabels[row.incident_type] ?? title(row.incident_type)} · {title(row.status)}</h3>
        {row.severity && <SeverityIndicator severity={row.severity}/>}
      </div>
      <div className="delivery-incident-evidence">
        <p>{row.reason}</p><p>Opened {utc(row.opened_at)}</p>
        {row.reconciliation_run_id && <RouteLink className="command-text-link" href={'/reconciliation/runs/' + row.reconciliation_run_id}>View reconciliation run</RouteLink>}
        {row.acknowledged_at && <p>Acknowledged {utc(row.acknowledged_at)}
          {row.acknowledgement_comment && <span className="delivery-comment">{row.acknowledgement_comment}</span>}</p>}
        {row.resolved_at && <p>Resolved {utc(row.resolved_at)}{row.resolution_reason && ' · ' + row.resolution_reason}</p>}
      </div>
      <div className="delivery-investigation">
        <h4>Investigation</h4>
        <p>{row.incident_type === 'MISSING_FILE' ? 'Check the arrival timeline and confirm the delivery schedule.'
          : row.incident_type === 'SOURCE_DELIVERY_ID_CONFLICT' ? 'Review the conflict event and verify the source delivery ID with the sender.'
            : row.incident_type === 'RECONCILIATION_FAILURE' ? 'Review the linked run and its exceptions.'
              : 'Review the file error and its processing or validation history.'}</p>
        <Copilot incidentId={row.id} acknowledged={Boolean(row.acknowledged_at)}/>
      </div>
      {canOperate && row.acknowledgement_enabled && row.status === 'OPEN' &&
        <Acknowledge incident={row.id} onSaved={refresh}/>}
      <NotificationHistory jobs={row.notifications ?? []}/>
      <details className="delivery-disclosure"><summary>Incident identifiers</summary>
        <dl className="delivery-facts"><dt>Incident ID</dt><dd><code>{row.id}</code></dd>
          {row.operator && <><dt>Acknowledged by</dt><dd><code>{row.operator}</code></dd></>}
        </dl>
        {row.id !== selectedIncident && <RouteLink className="command-text-link" detail
          href={'/deliveries/' + route.delivery + '/incidents/' + row.id + suffix}>Open this incident directly</RouteLink>}
      </details>
    </li>)}</ul> : rows ? <p>No incidents recorded.</p> : !failed && <p role="status">Loading incidents…</p>}
    {rows && (offset || rows.length === limit) ? <p className="delivery-scope">{rows.length
      ? `Showing incidents ${offset + 1}–${offset + rows.length}, newest first.` : 'No older incidents recorded.'}</p> : null}
    {rows?.length === limit && limit < 100 && <button className="command-button" onClick={more}>Show more incidents</button>}
    {(offset > 0 || (limit === 100 && rows?.length === limit)) && <nav className="pages" aria-label="Incident history pagination">
      <button disabled={offset === 0} onClick={() => openPage(offset - 100)}>Newer incidents</button>
      <button disabled={offset >= 10000 || rows?.length !== limit} onClick={() => openPage(offset + 100)}>Older incidents</button>
    </nav>}
  </section>
}

function NotificationHistory({ jobs }: { jobs: NotificationJob[] }) {
  const owners = [...new Set(jobs.filter(job => job.event === 'OPENED').map(job => job.owner))]
  const next = jobs.find(job => job.event === 'ESCALATED' && ['PENDING', 'SENDING'].includes(job.status))
  const level = Math.max(0, ...jobs.filter(job => job.event === 'ESCALATED' && job.attempts.length)
    .map(job => job.level))
  return <>
    {owners.length > 0 && <p>Process owners · {owners.join(', ')}</p>}
    {jobs.some(job => job.event === 'ESCALATED') && <p>Escalation level {level}
      {next ? ` · Next level ${next.level} due ${timestamp(next.scheduled_at)} UTC` : ' · No further escalation scheduled'}</p>}
    <details className="notification-history">
      <summary>Notification history ({jobs.length})</summary>
      {jobs.length === 0 ? <p>No notification jobs recorded.</p> : <ul>{jobs.map(job => <li key={job.id}>
        <strong>{title(job.event)}{job.level ? ` · Level ${job.level}` : ''} · {title(job.status)}</strong>
        <small>{job.owner} · {job.recipient}</small>
        <small>Scheduled {timestamp(job.scheduled_at)} UTC
          {job.status === 'PENDING' && job.attempts.length > 0 ? ` · Retry ${timestamp(job.next_attempt_at)} UTC` : ''}</small>
        {job.finished_at && <small>Finished {timestamp(job.finished_at)} UTC</small>}
        {job.attempts.map(attempt => <small key={attempt.number}>Attempt {attempt.number} · {title(attempt.status)}
          {' · '}{timestamp(attempt.started_at)} UTC{attempt.error_code ? ` · ${title(attempt.error_code)}` : ''}</small>)}
      </li>)}</ul>}
    </details>
  </>
}

function Acknowledge({ incident, onSaved }: { incident: string; onSaved: () => void }) {
  const [comment, setComment] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(false)
  return <form className="reprocess" onSubmit={async event => {
    event.preventDefault()
    setSending(true)
    setError(false)
    try {
      const response = await apiFetch(`/api/dashboard/incidents/${incident}/acknowledge`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ comment }),
      })
      if (response.status === 409) onSaved()
      if (!response.ok) throw new Error('Acknowledgement failed')
      onSaved()
    } catch {
      setError(true)
    } finally {
      setSending(false)
    }
  }}>
    <small>Recorded under your signed-in operator</small>
    <label>Comment (optional) <input value={comment} maxLength={500} onChange={event => setComment(event.target.value)}/></label>
    <button type="submit" disabled={sending}>{sending ? 'Saving…' : 'Acknowledge incident'}</button>
    {error && <p role="alert">Acknowledgement could not be saved. Refresh the incident and try again.</p>}
  </form>
}

function Timeline({ deliveryId, revision }: { deliveryId: string; revision: number }) {
  const [events, setEvents] = useState<DeliveryEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [more, setMore] = useState(false)
  const [offset, setOffset] = useState(0)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const request = new AbortController()
    setLoading(true)
    setError(false)
    read<DeliveryEvent[]>('/deliveries/' + deliveryId + '/events?limit=11&offset=' + offset, request.signal)
      .then(rows => {
        if (request.signal.aborted) return
        setEvents(existing => [...existing.slice(0, offset), ...rows.slice(0, 10)])
        setMore(rows.length > 10)
      })
      .catch(() => { if (!request.signal.aborted) setError(true) })
      .finally(() => { if (!request.signal.aborted) setLoading(false) })
    return () => request.abort()
  }, [deliveryId, offset, retry, revision])
  return <section className="delivery-panel" id="delivery-timeline" tabIndex={-1} aria-labelledby="timeline-title">
    <h2 id="timeline-title"><History size={20} aria-hidden="true"/> Delivery timeline</h2>
    <p>Recorded events in chronological order · {events.length} loaded</p>
    <ol className="timeline">{events.map(event => <li key={event.id}>
      <small>{utc(event.occurred_at)}</small>
      <strong>{event.event_type.replace(/([a-z])([A-Z])/g, '$1 $2')}</strong>
      <p>{eventDescriptions[event.event_type] ?? 'Description unavailable for this recorded event.'}</p>
      {event.filename && <p>File {event.filename}</p>}
      {event.details.error_code && <p>Error <code>{event.details.error_code}</code></p>}
      {event.details.failure_reason && <p>{event.details.failure_reason}</p>}
      {event.details.attempt_series && <p>Series {event.details.attempt_series} · {event.details.attempt_count_in_series} of 3 attempts</p>}
      {event.details.next_retry_at && <p>Retry eligible {timestamp(event.details.next_retry_at)} UTC</p>}
      {typeof event.details.debit_count === 'number' && <p>{event.details.debit_count} debit · {event.details.credit_count} credit · {event.details.zero_count} zero</p>}
      {typeof event.details.record_count === 'number' && <p>{event.details.record_count} CSV records</p>}
      {typeof event.details.exception_count === 'number' && <p>{event.details.exception_count} exception groups recorded</p>}
      {event.details.reconciliation_run_id && <RouteLink className="command-text-link"
        href={'/reconciliation/runs/' + event.details.reconciliation_run_id}>View run evidence</RouteLink>}
      <details className="delivery-disclosure"><summary>Event identifiers</summary>
        <dl className="delivery-facts"><dt>Event ID</dt><dd><code>{event.id}</code></dd>
          {event.file_id && <><dt>File ID</dt><dd><code>{event.file_id}</code></dd></>}
          {event.details.existing_file_id && <><dt>Retained file</dt><dd><code>{event.details.existing_file_id}</code></dd></>}
          {event.replaces_file_id && <><dt>Replaces file</dt><dd><code>{event.replaces_file_id}</code></dd></>}
          {event.event_type === 'ManualReprocessingRequested' && <><dt>Requested by</dt><dd>{event.actor_reference ?? 'Unknown operator'}</dd></>}
        </dl>
      </details>
    </li>)}</ol>
    {loading ? <p role="status">Loading timeline…</p> : error
      ? <p role="alert">Timeline unavailable. <button onClick={() => setRetry(value => value + 1)}>Retry timeline</button></p>
      : more ? <button onClick={() => setOffset(events.length)}>Load more events</button>
      : !events.length && <p>No delivery events recorded.</p>}
  </section>
}


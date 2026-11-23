import { useEffect, useRef, useState } from 'react'
import { FileStack, GitCompareArrows } from 'lucide-react'
import { apiFetch } from './session'
import { useResource } from './dashboardData'
import { Copilot } from './Copilot'
import { RouteLink, useNavigation } from './navigation'
import { SectionState } from './Shell'
import { timestamp, title } from './Operations'
import './reconciliation.css'

type Run = {
  id: string; name: string; status: string; attempts: number; counts: Record<string, number> | null
  parent_id: string | null; created_at: string; finished_at: string | null; error_code: string | null
}
type Result = { index: number; category: string; currency: string | null; difference: string | null; count_a: number; count_b: number }
type RunDetail = Run & {
  match_on: string; tolerance: string; material: boolean; incident_id: string | null; items: Result[]; has_more: boolean
  file_a_id: string | null; file_b_id: string | null
  sources: { id: string; integration: string; delivery_type: string; business_date: string; status: string }[]
}
type RunList = { items: Run[]; has_more: boolean; rerun_enabled: boolean }

const categories: Record<string, string> = {
  AMOUNT_MISMATCH: 'Amount mismatch', MISSING_A: 'Missing in source A', MISSING_B: 'Missing in source B',
  DUPLICATE: 'Duplicate records', AMBIGUOUS: 'Ambiguous matches', INVALID: 'Invalid or unsupported',
  EXACT: 'Exact matches', WITHIN_TOLERANCE: 'Within tolerance',
}
const matches = ['EXACT', 'WITHIN_TOLERANCE']
const size = 20
const base = '/reconciliation'
const runPath = (id: string) => base + '/runs/' + id
const utc = (value: string) => <time dateTime={value}>{timestamp(value)} UTC</time>
const execution: Record<string, string> = { WAITING: 'Waiting for sources', RUNNING: 'Running', RETRY: 'Retry scheduled', COMPLETED: 'Completed', FAILED: 'Failed' }

function totals(run: Run) {
  if (!run.counts) return undefined
  const matched = matches.reduce((sum, key) => sum + (run.counts?.[key] ?? 0), 0)
  return { matched, exceptions: Object.values(run.counts).reduce((sum, value) => sum + value, 0) - matched }
}

function outcome(run: Run) {
  const counts = totals(run)
  return !counts ? 'Results unavailable' : counts.exceptions ? 'Exceptions recorded' : 'No exceptions recorded'
}

function Execution({ run }: { run: Run }) {
  return <span className={'badge ' + (run.status === 'FAILED' ? 'processing_failed' : run.status === 'COMPLETED' ? 'completed' : '')}>
    {execution[run.status] ?? title(run.status)}
  </span>
}

function pageNumber(value: string | null, max: number) {
  const number = Number(value)
  return Number.isSafeInteger(number) && number > 0 && number <= max ? number : 1
}

export function Reconciliation({ revision, canOperate, refresh }: { revision: number; canOperate: boolean; refresh: () => void }) {
  const { route, query, pathname, navigate } = useNavigation()
  const selected = route.run
  const listPage = pageNumber(query.get('history'), 501)
  const page = pageNumber(query.get('page'), 2001)
  const run = useResource<RunDetail>(selected ? runPath(selected) + '?limit=1' : undefined, revision)
  const detail = run?.data
  const requestedCategory = query.get('category') ?? ''
  const category = requestedCategory === 'all' || Object.hasOwn(categories, requestedCategory) ? requestedCategory
    : Object.keys(categories).find(key => !matches.includes(key) && (detail?.counts?.[key] ?? 0) > 0) ?? 'all'
  const list = useResource<RunList>(!selected ? base + '?offset=' + (listPage - 1) * size
    : canOperate ? base + '?limit=1' : undefined, revision)
  const results = useResource<RunDetail>(detail?.counts ? runPath(detail.id) + '?offset=' + (page - 1) * size
    + (category === 'all' ? '' : '&category=' + category) : undefined, revision)
  const currentResult = results?.data?.items.find(item => item.index === route.exception)
  // A group index is its ordinal in the full report. A filtered page may never contain it.
  const exact = useResource<RunDetail>(detail?.counts && route.exception && !currentResult
    ? runPath(detail.id) + '?limit=1&offset=' + (route.exception - 1) : undefined, revision)
  const inspected = currentResult ?? exact?.data?.items.find(item => item.index === route.exception)
  const previous = useResource<RunDetail>(detail?.parent_id ? runPath(detail.parent_id) + '?limit=1' : undefined, revision)
  const history = base + (listPage > 1 ? '?history=' + listPage : '')
  const historySuffix = listPage > 1 ? '?history=' + listPage : ''
  const heading = useRef<HTMLHeadingElement>(null)
  const evidence = useRef<HTMLElement>(null)
  const inspectedIndex = inspected?.index

  function scoped(changes: Record<string, string>) {
    const next = new URLSearchParams(query)
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    return pathname + (next.size ? '?' + next : '')
  }

  useEffect(() => {
    if (detail?.id && !route.exception) heading.current?.focus()
  }, [detail?.id, route.exception])
  useEffect(() => {
    if (inspectedIndex !== undefined) evidence.current?.focus()
  }, [inspectedIndex])

  const retry = { kind: 'error' as const, retry: refresh }
  return <section className="recon-workspace" aria-labelledby="reconciliation-title">
    <h2 id="reconciliation-title" className={selected ? 'recon-sr' : undefined}>Reconciliation workbench</h2>
    {!selected ? <>
      <p className="recon-intro">Review execution and matching outcomes separately. Open a run to inspect its evidence.</p>
      {list?.error && <SectionState {...retry} heading="Run history is unavailable"/>}
      {list?.data?.items.length ? <div className="recon-panel"><table className="recon-table recon-history-table" role="table"><thead role="rowgroup"><tr role="row">
        <th scope="col">Run</th><th scope="col">Execution</th><th scope="col">Financial outcome</th><th scope="col">Created</th>
      </tr></thead><tbody role="rowgroup">{list.data.items.map(item => {
        const counts = totals(item)
        return <tr role="row" key={item.id} data-exceptions={Boolean(counts?.exceptions)}>
          <td role="cell"><RouteLink className="command-text-link" href={runPath(item.id) + historySuffix}>{item.name}</RouteLink>
            {item.parent_id && <small>Has a preceding run</small>}</td>
          <td role="cell"><span className="recon-row-label" aria-hidden="true">Execution</span><Execution run={item}/></td>
          <td role="cell"><span className="recon-row-label" aria-hidden="true">Financial outcome</span><strong>{outcome(item)}</strong>
            {counts && <small>{counts.matched} matched pairs · {counts.exceptions} exception groups</small>}</td>
          <td role="cell"><span className="recon-row-label" aria-hidden="true">Created</span>{utc(item.created_at)}</td>
        </tr>
      })}</tbody></table></div> : !list?.error && <SectionState kind={list?.data ? 'empty' : 'loading'}
        heading={list?.data ? 'No runs on this page' : 'Loading run history…'}/>}
      {list?.data && <nav className="pages" aria-label="Run history pagination">
        {listPage > 1 && <RouteLink className="command-button" href={base + (listPage > 2 ? '?history=' + (listPage - 1) : '')}>Previous runs</RouteLink>}
        <span>Page {listPage} · {list.data.items.length} loaded</span>
        {list.data.has_more && listPage < 501 && <RouteLink className="command-button" href={base + '?history=' + (listPage + 1)}>Next runs</RouteLink>}
      </nav>}
    </> : <>
      <RouteLink className="command-text-link" href={history}>Back to run history</RouteLink>
      {run?.error && <SectionState {...retry} heading="Run details are unavailable"/>}
      {!detail ? !run?.error && <SectionState kind="loading" heading="Loading run evidence…"/> : <article aria-label="Reconciliation run">
        <header className="recon-heading">
          <h3 tabIndex={-1} ref={heading}>{detail.name}</h3>
          <div><Execution run={detail}/><span>Created {utc(detail.created_at)}</span>
            {detail.finished_at && <span>Finished {utc(detail.finished_at)}</span>}</div>
        </header>
        <RunSummary detail={detail}/>
        <div className="recon-layout">
          <div className="recon-stack">
            <section className="recon-panel recon-box" aria-labelledby="results-title">
              <h4 id="results-title">Result groups</h4>
              {detail.counts ? <>
                <div className="recon-category-links">
                  {Object.entries(categories).filter(([key]) => !matches.includes(key) && (detail.counts?.[key] ?? 0) > 0)
                    .map(([key, name]) => <RouteLink key={key} className="command-button" current={category === key}
                      href={scoped({ category: key, page: '', exception: '' })}>{name} <strong>{detail.counts?.[key]}</strong></RouteLink>)}
                </div>
                <div className="recon-results-controls"><label htmlFor="recon-category">Result category</label>
                  <select id="recon-category" value={category} onChange={event => navigate(scoped({ category: event.target.value, page: '', exception: '' }))}>
                    <option value="all">All categories</option>
                    <optgroup label="Exceptions">{Object.keys(categories).filter(key => !matches.includes(key)).map(key =>
                      <option key={key} value={key}>{categories[key]} ({detail.counts?.[key] ?? 0})</option>)}</optgroup>
                    <optgroup label="Matched results">{matches.map(key =>
                      <option key={key} value={key}>{categories[key]} ({detail.counts?.[key] ?? 0})</option>)}</optgroup>
                  </select></div>
                {results?.error && <SectionState {...retry} heading="Result groups are unavailable"/>}
                {results?.data?.items.length ? <table className="recon-table recon-results-table"><thead><tr>
                  <th scope="col">Category</th><th scope="col">A / B rows</th><th scope="col">Difference A − B</th><th scope="col">Evidence</th>
                </tr></thead><tbody>{results.data.items.map(item => <tr key={item.index}>
                  <td>{categories[item.category]}</td><td>{item.count_a} / {item.count_b}</td><td className="recon-amount"><Difference item={item}/></td>
                  <td><RouteLink className="command-text-link" href={scoped({ exception: String(item.index), category })}>Inspect group {item.index}</RouteLink></td>
                </tr>)}</tbody></table> : !results?.error && <SectionState kind={results?.data ? 'empty' : 'loading'}
                  heading={results?.data ? 'No groups on this page' : 'Loading result groups…'}/>}
                {results?.data && <nav className="pages" aria-label="Result groups pagination">
                  {page > 1 && <RouteLink className="command-button" href={scoped({ category, page: page === 2 ? '' : String(page - 1), exception: '' })}>Previous results</RouteLink>}
                  <span>Page {page} · {results.data.items.length} groups loaded</span>
                  {results.data.has_more && page < 2001 && <RouteLink className="command-button" href={scoped({ category, page: String(page + 1), exception: '' })}>Next results</RouteLink>}
                </nav>}
              </> : <p>Result counts become available once a report is recorded.</p>}
            </section>
            {route.exception && <section ref={evidence} tabIndex={-1} className="recon-panel recon-box recon-inspection" aria-labelledby="group-title">
              <h4 id="group-title">Group {route.exception} evidence</h4>
              {inspected ? <>
                <p>{categories[inspected.category]}</p>
                <dl className="recon-facts"><dt>Source A rows</dt><dd>{inspected.count_a}</dd>
                  <dt>Source B rows</dt><dd>{inspected.count_b}</dd>
                  <dt>Difference A − B</dt><dd className="recon-amount"><Difference item={inspected}/></dd>
                  <dt>Currency</dt><dd>{inspected.currency ?? 'Unavailable'}</dd></dl>
                {!matches.includes(inspected.category) && <Copilot simulatedOnly key={inspected.index} reconciliationRunId={detail.id} exceptionIndex={inspected.index}/>}
              </> : <p>{exact?.data || exact?.error || !detail.counts ? 'This group is unavailable in the recorded report.' : 'Loading group evidence…'}</p>}
              <RouteLink className="command-text-link" href={scoped({ exception: '' })}>Close group evidence</RouteLink>
            </section>}
            {detail.parent_id && <section className="recon-panel recon-box" aria-labelledby="comparison-title">
              <h4 id="comparison-title">Immediate predecessor comparison</h4>
              {previous?.error ? <SectionState {...retry} heading="Previous run is unavailable"/>
                : previous?.data ? <Comparison current={detail} previous={previous.data}/> : <p role="status">Loading previous run…</p>}
              <RouteLink className="command-text-link" href={runPath(detail.parent_id) + historySuffix}>View preceding run</RouteLink>
            </section>}
          </div>
          <aside className="recon-stack" aria-label="Source and investigation context">
            <Sources detail={detail}/>
            <section className="recon-panel recon-box" aria-labelledby="investigation-title">
              <h4 id="investigation-title">Investigation actions</h4>
              {detail.incident_id && detail.sources[0] && <p><RouteLink className="command-text-link" detail
                href={'/deliveries/' + detail.sources[0].id + '/incidents/' + detail.incident_id}>View linked incident</RouteLink></p>}
              <Copilot simulatedOnly key={detail.id} reconciliationRunId={detail.id}/>
              {canOperate && list?.data?.rerun_enabled && ['COMPLETED', 'FAILED'].includes(detail.status)
                && <Rerun key={detail.id} id={detail.id} onQueued={id => navigate(runPath(id) + historySuffix)}/>}
            </section>
          </aside>
        </div>
      </article>}
    </>}
  </section>
}

function RunSummary({ detail }: { detail: RunDetail }) {
  const counts = totals(detail)
  return <section className="recon-summary" aria-label="Recorded reconciliation outcome">
    <div><h4>{outcome(detail)}</h4><p>{counts ? counts.matched + ' matched pairs · ' + counts.exceptions + ' exception groups' : 'No recorded result report'}
      {counts && detail.material && ' · Material difference detected'}</p></div>
    <div><h4>Matching configuration</h4><p>Match by {title(detail.match_on)} · Tolerance <span className="recon-amount">{detail.tolerance}</span></p></div>
    <div><h4>Execution attempts</h4><p>{detail.attempts}{detail.error_code && ' · ' + title(detail.error_code)}</p></div>
  </section>
}

function Sources({ detail }: { detail: RunDetail }) {
  return <section className="recon-panel recon-box" aria-labelledby="recon-source-title">
    <h4 id="recon-source-title"><FileStack size={18} aria-hidden="true"/> Source evidence</h4>
    <p>Pinned file IDs identify the versions used for this run. Delivery links open the current record.</p>
    <ul className="recon-sources-list">{detail.sources.map((source, index) => {
      const side = index === 0 ? 'A' : 'B'
      const file = index === 0 ? detail.file_a_id : detail.file_b_id
      return <li key={side}>
        <h5>Source {side} · {source.integration}</h5>
        <p>{title(source.delivery_type)} · {source.business_date}</p>
        <p>Current delivery status <strong>{title(source.status)}</strong></p>
        <details><summary>{file ? 'Pinned file ID' : 'Pinned file unavailable'}</summary>
          {file ? <code>{file}</code> : <p>This run has no recorded file pin for this source.</p>}</details>
        <RouteLink className="command-text-link" detail href={'/deliveries/' + source.id}>View source {side} delivery</RouteLink>
      </li>
    })}</ul>
    <details><summary>Run identifiers</summary><p>Run <code>{detail.id}</code></p>
      {detail.parent_id && <p>Previous run <code>{detail.parent_id}</code></p>}</details>
  </section>
}

function Difference({ item }: { item: Result }) {
  return item.difference === null ? 'Unavailable' : <>{item.difference}{item.currency && ' ' + item.currency}</>
}

function Comparison({ current, previous }: { current: RunDetail; previous: RunDetail }) {
  const before = totals(previous)
  const after = totals(current)
  return <>
    <p>Compare recorded totals. Individual exceptions cannot be paired across these reports.</p>
    <div className="recon-comparison-head">{[previous, current].map((run, index) => <div key={run.id}>
      <h5>{index === 0 ? 'Previous run' : 'Selected run'}</h5><strong>{run.name}</strong>
      <p><Execution run={run}/> {outcome(run)}{run.counts && run.material && ' · Material difference detected'}</p>
      <p>{utc(run.finished_at ?? run.created_at)}</p>
      <details><summary>Pinned versions</summary><p>Source A <code>{run.file_a_id ?? 'Unavailable'}</code></p>
        <p>Source B <code>{run.file_b_id ?? 'Unavailable'}</code></p></details>
    </div>)}</div>
    <table className="recon-table recon-compare-table"><thead><tr>
      <th scope="col">Recorded result</th><th scope="col">Previous</th><th scope="col">Selected</th><th scope="col">Change</th>
    </tr></thead><tbody>{([
      ['Matched pairs', before?.matched, after?.matched],
      ['Exception groups', before?.exceptions, after?.exceptions],
      ...Object.entries(categories).map(([key, name]) => [name,
        previous.counts ? previous.counts[key] ?? 0 : undefined, current.counts ? current.counts[key] ?? 0 : undefined]),
    ] as [string, number | undefined, number | undefined][]).map(([name, prior, next]) => {
      const delta = prior === undefined || next === undefined ? undefined : next - prior
      return <tr key={name}><th scope="row">{name}</th><td>{prior ?? '—'}</td><td>{next ?? '—'}</td>
        <td>{delta === undefined ? '—' : delta > 0 ? '+' + delta : delta}</td></tr>
    })}</tbody></table>
  </>
}

function Rerun({ id, onQueued }: { id: string; onQueued: (id: string) => void }) {
  const [confirmed, setConfirmed] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const requestId = useRef<string>(undefined)
  return <form className="reprocess" onSubmit={async event => {
    event.preventDefault()
    if (!confirmed || submitting) return
    requestId.current ??= crypto.randomUUID()
    setSubmitting(true)
    setError('')
    try {
      const response = await apiFetch('/api/dashboard' + runPath(id) + '/rerun', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmed: true, request_id: requestId.current }),
      })
      if (!response.ok) {
        if (response.status === 409) setConfirmed(false)
        setError(response.status === 409 ? 'A rerun conflicts with the current definition state. Refresh before trying again.'
          : 'Could not queue a rerun.')
        return
      }
      onQueued((await response.json()).run_id)
    } catch {
      setError('Could not confirm the response. Retrying uses the same request ID.')
    } finally {
      setSubmitting(false)
    }
  }}>
    <p>Queue a new run from this definition and retain the original evidence.</p>
    <label><input type="checkbox" checked={confirmed} disabled={submitting} onChange={event => setConfirmed(event.target.checked)}/>
      Confirm a new reconciliation run</label>
    <button className="command-button" disabled={!confirmed || submitting}>{submitting ? 'Queuing…' : 'Queue reconciliation rerun'}</button>
    {error && <p role="alert">{error}</p>}
  </form>
}

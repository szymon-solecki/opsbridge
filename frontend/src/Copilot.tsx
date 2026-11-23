import { apiFetch } from './session'
import { useEffect, useId, useRef, useState } from 'react'
import { RouteLink, routeId } from './navigation'
import { timestamp, title } from './Operations'
import './operational-experience.css'

type Provider = 'mock' | 'openai' | 'disabled'
type Evidence = { ref: string; kind: string; record_id: string; timestamp: string; fact: string; label?: string; delivery_id?: string }
type Finding = { key: string; hypothesis: string; next_step: string; references: string[] }
type Result = {
  provider: Provider; summary: string; summary_references: string[]; observations: string[]
  hypotheses: Finding[]; evidence: Evidence[]; missing_evidence: string[]; truncated: boolean
}

const providerLabels: Record<Provider, string> = { mock: 'Simulated analysis', openai: 'OpenAI', disabled: 'Unavailable' }
const examples = [
  'Which integrations currently have unresolved incidents?',
  'Which deliveries breached their SLA?',
  "Summarize today's operational problems.",
  'Why did the cash-position delivery fail?',
]
const errors: Record<string, string> = {
  unsupported_question: 'Choose a suggested question or ask “Why did delivery <ID> fail?” with a delivery ID.',
  provider_timeout: 'The provider timed out. Try again.',
  provider_unavailable: 'The provider could not be reached.',
  provider_disabled: 'The Copilot provider is unavailable. Check its server configuration.',
  invalid_provider_response: 'The provider returned a response that could not be verified.',
  evidence_not_found: 'This record is no longer available.',
  evidence_unavailable: 'OpsBridge could not load the evidence.',
  copilot_busy: 'The Copilot is busy. Wait a moment and try again.',
}

export function Copilot({ incidentId, acknowledged, reconciliationRunId, exceptionIndex, standalone = false, simulatedOnly = true }: {
  incidentId?: string; acknowledged?: boolean; reconciliationRunId?: string; exceptionIndex?: number; standalone?: boolean; simulatedOnly?: boolean
}) {
  const [mode, setMode] = useState<Provider>()
  const [question, setQuestion] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Result>()
  const [visible, setVisible] = useState(standalone)
  const [statusRevision, setStatusRevision] = useState(0)
  const scopeId = useId()
  const evidenceList = useRef<HTMLDetailsElement>(null)

  useEffect(() => {
    if (!visible || mode) return
    const request = new AbortController()
    void apiFetch('/api/dashboard/copilot/status', { signal: request.signal })
      .then(response => response.ok ? response.json() : null)
      .then(data => { if (!request.signal.aborted) setMode(data && Object.hasOwn(providerLabels, data.provider) ? data.provider : 'disabled') })
      .catch(() => { if (!request.signal.aborted) setMode('disabled') })
    return () => request.abort()
  }, [visible, mode, statusRevision])

  async function investigate(query?: string) {
    if (pending || !mode || mode === 'disabled' || (simulatedOnly && mode !== 'mock')) return
    setPending(true)
    setError('')
    setResult(undefined)
    try {
      const response = await apiFetch('/api/dashboard/copilot/investigate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ incident_id: incidentId, question: query,
          reconciliation_run_id: reconciliationRunId, exception_index: exceptionIndex }), signal: AbortSignal.timeout(26_000),
      })
      const data = await response.json()
      if (!response.ok) {
        setError(errors[data.detail] ?? 'The Copilot could not complete this request.')
        return
      }
      setResult(data)
      setMode(data.provider)
    } catch (cause) {
      setError(cause instanceof DOMException && cause.name === 'TimeoutError'
        ? 'The request timed out. Try again.' : 'The Copilot could not complete this request.')
    } finally {
      setPending(false)
    }
  }

  const index = new Map(result?.evidence.map(record => [record.ref, record]))
  const evidenceId = (ref: string) => scopeId + '-' + ref
  const citations = (refs: string[]) => <div className="copilot-references">{refs.map(ref => {
    const row = index.get(ref)
    return row && <a key={ref} href={'#' + evidenceId(ref)} onClick={event => {
      if (event.button || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return
      event.preventDefault()
      if (evidenceList.current) evidenceList.current.open = true
      document.getElementById(evidenceId(ref))?.focus()
    }}>{ref} · {evidenceLabel(row)}</a>
  })}</div>
  const unavailable = mode === 'disabled' || (simulatedOnly && mode === 'openai')
  const canAnalyze = Boolean(mode && !unavailable && !pending)
  const scoped = Boolean(incidentId || reconciliationRunId)
  const Container = standalone ? 'section' : 'details'
  const Header = standalone ? 'h2' : 'summary'
  return <Container className={scoped ? 'copilot copilot-incident' : 'panel copilot copilot-workspace'} onToggle={event => {
    if (event.currentTarget instanceof HTMLDetailsElement) setVisible(event.currentTarget.open)
  }}>
    <Header>{incidentId ? 'Investigate with Copilot' : reconciliationRunId
      ? (exceptionIndex ? 'Investigate exception with Copilot' : 'Summarize run with Copilot') : 'Operations Copilot'}
      {mode && <span className="badge">{simulatedOnly && mode !== 'mock' ? 'Simulation unavailable' : providerLabels[mode]}</span>}</Header>
    <p>Read-only investigation of recorded OpsBridge evidence. Review recommendations before acting.</p>
    {!mode && <p role="status">Checking analysis availability…</p>}
    {unavailable && <p>Simulated analysis is unavailable. <button type="button" onClick={() => {
      setMode(undefined); setStatusRevision(value => value + 1)
    }}>Check again</button></p>}
    {scoped
      ? <div className="copilot-actions">
          <button disabled={!canAnalyze} onClick={() => void investigate()}>{incidentId ? 'Analyze incident'
            : exceptionIndex ? 'Analyze exception' : 'Analyze run'}</button>
          {acknowledged && <button disabled={!canAnalyze} onClick={() => void investigate('What happened before this incident was acknowledged?')}>
            Review before acknowledgement</button>}
        </div>
      : <form onSubmit={event => { event.preventDefault(); if (question.trim()) void investigate(question) }}>
          <label>Operations question <input value={question} onChange={event => setQuestion(event.target.value)}
            required maxLength={320} autoComplete="off"/></label>
          <button disabled={!canAnalyze || !question.trim()}>Ask Copilot</button>
          <details className="copilot-suggestions" open={!pending && !result}>
            <summary>Suggested questions</summary>
            <div className="copilot-actions">{examples.map(example => <button type="button" key={example}
              onClick={() => setQuestion(example.replace(/\.$/, ''))}>{example}</button>)}</div>
          </details>
        </form>}
    {standalone && !pending && !error && !result && !unavailable &&
      <p className="copilot-idle">Select a suggested question or enter your own to review recorded evidence.</p>}
    {pending && <p role="status">Reviewing persisted evidence…</p>}
    {error && <p role="alert">{error}</p>}
    {result && <div className="copilot-result" aria-label="Investigation result">
      <section className="copilot-conclusion"><h3>Operational conclusion</h3><p>{result.summary}</p>
        {citations(result.summary_references)}</section>
      <section className="copilot-step"><h3>Recorded facts</h3>
        {result.observations.length ? <ul>{result.observations.map(ref => {
          const row = index.get(ref)
          return row && <li key={ref}>{row.label && <strong>{row.label} · </strong>}{row.fact}{citations([ref])}</li>
        })}</ul> : <p>No matching records were available for this investigation.</p>}</section>
      <div className="copilot-findings">
        <section className="copilot-step"><h3>Hypotheses</h3>
          {result.hypotheses.length ? <ul>{result.hypotheses.map(item => <li key={item.key}>
            {item.hypothesis}{citations(item.references)}</li>)}</ul>
            : <p>The available evidence does not support a specific hypothesis.</p>}</section>
        <section className="copilot-step"><h3>Recommended next steps</h3>
          {result.hypotheses.length ? <ol>{result.hypotheses.map(item => <li key={item.key}>
            {item.next_step}{citations(item.references)}</li>)}</ol> : <p>No specific next step was supported by the returned evidence.</p>}</section>
      </div>
      {result.missing_evidence.length > 0 && <section className="copilot-step"><h3>Evidence gaps</h3>
        <ul>{result.missing_evidence.map(item => <li key={item}>{item}</li>)}</ul></section>}
      {result.truncated && <p>The evidence set was limited. Additional records may exist.</p>}
      {result.evidence.length > 0 && <details className="copilot-evidence" ref={evidenceList}><summary>All evidence ({result.evidence.length})</summary>
        {result.evidence.map(item => {
          const link = evidenceLink(item)
          return <article tabIndex={-1} id={evidenceId(item.ref)} key={item.ref}>
            <h4>{item.ref} · {evidenceLabel(item)}</h4>
            <p><time dateTime={item.timestamp}>{timestamp(item.timestamp)} UTC</time></p>
            <p>{item.fact}</p>
            {link && <RouteLink className="command-text-link" href={link.href} detail={link.href.startsWith('/deliveries/')}>{link.name}</RouteLink>}
            <details><summary>Technical identifier</summary><code>{item.record_id}</code></details>
          </article>
        })}
      </details>}
    </div>}
  </Container>
}

function evidenceLabel(row: Evidence) {
  return row.label ? (/^[A-Z0-9_]+$/.test(row.label) ? title(row.label) : row.label) : title(row.kind)
}

function evidenceLink(row: Evidence) {
  const id = routeId(row.record_id)
  const delivery = routeId(row.delivery_id ?? null)
  if (id && row.kind === 'delivery') return { name: 'Open delivery evidence', href: '/deliveries/' + id }
  if (id && row.kind === 'integration') return { name: 'View integration deliveries', href: '/deliveries?integration=' + id }
  if (delivery && id && ['incident', 'incident_acknowledgement', 'incident_resolution'].includes(row.kind)) {
    return { name: 'Open incident evidence', href: '/deliveries/' + delivery + '/incidents/' + id }
  }
  if (id && ['reconciliation_run', 'reconciliation_summary'].includes(row.kind)) {
    return { name: 'Open reconciliation run', href: '/reconciliation/runs/' + id }
  }
  if (row.kind === 'reconciliation_exception') {
    const [run, ordinal, extra] = row.record_id.split(':')
    if (extra === undefined && routeId(run) && /^[1-9][0-9]{0,4}$/.test(ordinal) && Number(ordinal) <= 40000) {
      return { name: 'Open exception group', href: '/reconciliation/runs/' + routeId(run) + '?exception=' + ordinal }
    }
  }
}

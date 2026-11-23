import { useState } from 'react'
import { Bell, Shield } from 'lucide-react'
import { apiFetch, type Session } from './session'
import { RouteLink, useNavigation } from './navigation'
import { SectionState } from './Shell'
import { useResource } from './dashboardData'
import { problemLabels, title } from './Operations'
import './operational-experience.css'

type Role = Session['role']
type Account = Pick<Session, 'id' | 'username' | 'role'> & { active: boolean }
type Recipient = { owner: string; email: string }
type Step = { after_seconds: number; recipients: Recipient[] }
type Rule = {
  integration_id: string | null; incident_type: string | null; severity: string | null
  opened: Recipient[] | null; resolved: Recipient[] | null; escalations: Step[] | null
}
type Policy = { rules: unknown[] }
const roles: Role[] = ['VIEWER', 'OPERATOR', 'ADMIN']
const severities = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
const policyPath = '/notification-policies'
const emptyRule = (): Rule => ({ integration_id: null, incident_type: null, severity: null, opened: null, resolved: null, escalations: null })
const json = (body: unknown, method = 'POST'): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})
const heading = (rule: Rule) => [
  rule.integration_id ? 'Specific integration' : 'All integrations',
  rule.incident_type ? problemLabels[rule.incident_type] ?? title(rule.incident_type) : 'All incident types',
  rule.severity ? title(rule.severity) : 'All severities',
].join(' · ')

function record(value: unknown, fields: string[]): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).every(key => fields.includes(key))
}

function recipients(value: unknown): value is Recipient[] {
  return Array.isArray(value) && value.every(item =>
    record(item, ['owner', 'email']) && typeof item.owner === 'string' && typeof item.email === 'string')
}

function structured(value: unknown[]): Rule[] | undefined {
  if (!value.every(item => record(item, Object.keys(emptyRule())) &&
    (item.integration_id == null || typeof item.integration_id === 'string') &&
    (item.incident_type == null || (typeof item.incident_type === 'string' && Object.hasOwn(problemLabels, item.incident_type))) &&
    (item.severity == null || (typeof item.severity === 'string' && severities.includes(item.severity))) &&
    (item.opened == null || recipients(item.opened)) && (item.resolved == null || recipients(item.resolved)) &&
    (item.escalations == null || (Array.isArray(item.escalations) && item.escalations.every(step =>
      record(step, ['after_seconds', 'recipients']) && Number.isInteger(step.after_seconds) && recipients(step.recipients)))))) return
  return value.map(item => ({ ...emptyRule(), ...(item as Rule) }))
}

export function Administration({ ownId }: { ownId: string }) {
  const { query } = useNavigation()
  const policies = query.get('view') === 'policies'
  return <div className="admin-workspace">
    <nav className="experience-nav" aria-label="Administration views">
      <RouteLink href="/administration" current={!policies}>Operator accounts</RouteLink>
      <RouteLink href="/administration?view=policies" current={policies}>Notification policies</RouteLink>
    </nav>
    <div hidden={policies}><Accounts ownId={ownId}/></div>
    <div hidden={!policies}><PolicySettings/></div>
  </div>
}

function Accounts({ ownId }: { ownId: string }) {
  const [revision, setRevision] = useState(0)
  const source = useResource<Account[]>('/operators', revision, '/api/auth')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<Role>('VIEWER')
  const [change, setChange] = useState<{ account: Account; body: { role?: Role; active?: boolean }; description: string }>()
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<{ text: string; error?: boolean }>()
  const reload = () => setRevision(value => value + 1)
  async function save(path: string, options: RequestInit, success: string) {
    if (busy) return
    setBusy(true)
    setNote(undefined)
    try {
      const response = await apiFetch('/api/auth/operators' + path, options)
      if (!response.ok) {
        setNote({ text: response.status === 403 ? 'Permission denied.' : 'Check the account details and try again.', error: true })
        return
      }
      setChange(undefined)
      setNote({ text: success })
      reload()
      return true
    } catch {
      setNote({ text: 'The account service is unavailable.', error: true })
    } finally {
      setBusy(false)
    }
  }

  return <div className="experience-layout">
    <section className="experience-panel" aria-labelledby="accounts-title">
      <h2 id="accounts-title"><Shield size={18} aria-hidden="true"/> Operator accounts</h2>
      <p>Viewer can read evidence. Operator can take permitted operational actions. Admin can manage access and notification rules.</p>
      {note && <p role={note.error ? 'alert' : 'status'}>{note.text}</p>}
      {source?.error && <SectionState kind="error" heading="Account list unavailable" retry={reload}/>}
      {source?.data?.length ? <ul className="admin-accounts">{source.data.map(account => <li key={account.id}>
        <div><strong>{account.username}</strong> {account.id === ownId && <small>Current account</small>}
          <p><span className={'badge ' + (account.active ? 'completed' : '')}>{account.active ? 'Active' : 'Inactive'}</span></p></div>
        <div className="admin-account-actions">
          <label>Role<select aria-label={account.username + ' role'} value={change?.account.id === account.id ? change.body.role ?? account.role : account.role}
            disabled={busy || account.id === ownId} onChange={event => {
              const next = event.target.value as Role
              setChange(next === account.role ? undefined : { account, body: { role: next }, description: 'Change role to ' + next })
            }}>{roles.map(value => <option key={value}>{value}</option>)}</select></label>
          <button type="button" disabled={busy || account.id === ownId} onClick={() => setChange({
            account, body: { active: !account.active }, description: account.active ? 'Deactivate account' : 'Activate account',
          })}>{account.active ? 'Deactivate' : 'Activate'}</button>
        </div>
        {change?.account.id === account.id && <div className="admin-review">
          <p><strong>{change.description} for {account.username}?</strong> Existing sessions will be revoked when access changes.</p>
          <button disabled={busy} onClick={() => void save('/' + account.id, json(change.body, 'PATCH'), 'Account updated.')}>Confirm account change</button>
          <button disabled={busy} onClick={() => setChange(undefined)}>Cancel</button>
        </div>}
      </li>)}</ul> : !source?.error && <SectionState kind={source?.data ? 'empty' : 'loading'}
        heading={source?.data ? 'No accounts returned' : 'Loading accounts…'}/>}
      {source?.data?.length === 200 && <p>The account list displays up to 200 records.</p>}
    </section>
    <section className="experience-panel admin-form" aria-labelledby="create-title">
      <h2 id="create-title">Create operator</h2><p>The account starts active. Use the least privileged role needed.</p>
      <form onSubmit={async event => {
        event.preventDefault()
        const created = await save('', json({ username, password, role }), 'Operator created.')
        setPassword('')
        if (created) { setUsername(''); setRole('VIEWER') }
      }}>
        <label>New username<input value={username} onChange={event => setUsername(event.target.value)}
          minLength={3} maxLength={64} required autoComplete="off"/></label>
        <label>Initial password<input type="password" value={password} onChange={event => setPassword(event.target.value)}
          minLength={12} maxLength={256} required autoComplete="new-password"/></label>
        <label>New operator role<select value={role} onChange={event => setRole(event.target.value as Role)}>
          {roles.map(value => <option key={value}>{value}</option>)}</select></label>
        <button className="command-button command-primary" disabled={busy}>Create operator</button>
      </form>
    </section>
  </div>
}

function PolicySettings() {
  const [revision, setRevision] = useState(0)
  const source = useResource<Policy>(policyPath, revision)
  const [saved, setSaved] = useState<unknown[]>()
  const [draft, setDraft] = useState<Rule[]>()
  const [advanced, setAdvanced] = useState<string>()
  const [preview, setPreview] = useState<unknown[]>()
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ text: string; error?: boolean }>()
  const current = saved ?? source?.data?.rules
  const rules = current && structured(current)

  function prepare(value: unknown) {
    setNotice(undefined)
    if (!Array.isArray(value) || value.length > 100) {
      setNotice({ text: 'Enter an array with at most 100 rules.', error: true })
      return
    }
    const known = structured(value)
    if (known) {
      const scopes = new Set(known.map(rule => [rule.integration_id?.toLowerCase(), rule.incident_type, rule.severity].join('|')))
      if (scopes.size !== known.length || known.some(rule => rule.escalations?.some((step, index, steps) =>
        step.recipients.length === 0 || (index > 0 && step.after_seconds <= steps[index - 1].after_seconds)))) {
        setNotice({ text: 'Use unique rule scopes, recipients on every escalation step, and strictly increasing delays.', error: true })
        return
      }
    }
    setPreview(value)
  }

  async function apply() {
    if (!preview || busy) return
    setBusy(true)
    setNotice(undefined)
    try {
      const response = await apiFetch('/api/dashboard' + policyPath, json(preview, 'PUT'))
      if (!response.ok) {
        setNotice({ text: response.status === 403 ? 'Permission denied.' : 'The policy was not saved. Check the rule scopes, recipients and escalation delays.', error: true })
        return
      }
      setSaved((await response.json() as Policy).rules)
      setDraft(undefined); setAdvanced(undefined); setPreview(undefined)
      setNotice({ text: 'Notification policy saved.' })
    } catch {
      setNotice({ text: 'The policy service is unavailable.', error: true })
    } finally {
      setBusy(false)
    }
  }

  return <section className="experience-panel policy-workspace" aria-labelledby="policy-title">
    <h2 id="policy-title"><Bell size={18} aria-hidden="true"/> Notification policies</h2>
    <p>Rules apply to future notification jobs. Existing schedules keep their recorded policy.</p>
    {notice && <p role={notice.error ? 'alert' : 'status'}>{notice.text}</p>}
    {source?.error && <SectionState kind="error" heading="Notification policies unavailable" retry={() => setRevision(value => value + 1)}/>}
    {!current && !source?.error && <SectionState kind="loading" heading="Loading notification policies…"/>}
    {current && draft === undefined && advanced === undefined && <>
      {rules ? <PolicySummary rules={rules}/> : <p>Open the advanced editor to view this document without changing its fields.</p>}
      <div className="experience-actions">
        {rules && <button className="command-button command-primary" onClick={() => setDraft(rules)}>Edit policies</button>}
        <button className="command-button" onClick={() => setAdvanced(JSON.stringify(current, null, 2))}>Advanced policy editor</button>
      </div>
    </>}
    {draft !== undefined && !preview && <form className="admin-form" onInvalidCapture={event => {
      const disclosure = (event.target as HTMLElement).closest('details')
      if (disclosure) disclosure.open = true
    }} onSubmit={event => { event.preventDefault(); prepare(draft) }}>
      {draft.map((rule, index) => <RuleEditor key={index} rule={rule} number={index + 1}
        onChange={next => setDraft(value => value?.map((item, position) => position === index ? next : item))}
        remove={() => setDraft(value => value?.filter((_, position) => position !== index))}/>)}
      <div className="experience-actions">
        <button type="button" disabled={draft.length >= 100} onClick={() => setDraft([...draft, emptyRule()])}>Add rule</button>
        <button className="command-button command-primary">Review changes</button>
        <button type="button" onClick={() => setDraft(undefined)}>Cancel edit</button>
      </div>
    </form>}
    {advanced !== undefined && !preview && <form className="admin-form" onSubmit={event => {
      event.preventDefault()
      try { prepare(JSON.parse(advanced)) } catch { setNotice({ text: 'Enter valid JSON.', error: true }) }
    }}>
      <label>Policy document (JSON)<textarea value={advanced} rows={13} onChange={event => setAdvanced(event.target.value)}/></label>
      <div className="experience-actions"><button className="command-button command-primary">Review changes</button>
        <button type="button" onClick={() => setAdvanced(undefined)}>Cancel edit</button></div>
    </form>}
    {preview && <section className="admin-review" aria-labelledby="review-title">
      <h3 id="review-title">Review pending policy changes</h3>
      <p>{preview.length} rules will replace the saved policy. Saving affects future jobs.</p>
      {structured(preview) ? <PolicySummary rules={structured(preview)!}/> : <pre>{JSON.stringify(preview, null, 2)}</pre>}
      <div className="experience-actions"><button className="command-button command-primary" disabled={busy}
        onClick={() => void apply()}>Save notification policy</button>
        <button disabled={busy} onClick={() => setPreview(undefined)}>Back to editing</button></div>
    </section>}
  </section>
}

function PolicySummary({ rules }: { rules: Rule[] }) {
  function owners(entries: Recipient[] | null) {
    return entries === null ? 'Inherit matching rule' : entries.length ? entries.map(item => item.owner).join(', ') : 'Disabled'
  }
  return rules.length ? <ul className="admin-policies">{rules.map((rule, index) => <li key={index}>
    <h3>{heading(rule)}</h3>
    <dl><div><dt>On opening</dt><dd>{owners(rule.opened)}</dd></div><div><dt>On resolution</dt><dd>{owners(rule.resolved)}</dd></div>
      <div><dt>Escalation</dt><dd>{rule.escalations === null ? 'Inherit matching rule' : rule.escalations.length
        ? rule.escalations.map(step => step.after_seconds + 's · ' + owners(step.recipients)).join(' / ') : 'Disabled'}</dd></div></dl>
    <details><summary>Recipient addresses and scope</summary>
      {rule.integration_id && <p>Integration ID <code>{rule.integration_id}</code></p>}
      <p>Opening · {rule.opened?.map(item => item.email).join(', ') || owners(rule.opened)}</p>
      <p>Resolution · {rule.resolved?.map(item => item.email).join(', ') || owners(rule.resolved)}</p>
      {rule.escalations?.map(step => <p key={step.after_seconds}>After {step.after_seconds}s · {step.recipients.map(item => item.email).join(', ')}</p>)}</details>
  </li>)}</ul> : <p>No rules configured.</p>
}

function RuleEditor({ rule, number, onChange, remove }: { rule: Rule; number: number; onChange: (rule: Rule) => void; remove: () => void }) {
  return <details className="admin-rule" open={number === 1 || undefined}>
    <summary>Rule {number} · {heading(rule)}</summary>
    <div className="admin-fields">
      <label>Integration ID (optional)<input value={rule.integration_id ?? ''} maxLength={36}
        pattern="[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
        onChange={event => onChange({ ...rule, integration_id: event.target.value || null })}/></label>
      <label>Incident type<select value={rule.incident_type ?? ''} onChange={event => onChange({ ...rule, incident_type: event.target.value || null })}>
        <option value="">All incident types</option>{Object.entries(problemLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>Severity<select value={rule.severity ?? ''} onChange={event => onChange({ ...rule, severity: event.target.value || null })}>
        <option value="">All severities</option>{severities.map(value => <option key={value} value={value}>{title(value)}</option>)}</select></label>
    </div>
    <Recipients label="Opening notifications" value={rule.opened} onChange={opened => onChange({ ...rule, opened })}/>
    <Recipients label="Resolution notifications" value={rule.resolved} onChange={resolved => onChange({ ...rule, resolved })}/>
    <fieldset><legend>Escalation</legend>
      <Mode label="Escalation behavior" value={rule.escalations} onChange={mode => onChange({ ...rule,
        escalations: mode === 'inherit' ? null : mode === 'disabled' ? [] : [{ after_seconds: 60, recipients: [{ owner: '', email: '' }] }],
      })}/>
      {rule.escalations?.map((step, index) => <fieldset key={index}><legend>Step {index + 1}</legend>
        <label>Delay in seconds<input type="number" min={1} max={2592000} step={1} required value={step.after_seconds}
          onChange={event => onChange({ ...rule, escalations: rule.escalations?.map((entry, i) => i === index
            ? { ...entry, after_seconds: Number(event.target.value) } : entry) ?? [] })}/></label>
        <RecipientRows value={step.recipients} onChange={recipients => onChange({ ...rule,
          escalations: rule.escalations?.map((entry, i) => i === index ? { ...entry, recipients } : entry) ?? [],
        })}/>
        <button type="button" onClick={() => onChange({ ...rule, escalations: rule.escalations?.filter((_, i) => i !== index) ?? [] })}>Remove escalation step</button>
      </fieldset>)}
      {(rule.escalations?.length ?? 0) > 0 && <button type="button" disabled={rule.escalations!.length >= 5}
        onClick={() => onChange({ ...rule, escalations: [...rule.escalations!, {
          after_seconds: (rule.escalations!.at(-1)?.after_seconds ?? 0) + 60, recipients: [{ owner: '', email: '' }],
        }] })}>Add escalation step</button>}
    </fieldset>
    <button type="button" onClick={remove}>Remove rule</button>
  </details>
}

type ModeValue = 'inherit' | 'disabled' | 'custom'
function Mode({ label, value, onChange }: { label: string; value: unknown[] | null; onChange: (mode: ModeValue) => void }) {
  return <label>{label}<select aria-label={label} value={value === null ? 'inherit' : value.length === 0 ? 'disabled' : 'custom'}
    onChange={event => onChange(event.target.value as ModeValue)}>
    <option value="inherit">Inherit matching rule</option><option value="disabled">Disabled</option><option value="custom">Custom</option>
  </select></label>
}

function Recipients({ label, value, onChange }: { label: string; value: Recipient[] | null; onChange: (value: Recipient[] | null) => void }) {
  return <fieldset><legend>{label}</legend>
    <Mode label={label + ' behavior'} value={value} onChange={mode => onChange(mode === 'inherit' ? null : mode === 'disabled' ? [] : [{ owner: '', email: '' }])}/>
    {Boolean(value?.length) && <RecipientRows value={value!} onChange={onChange}/>}
  </fieldset>
}

function RecipientRows({ value, onChange }: { value: Recipient[]; onChange: (value: Recipient[]) => void }) {
  return <>
    {value.map((item, index) => <div className="admin-fields" key={index}>
      <label>Owner {index + 1}<input value={item.owner} maxLength={100} required
        onChange={event => onChange(value.map((entry, i) => i === index ? { ...entry, owner: event.target.value } : entry))}/></label>
      <label>Email {index + 1}<input type="email" value={item.email} maxLength={254} required pattern=".+@[A-Za-z0-9.\-]+\.[Tt][Ee][Ss][Tt]"
        onChange={event => onChange(value.map((entry, i) => i === index ? { ...entry, email: event.target.value } : entry))}/></label>
      <button type="button" onClick={() => onChange(value.filter((_, i) => i !== index))}>Remove recipient</button>
    </div>)}
    <button type="button" disabled={value.length >= 20} onClick={() => onChange([...value, { owner: '', email: '' }])}>Add recipient</button>
  </>
}

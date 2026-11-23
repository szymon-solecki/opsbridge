import { Activity, Boxes, ChartNoAxesCombined, ClipboardList, FileStack, GitCompareArrows, LayoutDashboard,
  LogOut, Menu, RefreshCw, Shield, Sparkles, X } from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { type Section, RouteLink, sections, useNavigation } from './navigation'
import type { Session } from './session'

const pages = {
  overview: { title: 'Overview', description: 'Review current conditions, choose what to investigate, and catch up on recent changes.', icon: LayoutDashboard },
  'action-center': { title: 'Action Center', description: 'Triage recorded incidents and detected delivery issues, then open the evidence for each item.', icon: ClipboardList },
  deliveries: { title: 'Deliveries', description: 'Track expected arrivals, current files and processing history.', icon: FileStack },
  reconciliation: { title: 'Reconciliation', description: 'Compare source deliveries and investigate differences in recorded runs.', icon: GitCompareArrows },
  copilot: { title: 'AI Copilot', description: 'Investigate operational issues using recorded evidence.', icon: Sparkles },
  monitoring: { title: 'Monitoring', description: 'Check workspace connectivity and find operational telemetry.', icon: ChartNoAxesCombined },
  administration: { title: 'Administration', description: 'Manage operator access and notification policies.', icon: Shield },
}

function Sidebar({ section, admin, onFollow }: { section: Section | 'not-found'; admin: boolean; onFollow?: () => void }) {
  return <>
    <RouteLink href="/overview" className="command-brand" onFollow={onFollow}>
      <span className="command-mark"><Activity size={21} aria-hidden="true"/></span><span>OpsBridge</span>
    </RouteLink>
    <nav aria-label="Workspace navigation" className="command-nav">
      {sections.filter(id => id !== 'administration' || admin).map(id => {
        const { icon: Icon, title } = pages[id]
        return <RouteLink href={'/' + id} current={section === id} key={id} onFollow={onFollow}>
          <Icon size={18} aria-hidden="true"/><span>{title}</span>
        </RouteLink>
      })}
    </nav>
  </>
}

export function SectionState({ detail, heading, retry, kind = 'empty' }: {
  heading: string; detail?: string; retry?: () => void; kind?: 'empty' | 'loading' | 'error'
}) {
  return <div className={'command-state command-state-' + kind} role={kind === 'loading' ? 'status' : kind === 'error' ? 'alert' : undefined}>
    <strong>{heading}</strong>{detail && <p>{detail}</p>}
    {retry && <button className="command-button" onClick={retry}>Try again</button>}
  </div>
}

export function MetricCard({ label, value, icon: Icon, tone = 'neutral' }: {
  label: string; value?: number | string; icon: typeof Boxes; tone?: string
}) {
  return <div className="metric command-metric"><div className={'metric-icon ' + tone}><Icon size={17} aria-hidden="true"/></div>
    <div><span>{label}</span><strong>{value ?? '—'}</strong></div></div>
}

export function SeverityIndicator({ severity }: { severity: string }) {
  return <span className={'severity-indicator severity-' + severity.toLowerCase()}><Shield size={13} aria-hidden="true"/>
    Severity {severity.charAt(0) + severity.slice(1).toLowerCase()}</span>
}

export function CommandShell({ session, connection, updated, refresh, signOut, signingOut, sessionError, children }: {
  session: Session; connection: string; updated?: string; refresh: () => void; signOut: () => void;
  signingOut: boolean; sessionError: string; children: ReactNode
}) {
  const { route, pathname } = useNavigation()
  const [menu, setMenu] = useState(false)
  const drawer = useRef<HTMLDialogElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const section = route.section
  const page = section === 'not-found' ? { title: 'Page not found', description: '' } : pages[section]
  const title = route.activity ? 'Recent activity' : page.title
  const description = route.activity ? 'Explore projected events across your integrations.' : page.description
  const workspaceTitle = route.delivery ? 'Delivery evidence' : title

  useEffect(() => {
    document.title = `${workspaceTitle} | OpsBridge`
    if (!route.delivery) heading.current?.focus({ preventScroll: true })
  }, [pathname, route.delivery, workspaceTitle])

  useEffect(() => {
    const dialog = drawer.current
    if (menu && dialog && !dialog.open) dialog.showModal()
    if (!menu && dialog?.open) dialog.close()
  }, [menu])

  useEffect(() => {
    const wide = window.matchMedia('(min-width: 768px)')
    const closeOnWide = (event: MediaQueryListEvent) => { if (event.matches) setMenu(false) }
    wide.addEventListener('change', closeOnWide)
    return () => wide.removeEventListener('change', closeOnWide)
  }, [])

  return <div className="command-shell" data-area={section}>
    <a className="command-skip" href="#workspace-content">Skip to content</a>
    <aside className="command-sidebar"><Sidebar section={section} admin={session.role === 'ADMIN'}/></aside>
    <dialog ref={drawer} className="command-drawer" aria-label="Workspace menu" onClose={() => setMenu(false)}>
      <button className="command-menu-close" aria-label="Close navigation" onClick={() => setMenu(false)}><X size={21}/></button>
      <Sidebar section={section} admin={session.role === 'ADMIN'} onFollow={() => {
        drawer.current?.close()
        setMenu(false)
        if (document.activeElement === menuButton.current) heading.current?.focus({ preventScroll: true })
      }}/>
    </dialog>
    <div className="command-workspace">
      <header className="command-topbar">
        <div className="command-context">
          <button ref={menuButton} className="command-menu" type="button" aria-label="Open navigation" aria-expanded={menu} onClick={() => setMenu(true)}><Menu size={21}/></button>
          <span>Integration Operations Command Center</span>
        </div>
        <div className="command-session">
          <span className={'live-status' + (connection === 'Live' ? ' live' : '')} role="status"><Activity size={13} aria-hidden="true"/>{connection}</span>
          <span className="command-identity">{session.username} · {session.role}</span>
          <button className="command-button command-signout" aria-label="Sign out" disabled={signingOut} onClick={signOut}><LogOut size={15} aria-hidden="true"/><span>Sign out</span></button>
        </div>
      </header>
      <main id="workspace-content" className="command-main" tabIndex={-1}>
        {sessionError && <p className="command-session-error" role="alert">{sessionError}</p>}
        <div className={'command-page-header' + (route.delivery ? ' delivery-refresh' : '')}>
          {!route.delivery && <div>{route.activity && <RouteLink className="command-text-link" href="/overview">Overview</RouteLink>}
            <h1 ref={heading} tabIndex={-1}>{title}</h1>{description && <p>{description}</p>}</div>}
          {section !== 'not-found' && section !== 'administration' && section !== 'copilot' && section !== 'monitoring' && <div className="command-refresh">
            <button className="command-button" type="button" onClick={refresh}><RefreshCw size={15} aria-hidden="true"/>Refresh</button>
            {updated && <small>Updated {updated} UTC</small>}
          </div>}
        </div>
        {children}
      </main>
    </div>
  </div>
}

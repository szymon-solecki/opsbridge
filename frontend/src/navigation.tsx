import { createContext, type MouseEvent, type ReactNode, useContext, useEffect, useState } from 'react'

export const sections = ['overview', 'action-center', 'deliveries', 'reconciliation', 'copilot', 'monitoring', 'administration'] as const
export type Section = typeof sections[number]
type Route = { section: Section | 'not-found'; activity?: boolean; delivery?: string; incident?: string; run?: string; exception?: number }
const id = '[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
const uuid = new RegExp('^' + id + '$', 'i')
const deliveryPath = new RegExp(`^/deliveries/(${id})(?:/incidents/(${id}))?$`, 'i')
const runPath = new RegExp(`^/reconciliation/runs/(${id})$`, 'i')

export function routeId(value: string | null) {
  return value && uuid.test(value) ? value.toLowerCase() : ''
}

function readLocation() {
  const pathname = window.location.pathname.replace(/\/$/, '') || '/'
  const query = new URLSearchParams(window.location.search)
  const delivery = pathname.match(deliveryPath)
  const run = pathname.match(runPath)
  const exception = query.get('exception') ?? ''
  const section = sections.find(name => pathname === '/' + name)
  const route: Route = delivery ? { section: 'deliveries', delivery: delivery[1].toLowerCase(), incident: delivery[2]?.toLowerCase() }
    : run ? { section: 'reconciliation', run: run[1].toLowerCase(), exception: /^[1-9][0-9]{0,4}$/.test(exception) && Number(exception) <= 40000 ? Number(exception) : undefined }
    : pathname === '/overview/activity' ? { section: 'overview', activity: true }
    : { section: pathname === '/' ? 'overview' : section ?? 'not-found' }
  return { route, pathname, query }
}

type Navigation = ReturnType<typeof readLocation> & {
  navigate: (href: string, options?: { replace?: boolean; detail?: boolean }) => void
  deliveryOrigin?: string
}
const NavigationContext = createContext<Navigation | null>(null)

export function NavigationProvider({ children }: { children: ReactNode }) {
  const [location, setLocation] = useState(readLocation)
  useEffect(() => {
    const sync = () => setLocation(readLocation())
    window.addEventListener('popstate', sync)
    if (window.location.pathname === '/') window.history.replaceState(null, '', '/overview')
    sync()
    return () => window.removeEventListener('popstate', sync)
  }, [])

  function navigate(href: string, options?: { replace?: boolean; detail?: boolean }) {
    if (href === window.location.pathname + window.location.search) return
    const state = options?.detail ? {
      deliveryOrigin: location.route.delivery
        ? window.history.state?.deliveryOrigin
        : window.location.pathname + window.location.search,
    } : null
    if (options?.replace) window.history.replaceState(state, '', href)
    else window.history.pushState(state, '', href)
    setLocation(readLocation())
  }

  return <NavigationContext.Provider value={{ ...location, navigate,
    deliveryOrigin: window.history.state?.deliveryOrigin }}>{children}</NavigationContext.Provider>
}

export function useNavigation() {
  const navigation = useContext(NavigationContext)
  if (!navigation) throw new Error('Missing workspace navigation')
  return navigation
}

export function RouteLink({ href, children, className, current, detail, onFollow }: {
  href: string; children: ReactNode; className?: string; current?: boolean; detail?: boolean; onFollow?: () => void
}) {
  const { navigate } = useNavigation()
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.altKey || event.ctrlKey || event.shiftKey) return
    event.preventDefault()
    navigate(href, { detail })
    onFollow?.()
  }
  return <a href={href} className={className} aria-current={current ? 'page' : undefined} onClick={follow}>{children}</a>
}

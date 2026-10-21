import { useQuery } from '@tanstack/react-query'
import {
  BookOpenCheck,
  ClipboardCheck,
  History,
  Moon,
  Network,
  ScrollText,
  Server,
  Sparkles,
  Sun,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import { useEffect } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { api, type Health } from '@/api'
import { UstLogo } from '@/components/ust-logo'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from '@/components/ui/sidebar'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useTheme } from '@/app/theme/theme-context'
import { cn } from '@/lib/utils'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
}

// What engineers use every day comes first; how AINOPS works underneath is in the second group.
const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: 'Troubleshoot',
    items: [
      { to: '/', label: 'Investigate', icon: Sparkles, end: true },
      { to: '/inventory', label: 'Inventory', icon: Server },
      { to: '/cases', label: 'Cases', icon: ClipboardCheck },
      { to: '/history', label: 'History', icon: History },
    ],
  },
  {
    label: 'Behind the scenes',
    items: [
      { to: '/graph', label: 'Network map', icon: Network },
      { to: '/skills', label: 'Skills', icon: BookOpenCheck },
      { to: '/tools', label: 'AI tools', icon: Wrench },
      { to: '/audit', label: 'Audit log', icon: ScrollText },
    ],
  },
]
const NAV = NAV_GROUPS.flatMap((group) => group.items)

function isActive(path: string, item: NavItem) {
  if (item.end) return path === '/' || path.startsWith('/investigations')
  return path.startsWith(item.to)
}

function StatusDot({
  ok,
  label,
  detail,
}: {
  ok: boolean | undefined
  label: string
  detail: string
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="flex cursor-default items-center gap-1.5 rounded px-1.5 py-1 text-xs text-muted-foreground">
          <span
            aria-hidden="true"
            className={cn(
              'size-2 rounded-full',
              ok === undefined
                ? 'bg-status-unknown'
                : ok
                  ? 'bg-status-healthy'
                  : 'bg-status-critical',
            )}
          />
          {label}
          <span className="sr-only">: {detail}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>{detail}</TooltipContent>
    </Tooltip>
  )
}

function HealthBar({ health }: { health: Health | undefined }) {
  const up = (ok: boolean | undefined, yes: string) =>
    ok === undefined ? 'checking…' : ok ? yes : 'not reachable'
  return (
    <div className="hidden items-center gap-1 md:flex">
      <StatusDot
        ok={health?.mcp_network.ok}
        label="Network MCP"
        detail={up(health?.mcp_network.ok, `${health?.mcp_network.tools} tools`)}
      />
      <StatusDot
        ok={health?.mcp_topology.ok}
        label="Topology MCP"
        detail={up(health?.mcp_topology.ok, `${health?.mcp_topology.tools} tools`)}
      />
      <StatusDot
        ok={health?.graph.ok}
        label="Graph"
        detail={up(health?.graph.ok, 'Neo4j connected')}
      />
      <StatusDot
        ok={health?.llm_configured}
        label="LLM"
        detail={health ? health.llm_model || 'not configured' : 'checking…'}
      />
    </div>
  )
}

export function Shell() {
  const location = useLocation()
  const { resolved, setChoice } = useTheme()
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15000 })
  // How many cases wait for review, next to "Cases" (shared with the Cases page's lists).
  const cases = useQuery({
    queryKey: ['cases', 'all'],
    queryFn: () => api.cases(),
    refetchInterval: 30000,
  })
  const pending = cases.data?.counts.pending ?? 0
  const current = NAV.find((item) => isActive(location.pathname, item))

  useEffect(() => {
    document.title = current ? `${current.label} · AINOPS` : 'AINOPS'
  }, [current])

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader className="px-3 py-3">
          <div className="flex items-center gap-2.5 overflow-hidden">
            <UstLogo className="h-6 w-auto shrink-0 text-foreground" />
            <div className="leading-tight group-data-[collapsible=icon]:hidden">
              <p className="text-sm font-semibold">AINOPS</p>
              <p className="text-[11px] text-muted-foreground">Agentic network ops</p>
            </div>
          </div>
        </SidebarHeader>
        <SidebarContent>
          {NAV_GROUPS.map((group) => (
            <SidebarGroup key={group.label}>
              <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {group.items.map((item) => (
                    <SidebarMenuItem key={item.to}>
                      <SidebarMenuButton
                        asChild
                        isActive={isActive(location.pathname, item)}
                        tooltip={item.label}
                      >
                        <NavLink to={item.to} end={item.end}>
                          <item.icon aria-hidden="true" />
                          <span>{item.label}</span>
                        </NavLink>
                      </SidebarMenuButton>
                      {item.to === '/cases' && pending > 0 && (
                        <SidebarMenuBadge aria-label={`${pending} waiting for review`}>
                          {pending}
                        </SidebarMenuBadge>
                      )}
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
        </SidebarContent>
        <SidebarFooter className="px-3 py-3 text-[11px] text-muted-foreground group-data-[collapsible=icon]:hidden">
          Read-only. AINOPS never changes a device.
        </SidebarFooter>
      </Sidebar>

      <SidebarInset className="min-w-0">
        <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b bg-background px-4">
          <SidebarTrigger aria-label="Toggle sidebar" />
          <Separator
            orientation="vertical"
            className="mr-1 data-vertical:h-5 data-vertical:self-center"
          />
          <p className="text-sm font-medium">{current?.label ?? 'AINOPS'}</p>
          <div className="ml-auto flex items-center gap-2">
            <HealthBar health={health.data} />
            {health.data &&
              (health.data.lab_simulated ? (
                <span
                  title="The consoles are the simulated copy of the lab on this laptop, not the real devices"
                  className="rounded border border-status-warning-border bg-status-warning-bg px-2 py-0.5 text-[11px] font-semibold tracking-wide text-status-warning uppercase"
                >
                  Lab · simulated devices
                </span>
              ) : (
                <span className="rounded border border-status-healthy-border bg-status-healthy-bg px-2 py-0.5 text-[11px] font-semibold tracking-wide text-status-healthy uppercase">
                  Lab · live devices
                </span>
              ))}
            <Button
              variant="ghost"
              size="icon"
              aria-label={resolved === 'dark' ? 'Use light theme' : 'Use dark theme'}
              onClick={() => setChoice(resolved === 'dark' ? 'light' : 'dark')}
            >
              {resolved === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
            </Button>
          </div>
        </header>
        <main className="relative h-[calc(100svh-3.5rem)] min-h-0 min-w-0 overflow-y-auto">
          <Outlet />
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}

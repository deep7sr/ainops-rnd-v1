import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleCheck, CircleX, ExternalLink, Loader2, RefreshCw, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, type GraphDevice, type GraphLink, type RunEvent, type Topology } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useRunEvents } from '@/hooks/use-run-events'
import { cn } from '@/lib/utils'
import { NetworkMap } from './network-map'

function when(iso: string | undefined | null): string {
  return iso ? new Date(iso).toLocaleString() : 'never'
}

/** After a run that reached no device: say that the graph was kept, not emptied. */
export function NotUpdated({ events }: { events: RunEvent[] }) {
  const done = events.find(
    (e): e is Extract<RunEvent, { type: 'discovery_done' }> => e.type === 'discovery_done',
  )
  if (done?.graph_updated !== false) return null
  return (
    <p
      role="alert"
      className="flex items-start gap-2 rounded-md border border-status-warning-border bg-status-warning-bg px-3 py-2 text-sm"
    >
      <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-status-warning" />
      {done.findings[0] ?? 'No device answered: the knowledge graph was not changed.'}
    </p>
  )
}

function DiscoveryProgress({ events }: { events: RunEvent[] }) {
  const devices = events.find((e) => e.type === 'started' && 'devices' in e) as
    { devices: string[] } | undefined
  const done = new Map(
    events
      .filter((e): e is Extract<RunEvent, { type: 'device_done' }> => e.type === 'device_done')
      .map((e) => [e.device, e]),
  )
  const started = new Set(
    events
      .filter(
        (e): e is Extract<RunEvent, { type: 'device_started' }> => e.type === 'device_started',
      )
      .map((e) => e.device),
  )
  return (
    <ul className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4" aria-label="Discovery progress">
      {(devices?.devices ?? []).map((name) => {
        const result = done.get(name)
        return (
          <li
            key={name}
            className="flex items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm"
          >
            {result ? (
              result.ok ? (
                <CircleCheck aria-hidden="true" className="size-4 text-status-healthy" />
              ) : (
                <CircleX aria-hidden="true" className="size-4 text-status-critical" />
              )
            ) : started.has(name) ? (
              <Loader2
                aria-hidden="true"
                className="size-4 animate-spin text-primary motion-reduce:animate-none"
              />
            ) : (
              <span aria-hidden="true" className="size-4 rounded-full border" />
            )}
            <span className="font-medium">{name}</span>
            <span
              className="ml-auto truncate text-xs text-muted-foreground"
              title={result?.error ?? ''}
            >
              {result
                ? result.ok
                  ? `${result.interfaces} if · ${result.neighbors} nbr`
                  : 'no answer'
                : started.has(name)
                  ? 'asking…'
                  : 'waiting'}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

function DeviceDetail({ device, links }: { device: GraphDevice; links: GraphLink[] }) {
  const mine = links.filter((l) => l.a === device.name || l.b === device.name)
  return (
    <div className="space-y-3">
      <div>
        <p className="font-semibold">{device.name}</p>
        <p className="text-sm text-muted-foreground">{device.description}</p>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <th className="py-1 font-medium">Interface</th>
            <th className="py-1 font-medium">Status</th>
            <th className="py-1 font-medium">IPv4</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {device.interfaces.map((i) => (
            <tr key={i.name}>
              <td className="py-1 font-mono text-xs">{i.name}</td>
              <td
                className={cn(
                  'py-1 text-xs',
                  i.status === 'up' ? 'text-status-healthy' : 'text-status-critical',
                )}
              >
                {i.status}
              </td>
              <td className="py-1 font-mono text-xs">{i.ipv4.join(', ') || '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-muted-foreground">
        {mine.length} link(s):{' '}
        {mine.map((l) => (l.a === device.name ? l.b : l.a)).join(', ') || 'none'}
      </p>
    </div>
  )
}

function LinkDetail({ link }: { link: GraphLink }) {
  return (
    <div className="space-y-2 text-sm">
      <p className="font-semibold">
        {link.a} {link.a_interface} ↔ {link.b} {link.b_interface}
      </p>
      <p>
        Subnet <span className="font-mono">{link.subnet ?? 'none shared'}</span>
      </p>
      <p>
        Status: {link.a} {link.a_status ?? '?'} · {link.b} {link.b_status ?? '?'}
      </p>
      <p className="flex flex-wrap items-center gap-1.5">
        Found by
        {link.sources.map((s) => (
          <Badge key={s} variant="outline" className="uppercase">
            {s}
          </Badge>
        ))}
      </p>
    </div>
  )
}

function GraphView({ topology }: { topology: Topology }) {
  const [selected, setSelected] = useState<string | null>(null)
  const device = topology.devices.find((d) => d.name === selected)
  const link = topology.links.find((l) => l.key === selected)
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="rounded-lg border bg-card p-3">
        <NetworkMap topology={topology} selected={selected} onSelect={setSelected} />
      </div>
      <div className="rounded-lg border bg-card p-4">
        {device ? (
          <DeviceDetail device={device} links={topology.links} />
        ) : link ? (
          <LinkDetail link={link} />
        ) : (
          <p className="text-sm text-muted-foreground">
            Select a device or a link on the map to see what discovery learned about it.
          </p>
        )}
      </div>
    </div>
  )
}

export function TopologyPage() {
  const queryClient = useQueryClient()
  const topology = useQuery({ queryKey: ['topology'], queryFn: api.topology })
  const [runId, setRunId] = useState<string | null>(null)
  const run = useRunEvents(runId)
  const discover = useMutation({
    mutationFn: api.startDiscovery,
    onSuccess: ({ id }) => setRunId(id),
  })

  useEffect(() => {
    if (run.done) void queryClient.invalidateQueries({ queryKey: ['topology'] })
  }, [run.done, queryClient])

  const discovering = runId !== null && !run.done
  const info = topology.data?.discovery
  const interfaces = topology.data?.devices.reduce((n, d) => n + d.interfaces.length, 0) ?? 0

  return (
    <div className="mx-auto max-w-[1400px] space-y-5 px-6 py-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Network map</h1>
          <p className="text-sm text-muted-foreground">
            The knowledge graph of the network, built automatically by discovery (CDP/LLDP
            neighbours and shared subnets), stored in Neo4j. The agent reads it to find the path
            before it checks devices live.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <a href="http://localhost:7474" target="_blank" rel="noreferrer">
              <ExternalLink aria-hidden="true" /> Neo4j Browser
            </a>
          </Button>
          <Button onClick={() => discover.mutate()} disabled={discovering || discover.isPending}>
            {discovering ? (
              <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            ) : (
              <RefreshCw aria-hidden="true" />
            )}
            {discovering ? 'Discovering…' : 'Run discovery'}
          </Button>
        </div>
      </div>

      {discover.isError && (
        <p role="alert" className="text-sm text-status-critical">
          Discovery could not start: {discover.error.message}
        </p>
      )}
      {runId && <DiscoveryProgress events={run.events} />}
      {runId && <NotUpdated events={run.events} />}

      <dl className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {[
          ['Devices', topology.data?.devices.length ?? '-'],
          ['Links', topology.data?.links.length ?? '-'],
          ['Interfaces', interfaces || '-'],
          ['Last discovery', when(info?.at)],
          ['Data', info?.source ?? '-'],
        ].map(([label, value]) => (
          <div key={label} className="rounded-md border bg-card px-4 py-2.5">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="mt-0.5 truncate font-semibold">{value}</dd>
          </div>
        ))}
      </dl>

      {topology.isPending ? (
        <Skeleton className="h-[480px] w-full" />
      ) : topology.isError ? (
        <p role="alert" className="text-sm text-status-critical">
          Could not load the graph: {topology.error.message}. Is Neo4j running?
        </p>
      ) : topology.data.devices.length === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center">
          <p className="font-medium">The graph is empty</p>
          <p className="text-sm text-muted-foreground">Run discovery to build it from the lab.</p>
        </div>
      ) : (
        <GraphView topology={topology.data} />
      )}

      {info && (info.findings.length > 0 || info.devices_failed.length > 0) && (
        <section className="rounded-lg border bg-card p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <TriangleAlert aria-hidden="true" className="size-4 text-status-warning" /> What
            discovery noticed
          </h2>
          <ul className="mt-2 space-y-1 text-sm">
            {info.devices_failed.map((line) => (
              <li key={line} className="text-status-critical">
                Not reached: {line}
              </li>
            ))}
            {info.findings.map((line) => (
              <li key={line} className="text-muted-foreground">
                {line}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

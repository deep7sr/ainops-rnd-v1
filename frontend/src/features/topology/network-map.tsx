// The network as one SVG, drawn from the knowledge graph. During an investigation it also shows
// what the agent is doing, only from real events: the path it found (drawn hop by hop), the device
// it is checking right now and with which tool, the verdict on every device it checked (computed
// by code), the packets of its pings, and the fault it blames. Devices that do not matter fade.
// Colour is never the only signal: states also have icons, labels and line styles.

import { CircleCheck, CircleX, Loader2, TriangleAlert } from 'lucide-react'
import { useSyncExternalStore, type CSSProperties } from 'react'
import type { GraphDevice, GraphLink, Topology } from '@/api'
import { cn } from '@/lib/utils'
import {
  boxIssue,
  NO_HIGHLIGHT,
  type DeviceState,
  type MapHighlight,
  type MapPing,
} from './highlight'
import {
  edgeInterfaces,
  edgePoint,
  layoutDevices,
  linkIsDown,
  NODE_HEIGHT,
  NODE_WIDTH,
  siteOrder,
  SITE_NAMES,
  VIEW_HEIGHT,
  VIEW_WIDTH,
  type Point,
} from './layout'

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)'

function subscribeMotion(onChange: () => void) {
  const query = typeof window.matchMedia === 'function' ? window.matchMedia(REDUCED_MOTION) : null
  query?.addEventListener('change', onChange)
  return () => query?.removeEventListener('change', onChange)
}

/** SVG motion (the ping packets) is not covered by CSS `motion-reduce`, so ask the browser. */
function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeMotion,
    () => typeof window.matchMedia === 'function' && window.matchMedia(REDUCED_MOTION).matches,
    () => false,
  )
}

/** Index of the hop this link is on (0 = first hop of the path), or -1. */
function hopIndex(link: GraphLink, path: string[]): number {
  for (let i = 0; i < path.length - 1; i++) {
    const pair = [path[i], path[i + 1]]
    if (pair.includes(link.a) && pair.includes(link.b)) return i
  }
  return -1
}

function LinkLine({
  link,
  positions,
  highlight,
  investigating,
  selected,
  onSelect,
}: {
  link: GraphLink
  positions: Map<string, Point>
  highlight: MapHighlight
  investigating: boolean
  selected: boolean
  onSelect?: (key: string) => void
}) {
  const a = positions.get(link.a)
  const b = positions.get(link.b)
  if (!a || !b) return null
  const start = edgePoint(a, b)
  const end = edgePoint(b, a)
  const mid = { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 }
  const fault =
    highlight.faultInterfaces.has(`${link.a}:${link.a_interface}`) ||
    highlight.faultInterfaces.has(`${link.b}:${link.b_interface}`)
  const down = linkIsDown(link)
  const hop = hopIndex(link, highlight.path)
  const inPath = hop >= 0
  const faded = investigating && !inPath && !fault
  // Interface names at both ends, only where there is room (short links would cover the subnet).
  const length = Math.hypot(end.x - start.x, end.y - start.y)
  const showEnds = (fault || inPath || selected) && length > 150
  const label = link.subnet ?? 'no shared subnet'
  const at = (t: number) => ({
    x: start.x + (end.x - start.x) * t,
    y: start.y + (end.y - start.y) * t,
  })
  const evidence = highlight.faultEvidence.length ? ` · ${highlight.faultEvidence.join(', ')}` : ''

  return (
    <g
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
      aria-label={`Link ${link.a} ${link.a_interface} to ${link.b} ${link.b_interface}, ${label}${
        fault ? ', blamed by the diagnosis' : down ? ', down' : inPath ? ', on the path' : ''
      }`}
      className={cn(
        'transition-opacity duration-500',
        faded && 'opacity-35',
        onSelect && 'cursor-pointer focus-visible:outline-none',
      )}
      onClick={() => onSelect?.(link.key)}
      onKeyDown={(event) => {
        if (onSelect && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault()
          onSelect(link.key)
        }
      }}
    >
      <line
        x1={start.x}
        y1={start.y}
        x2={end.x}
        y2={end.y}
        strokeWidth={16}
        className="stroke-transparent"
      />
      {inPath && !fault && (
        // The plain line under the drawn one, so the link never disappears while it draws.
        <line
          x1={start.x}
          y1={start.y}
          x2={end.x}
          y2={end.y}
          strokeWidth={2}
          className="stroke-muted-foreground/40"
        />
      )}
      <line
        x1={start.x}
        y1={start.y}
        x2={end.x}
        y2={end.y}
        strokeWidth={fault ? 4 : inPath ? 3.5 : 2}
        strokeDasharray={fault || down ? '9 6' : undefined}
        style={
          inPath && !fault
            ? ({ '--len': `${Math.ceil(length)}`, '--delay': `${hop * 350}ms` } as CSSProperties)
            : undefined
        }
        className={cn(
          'transition-[stroke] duration-300',
          inPath && !fault && !down && 'path-draw',
          fault || down
            ? 'stroke-status-critical'
            : inPath || selected
              ? 'stroke-primary'
              : 'stroke-muted-foreground/40',
        )}
      />
      <g transform={`translate(${mid.x}, ${mid.y})`}>
        <rect
          x={-label.length * 3.4 - 7}
          y={-10}
          width={label.length * 6.8 + 14}
          height={20}
          rx={4}
          className={cn(
            fault || down
              ? 'fill-status-critical-bg stroke-status-critical-border'
              : inPath
                ? 'fill-secondary stroke-primary/40'
                : 'fill-card stroke-border',
          )}
        />
        <text
          textAnchor="middle"
          dominantBaseline="central"
          className={cn(
            'font-mono text-[10.5px]',
            fault || down ? 'fill-status-critical font-semibold' : 'fill-muted-foreground',
          )}
        >
          {label}
        </text>
      </g>
      {showEnds &&
        [
          { p: at(0.16), text: link.a_interface },
          { p: at(0.84), text: link.b_interface },
        ].map(({ p, text }, index) => (
          <text
            key={index}
            x={p.x}
            y={p.y - 8}
            textAnchor="middle"
            className={cn('font-mono text-[10px]', fault ? 'fill-status-critical' : 'fill-primary')}
          >
            {text}
          </text>
        ))}
      {fault && (
        <text
          x={mid.x}
          y={mid.y + 25}
          textAnchor="middle"
          className="fill-status-critical text-[11px] font-semibold"
        >
          Root cause{evidence}
        </text>
      )}
    </g>
  )
}

interface PingNote {
  device: string
  text: string
  ok: boolean
}

const STATE_LABEL: Record<DeviceState, string> = {
  checking: 'being checked now',
  ok: 'checked, healthy',
  problem: 'checked, problem found',
  unreachable: 'did not answer',
  checked: 'checked',
}

function DeviceBox({
  device,
  at,
  highlight,
  investigating,
  note,
  selected,
  onSelect,
}: {
  device: GraphDevice
  at: Point
  highlight: MapHighlight
  investigating: boolean
  note: PingNote | null
  selected: boolean
  onSelect?: (name: string) => void
}) {
  const state = highlight.states.get(device.name)
  const issues = highlight.issues.get(device.name) ?? []
  const fault = highlight.faultDevices.has(device.name)
  const checking = state === 'checking'
  const inPath = highlight.path.includes(device.name)
  const faded = investigating && !inPath && !state && !fault
  const caption = highlight.caption?.device === device.name ? highlight.caption.label : null
  const detail = checking
    ? `${caption ?? 'checking'}…`
    : issues.length
      ? boxIssue(issues[0])
      : note
        ? note.text
        : state === 'unreachable'
          ? 'did not answer'
          : `${device.role.replace('-', ' ')} · ${device.platform === 'juniper_junos' ? 'Junos' : 'IOS'}`
  const spoken = fault ? 'root cause' : state ? STATE_LABEL[state] : inPath ? 'on the path' : ''
  const extra = note && !checking && !issues.length ? [note.text] : []

  return (
    <g
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
      aria-label={[device.name, device.role, spoken, ...issues, ...extra]
        .filter(Boolean)
        .join(', ')}
      className={cn(
        'transition-opacity duration-500',
        faded && 'opacity-35',
        onSelect && 'cursor-pointer focus-visible:outline-none',
      )}
      onClick={() => onSelect?.(device.name)}
      onKeyDown={(event) => {
        if (onSelect && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault()
          onSelect(device.name)
        }
      }}
      transform={`translate(${at.x - NODE_WIDTH / 2}, ${at.y - NODE_HEIGHT / 2})`}
    >
      <title>{[device.name, spoken, ...issues].filter(Boolean).join(' · ')}</title>
      {checking && (
        // A real state (a command is running on this device), so it may move; still when reduced
        // motion is asked for.
        <rect
          x={-6}
          y={-6}
          width={NODE_WIDTH + 12}
          height={NODE_HEIGHT + 12}
          rx={10}
          className="animate-pulse fill-none stroke-primary stroke-2 motion-reduce:animate-none"
        />
      )}
      <rect
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={6}
        strokeWidth={fault || checking || selected ? 2.5 : inPath || state ? 2 : 1.25}
        className={cn(
          'transition-[fill,stroke] duration-300',
          fault
            ? 'fill-status-critical-bg stroke-status-critical'
            : checking
              ? 'fill-secondary stroke-primary'
              : state === 'problem'
                ? 'fill-status-warning-bg stroke-status-warning-border'
                : state === 'ok'
                  ? 'fill-status-healthy-bg stroke-status-healthy-border'
                  : state === 'unreachable'
                    ? 'fill-status-unknown-bg stroke-status-unknown-border'
                    : inPath || selected || state === 'checked'
                      ? 'fill-card stroke-primary'
                      : 'fill-card stroke-border',
        )}
      />
      <foreignObject x={NODE_WIDTH - 24} y={7} width={17} height={17}>
        {fault ? (
          <TriangleAlert aria-hidden="true" className="size-4 text-status-critical" />
        ) : checking ? (
          <Loader2
            aria-hidden="true"
            className="size-4 animate-spin text-primary motion-reduce:animate-none"
          />
        ) : state === 'problem' ? (
          <TriangleAlert aria-hidden="true" className="size-4 text-status-warning" />
        ) : state === 'ok' ? (
          <CircleCheck aria-hidden="true" className="size-4 text-status-healthy" />
        ) : state === 'unreachable' ? (
          <CircleX aria-hidden="true" className="size-4 text-status-unknown" />
        ) : state === 'checked' ? (
          <CircleCheck aria-hidden="true" className="size-4 text-muted-foreground" />
        ) : null}
      </foreignObject>
      <text x={11} y={23} className="fill-foreground text-[13px] font-semibold">
        {device.name}
      </text>
      <foreignObject x={11} y={31} width={NODE_WIDTH - 20} height={18}>
        <div
          className={cn(
            'truncate text-[11px] leading-[18px]',
            fault
              ? 'font-semibold text-status-critical'
              : checking
                ? 'font-medium text-primary'
                : issues.length
                  ? 'font-semibold text-status-warning'
                  : note
                    ? cn('font-semibold', note.ok ? 'text-status-healthy' : 'text-status-critical')
                    : 'text-muted-foreground',
          )}
        >
          {detail}
        </div>
      </foreignObject>
    </g>
  )
}

/** A packet travelling the ping's route while it runs (its result is then shown in a box). */
function PingPacket({
  ping,
  positions,
  reducedMotion,
}: {
  ping: MapPing
  positions: Map<string, Point>
  reducedMotion: boolean
}) {
  const points = ping.route.map((name) => positions.get(name)).filter((p): p is Point => !!p)
  if (points.length === 0) return null
  const route = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')

  if (ping.ok === null) {
    if (points.length < 2) return null // the way is unknown: the device caption says "pinging"
    const middle = points[Math.floor(points.length / 2)]
    return (
      <g aria-label={`Ping to ${ping.destination} in flight`}>
        {reducedMotion ? (
          <circle cx={middle.x} cy={middle.y} r={6} className="fill-primary" />
        ) : (
          <circle r={6} className="fill-primary stroke-card stroke-2">
            <animateMotion
              dur={`${Math.max(points.length - 1, 1) * 0.9}s`}
              repeatCount="indefinite"
              path={route}
            />
          </circle>
        )}
      </g>
    )
  }
  return null
}

export function NetworkMap({
  topology,
  highlight = NO_HIGHLIGHT,
  selected = null,
  onSelect,
  showEdges = true,
  className,
}: {
  topology: Topology
  highlight?: MapHighlight
  selected?: string | null
  onSelect?: (key: string) => void
  showEdges?: boolean
  className?: string
}) {
  const reducedMotion = usePrefersReducedMotion()
  const positions = layoutDevices(topology.devices)
  const sites = siteOrder(topology.devices)
  const columnWidth = VIEW_WIDTH / Math.max(sites.length, 1)
  const edges = showEdges ? edgeInterfaces(topology.devices, topology.links) : []
  // Once the agent has found its path, what is not on it fades (it cannot matter).
  const investigating = highlight.path.length > 0
  // Without the edge labels, zoom to the devices so the map is readable in a narrow panel.
  const xs = [...positions.values()].map((p) => p.x)
  const zoom = !showEdges && xs.length > 0
  const viewLeft = zoom ? Math.max(0, Math.min(...xs) - NODE_WIDTH / 2 - 40) : 0
  const viewRight = zoom ? Math.min(VIEW_WIDTH, Math.max(...xs) + NODE_WIDTH / 2 + 40) : VIEW_WIDTH
  const viewBox = `${viewLeft} 0 ${viewRight - viewLeft} ${VIEW_HEIGHT}`
  // The latest answered ping is written in a device box: in the target's box when it replied, in
  // the sender's box when it did not (a ping alone does not tell where the packet was lost).
  const answered = highlight.pings.filter((p) => p.ok !== null).at(-1)
  const note: PingNote | null = answered
    ? {
        device: answered.ok ? answered.route[answered.route.length - 1] : answered.from,
        text: answered.ok
          ? `✓ ${answered.destination} replied`
          : `✕ no reply from ${answered.destination}`,
        ok: answered.ok === true,
      }
    : null

  return (
    <svg
      viewBox={viewBox}
      role="group"
      aria-label="Network map"
      className={cn('h-auto w-full select-none', className)}
    >
      {sites.map((site, index) => (
        <g key={site}>
          <rect
            x={columnWidth * index + 12}
            y={12}
            width={columnWidth - 24}
            height={VIEW_HEIGHT - 24}
            rx={8}
            className="fill-muted/50 stroke-border"
            strokeDasharray="4 4"
          />
          <text
            x={Math.max(columnWidth * index + 28, viewLeft + 16)}
            y={40}
            className="fill-eyebrow text-[11px] font-semibold tracking-[0.12em]"
          >
            {site} · {(SITE_NAMES[site] ?? site).toUpperCase()}
          </text>
        </g>
      ))}

      {edges.map((edge, index) => {
        const at = positions.get(edge.device)
        if (!at) return null
        const leftSide = at.x < VIEW_WIDTH / 2
        const siblings = edges.filter((e) => e.device === edge.device)
        const offset = (siblings.indexOf(edge) - (siblings.length - 1) / 2) * 22
        const x0 = at.x + (leftSide ? -NODE_WIDTH / 2 : NODE_WIDTH / 2)
        const x1 = x0 + (leftSide ? -26 : 26)
        const y = at.y + offset
        const label = `${edge.name} ${edge.ipv4[0]}`
        const width = label.length * 5.7 + 12
        return (
          <g
            key={`${edge.device}:${edge.name}:${index}`}
            aria-label={`${edge.device} ${label}, no known peer`}
          >
            <line
              x1={x0}
              y1={y}
              x2={x1}
              y2={y}
              strokeDasharray="3 3"
              className="stroke-muted-foreground/50"
            />
            <rect
              x={leftSide ? x1 - width : x1}
              y={y - 9}
              width={width}
              height={18}
              rx={3}
              className="fill-background stroke-border"
            />
            <text
              x={leftSide ? x1 - width / 2 : x1 + width / 2}
              y={y}
              textAnchor="middle"
              dominantBaseline="central"
              className="fill-muted-foreground font-mono text-[9px]"
            >
              {label}
            </text>
          </g>
        )
      })}

      {topology.links.map((link) => (
        <LinkLine
          key={link.key}
          link={link}
          positions={positions}
          highlight={highlight}
          investigating={investigating}
          selected={selected === link.key}
          onSelect={onSelect}
        />
      ))}
      {topology.devices.map((device) => {
        const at = positions.get(device.name)
        return at ? (
          <DeviceBox
            key={device.name}
            device={device}
            at={at}
            highlight={highlight}
            investigating={investigating}
            note={note?.device === device.name ? note : null}
            selected={selected === device.name}
            onSelect={onSelect}
          />
        ) : null
      })}
      {highlight.pings.map((ping) => (
        <PingPacket
          key={ping.key}
          ping={ping}
          positions={positions}
          reducedMotion={reducedMotion}
        />
      ))}
    </svg>
  )
}

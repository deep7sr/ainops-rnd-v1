// The network as one SVG, drawn from the knowledge graph. During an investigation it also shows
// what the agent is doing, only from real events: the path it found (drawn hop by hop), the device
// it is checking right now and with which tool, the verdict on every device it checked (computed
// by code), the packets of its pings, and the fault it blames. Devices that do not matter fade.
// Colour is never the only signal: states also have icons, labels and line styles.

import { CircleCheck, CircleX, Loader2, TriangleAlert } from 'lucide-react'
import { motion } from 'motion/react'
import { useId, type CSSProperties } from 'react'
import type { GraphDevice, GraphLink, Topology } from '@/api'
import { DeviceGlyph } from '@/components/device-glyph'
import { usePrefersReducedMotion } from '@/hooks/use-reduced-motion'
import { cn } from '@/lib/utils'
import { AgentBeneath, AgentConsoleStrip, AgentLayer } from './agent-layer'
import {
  boxIssue,
  NO_HIGHLIGHT,
  type AgentWalk,
  type DeviceState,
  type MapHighlight,
  type MapPing,
} from './highlight'
import {
  edgeInterfaces,
  edgePoint,
  frameView,
  layoutDevices,
  linkIsDown,
  labelAt,
  layoutLans,
  NODE_WIDTH,
  siteOrder,
  SITE_NAMES,
  TILE,
  VIEW_HEIGHT,
  VIEW_WIDTH,
  type Point,
} from './layout'
import type { EndpointTag, LanEndpoint } from './lan'

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
  const along = labelAt(start, end)
  const mid = { x: start.x + (end.x - start.x) * along, y: start.y + (end.y - start.y) * along }
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
  // The way traffic goes on this hop: from path[hop] to path[hop + 1].
  const forward = inPath && highlight.path[hop] === link.a
  const [from, to] = forward ? [start, end] : [end, start]
  const flowing = inPath && !fault && !down
  // The hop number sits just left of the subnet label (any link is long enough for that).
  // On a vertical link the label goes beside it, clear of the names under the tiles (the line
  // passes under them).
  const vertical = Math.abs(end.x - start.x) < 20
  const pillAt = vertical
    ? { x: mid.x + 56 + label.length * 3.4 + 7, y: (start.y + end.y) / 2 }
    : mid
  const hopAt = { x: pillAt.x - label.length * 3.4 - 7 - 12, y: pillAt.y }

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
      {flowing && (
        // Once the hop is drawn, dashes flow along it the way the traffic goes.
        <line
          x1={from.x}
          y1={from.y}
          x2={to.x}
          y2={to.y}
          strokeWidth={1.5}
          style={{ '--delay': `${hop * 350 + 600}ms` } as CSSProperties}
          className="flow-dash stroke-card/90"
        />
      )}
      {flowing && (
        // Which hop of the path this is, counted from the source.
        <g aria-hidden="true" transform={`translate(${hopAt.x}, ${hopAt.y})`}>
          <circle r={8} className="fill-primary stroke-card" strokeWidth={1.5} />
          <text
            textAnchor="middle"
            dominantBaseline="central"
            className="fill-primary-foreground font-mono text-[9.5px] font-semibold"
          >
            {hop + 1}
          </text>
        </g>
      )}
      <g transform={`translate(${pillAt.x}, ${pillAt.y})`}>
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
        // Where the link breaks: a pulsing mark at the blamed end (both ends if both are blamed).
        <g aria-hidden="true">
          {[
            { p: at(0.16), blamed: highlight.faultInterfaces.has(`${link.a}:${link.a_interface}`) },
            { p: at(0.84), blamed: highlight.faultInterfaces.has(`${link.b}:${link.b_interface}`) },
          ]
            .filter(({ blamed }) => blamed)
            .map(({ p }, index) => (
              <g key={index} transform={`translate(${p.x}, ${p.y})`}>
                <circle
                  r={9}
                  className="origin-center animate-ping fill-status-critical/40 [animation-duration:1.4s] [transform-box:fill-box] motion-reduce:hidden"
                />
                <circle r={8} className="fill-status-critical stroke-card" strokeWidth={1.5} />
                <path
                  d="M-3.5 -3.5l7 7M3.5 -3.5l-7 7"
                  className="stroke-white"
                  strokeWidth={2}
                  strokeLinecap="round"
                />
              </g>
            ))}
        </g>
      )}
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

/** The rounded square with the device's picture: its colour says what the checks found. */
function tileTone({
  fault,
  checking,
  state,
  lit,
}: {
  fault: boolean
  checking: boolean
  state: DeviceState | undefined
  lit: boolean
}) {
  return fault
    ? 'fill-status-critical-bg stroke-status-critical'
    : checking
      ? 'fill-secondary stroke-primary'
      : state === 'problem'
        ? 'fill-status-warning-bg stroke-status-warning'
        : state === 'ok'
          ? 'fill-status-healthy-bg stroke-status-healthy-border'
          : state === 'unreachable'
            ? 'fill-status-unknown-bg stroke-status-unknown-border'
            : lit
              ? 'fill-card stroke-primary'
              : 'fill-card stroke-border'
}

/** The state badge on a tile's top right corner. */
function StateBadge({ fault, state }: { fault: boolean; state: DeviceState | undefined }) {
  const icon = fault ? (
    <TriangleAlert aria-hidden="true" className="size-3.5 text-status-critical" />
  ) : state === 'checking' ? (
    <Loader2
      aria-hidden="true"
      className="size-3.5 animate-spin text-primary motion-reduce:animate-none"
    />
  ) : state === 'problem' ? (
    <TriangleAlert aria-hidden="true" className="size-3.5 text-status-warning" />
  ) : state === 'ok' ? (
    <CircleCheck aria-hidden="true" className="size-3.5 text-status-healthy" />
  ) : state === 'unreachable' ? (
    <CircleX aria-hidden="true" className="size-3.5 text-status-unknown" />
  ) : state === 'checked' ? (
    <CircleCheck aria-hidden="true" className="size-3.5 text-muted-foreground" />
  ) : null
  if (!icon) return null
  return (
    <g transform={`translate(${TILE / 2 - 3}, ${-TILE / 2 + 3})`}>
      <circle r={10} className="fill-card stroke-border" />
      <foreignObject x={-7} y={-7} width={14} height={14}>
        {icon}
      </foreignObject>
    </g>
  )
}

function DeviceTile({
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
      transform={`translate(${at.x}, ${at.y})`}
    >
      <title>{[device.name, spoken, ...issues].filter(Boolean).join(' · ')}</title>
      <rect
        x={-TILE / 2}
        y={-TILE / 2}
        width={TILE}
        height={TILE}
        rx={14}
        strokeWidth={fault || checking || selected ? 2.5 : inPath || state ? 2 : 1.5}
        className={cn(
          'drop-shadow-[0_2px_4px_rgb(16_40_44/0.10)] transition-[fill,stroke] duration-300',
          tileTone({ fault, checking, state, lit: inPath || selected || state === 'checked' }),
        )}
      />
      <DeviceGlyph
        deviceRole={device.role}
        x={-19}
        y={-22}
        size={38}
        className={cn(
          'transition-colors duration-300',
          fault
            ? 'text-status-critical'
            : state === 'problem'
              ? 'text-status-warning'
              : state === 'ok'
                ? 'text-status-healthy'
                : checking || inPath || selected || state
                  ? 'text-primary'
                  : 'text-muted-foreground',
        )}
      />
      <StateBadge fault={fault} state={state} />
      <text
        y={TILE / 2 + 16}
        textAnchor="middle"
        className="fill-foreground text-halo text-[12.5px] font-semibold"
      >
        {device.name}
      </text>
      <foreignObject x={-NODE_WIDTH / 2} y={TILE / 2 + 20} width={NODE_WIDTH} height={18}>
        <div
          className={cn(
            'truncate text-halo text-center text-[11px] leading-[18px]',
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

const TAG_TEXT: Record<EndpointTag, string> = {
  source: 'SOURCE',
  destination: 'DESTINATION',
  question: 'IN YOUR QUESTION',
}

/** A user LAN at the edge of the map, and its link to its core switch. */
function LanEnd({
  lan,
  at,
  device,
  tag,
  investigating,
}: {
  lan: LanEndpoint
  at: Point
  device: Point
  tag: EndpointTag | undefined
  investigating: boolean
}) {
  const start = edgePoint(device, at)
  const end = edgePoint(at, device)
  const end_ = tag === 'source' || tag === 'destination'
  const faded = investigating && !tag
  const tagText = tag ? TAG_TEXT[tag] : ''
  const tagWidth = tagText.length * 6.4 + 14
  return (
    <g
      aria-label={[lan.name, lan.subnet, tag ? tagText.toLowerCase() : '']
        .filter(Boolean)
        .join(', ')}
      className={cn('transition-opacity duration-500', faded && 'opacity-35')}
    >
      <line
        x1={start.x}
        y1={start.y}
        x2={end.x}
        y2={end.y}
        strokeWidth={end_ ? 3 : 2}
        className={end_ ? 'stroke-primary' : 'stroke-muted-foreground/40'}
      />
      {end_ && (
        <line
          x1={tag === 'source' ? end.x : start.x}
          y1={end.y}
          x2={tag === 'source' ? start.x : end.x}
          y2={end.y}
          strokeWidth={1.5}
          className="flow-dash stroke-card/90"
        />
      )}
      <text
        x={start.x + (end.x - start.x) * 0.2}
        y={start.y - 8}
        textAnchor="middle"
        className={cn('font-mono text-[10px]', end_ ? 'fill-primary' : 'fill-muted-foreground')}
      >
        {lan.interface}
      </text>
      <g transform={`translate(${at.x}, ${at.y})`}>
        <rect
          x={-TILE / 2 + 4}
          y={-TILE / 2 + 4}
          width={TILE - 8}
          height={TILE - 8}
          rx={12}
          strokeWidth={end_ ? 2 : 1.5}
          className={cn(
            'drop-shadow-[0_2px_4px_rgb(16_40_44/0.10)]',
            tag ? 'fill-card stroke-primary' : 'fill-card stroke-border',
          )}
        />
        <DeviceGlyph
          deviceRole="lan"
          x={-17}
          y={-17}
          size={34}
          className={tag ? 'text-primary' : 'text-muted-foreground'}
        />
        <text
          y={TILE / 2 + 16}
          textAnchor="middle"
          className="fill-foreground text-halo text-[12.5px] font-semibold"
        >
          {lan.name}
        </text>
        <text
          y={TILE / 2 + 31}
          textAnchor="middle"
          className="fill-muted-foreground text-halo font-mono text-[10.5px]"
        >
          {lan.subnet}
        </text>
        {tag && (
          <g transform={`translate(0, ${-TILE / 2 - 14})`}>
            <rect
              x={-tagWidth / 2}
              y={-9}
              width={tagWidth}
              height={18}
              rx={9}
              className={end_ ? 'fill-primary' : 'fill-secondary stroke-primary/40'}
            />
            <text
              textAnchor="middle"
              dominantBaseline="central"
              className={cn(
                'text-[9.5px] font-bold tracking-wider',
                end_ ? 'fill-primary-foreground' : 'fill-secondary-foreground',
              )}
            >
              {tagText}
            </text>
          </g>
        )}
      </g>
    </g>
  )
}

/**
 * A packet travelling the ping's route while it runs (its result is then shown in a box). When the
 * answer has just come in (`fresh`), the packet plays it once: out and back for a reply; out and
 * fading away for no reply (a ping does not say where the packet was lost).
 */
function PingPacket({
  ping,
  positions,
  reducedMotion,
  fresh,
}: {
  ping: MapPing
  positions: Map<string, Point>
  reducedMotion: boolean
  fresh: boolean
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
  if (!fresh || reducedMotion || points.length < 2) return null
  const there = ping.ok ? [...points, ...points.slice(0, -1).reverse()] : points
  return (
    <motion.circle
      aria-hidden="true"
      r={6}
      initial={{ cx: points[0].x, cy: points[0].y, opacity: 1 }}
      animate={{
        cx: there.map((p) => p.x),
        cy: there.map((p) => p.y),
        opacity: ping.ok
          ? [...there.slice(1).map(() => 1), 0]
          : there.map((_, i, all) => 1 - i / all.length),
      }}
      transition={{ duration: 0.45 * there.length, ease: 'linear' }}
      className={
        ping.ok
          ? 'fill-status-healthy stroke-card stroke-2'
          : 'fill-status-critical stroke-card stroke-2'
      }
    />
  )
}

export function NetworkMap({
  topology,
  highlight = NO_HIGHLIGHT,
  selected = null,
  focus = null,
  onSelect,
  showEdges = true,
  agent = null,
  lans = null,
  className,
}: {
  topology: Topology
  /** The user LANs to draw at the edges (the investigation map), and which end of the question
   *  each one is. */
  lans?: { endpoints: LanEndpoint[]; tags: Map<string, EndpointTag> } | null
  highlight?: MapHighlight
  /** The agent during a live investigation: its marker, trail and console. */
  agent?: AgentWalk | null
  selected?: string | null
  /** Devices to zoom to (the root cause); null or empty: the whole map. */
  focus?: string[] | null
  onSelect?: (key: string) => void
  showEdges?: boolean
  className?: string
}) {
  const reducedMotion = usePrefersReducedMotion()
  // Gradient ids for this map, made of plain characters (they go into url(#...)).
  const id = `map${useId().replace(/[^A-Za-z0-9]/g, '')}`
  const ids = { orb: `${id}-orb`, sweep: `${id}-sweep` }
  const positions = layoutDevices(topology.devices)
  const lanAt = lans ? layoutLans(lans.endpoints, topology.devices, positions) : new Map()
  const sites = siteOrder(topology.devices)
  const columnWidth = VIEW_WIDTH / Math.max(sites.length, 1)
  const edges = showEdges ? edgeInterfaces(topology.devices, topology.links) : []
  // Once the agent has found its path, what is not on it fades (it cannot matter).
  const investigating = highlight.path.length > 0
  // Without the edge labels, zoom to the devices so the map is readable in a narrow panel.
  const xs = [...positions.values(), ...lanAt.values()].map((p) => p.x)
  const zoom = !showEdges && xs.length > 0
  const viewLeft = zoom ? Math.max(0, Math.min(...xs) - NODE_WIDTH / 2 - 40) : 0
  const viewRight = zoom ? Math.min(VIEW_WIDTH, Math.max(...xs) + NODE_WIDTH / 2 + 40) : VIEW_WIDTH
  const view = frameView(
    { x: viewLeft, y: 0, width: viewRight - viewLeft, height: VIEW_HEIGHT },
    (focus ?? []).map((name) => positions.get(name)).filter((p): p is Point => !!p),
  )
  const viewBox = `${view.x} ${view.y} ${view.width} ${view.height}`
  // The latest answered ping is written in a device box: in the target's box when it replied, in
  // the sender's box when it did not (a ping alone does not tell where the packet was lost).
  const answered = highlight.pings.filter((p) => p.ok !== null).at(-1)
  // Only the latest answer plays, and only while the investigation runs (not when it is reopened).
  const freshPing = agent && agent.mode !== 'resting' ? answered?.key : undefined
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
    <div className="relative">
      <motion.svg
        initial={false}
        animate={{ viewBox }}
        transition={{ duration: reducedMotion ? 0 : 0.9, ease: [0.65, 0, 0.35, 1] }}
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
          const x0 = at.x + (leftSide ? -TILE / 2 - 6 : TILE / 2 + 6)
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

        {lans?.endpoints.map((lan) => {
          const at = lanAt.get(lan.key)
          const device = positions.get(lan.device)
          return at && device ? (
            <LanEnd
              key={lan.key}
              lan={lan}
              at={at}
              device={device}
              tag={lans.tags.get(lan.key)}
              investigating={investigating}
            />
          ) : null
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
        {agent && <AgentBeneath walk={agent} positions={positions} ids={ids} />}
        {topology.devices.map((device) => {
          const at = positions.get(device.name)
          return at ? (
            <DeviceTile
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
            fresh={ping.key === freshPing}
          />
        ))}
        {agent && (
          <AgentLayer walk={agent} positions={positions} links={topology.links} ids={ids} />
        )}
      </motion.svg>
      {agent && agent.mode !== 'resting' && (
        <AgentConsoleStrip console={agent.console} instant={reducedMotion} />
      )}
    </div>
  )
}

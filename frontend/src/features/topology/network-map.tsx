// The network as one SVG, drawn from the knowledge graph. During an investigation it also shows
// what the agent is doing: the path it found, the device it is checking right now, the devices it
// has checked, and the fault it blames. Colour is never the only signal: states also have icons,
// labels and line styles.

import { CircleCheck, Loader2, TriangleAlert } from 'lucide-react'
import type { GraphDevice, GraphLink, Topology } from '@/api'
import { cn } from '@/lib/utils'
import { NO_HIGHLIGHT, type MapHighlight } from './highlight'
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

function onPath(link: GraphLink, path: string[]): boolean {
  for (let i = 0; i < path.length - 1; i++) {
    const pair = [path[i], path[i + 1]]
    if (pair.includes(link.a) && pair.includes(link.b)) return true
  }
  return false
}

function LinkLine({
  link,
  positions,
  highlight,
  selected,
  onSelect,
}: {
  link: GraphLink
  positions: Map<string, Point>
  highlight: MapHighlight
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
  const inPath = onPath(link, highlight.path)
  // Interface names at both ends, only where there is room (short links would cover the subnet).
  const length = Math.hypot(end.x - start.x, end.y - start.y)
  const showEnds = (fault || inPath || selected) && length > 150
  const label = link.subnet ?? 'no shared subnet'
  const at = (t: number) => ({
    x: start.x + (end.x - start.x) * t,
    y: start.y + (end.y - start.y) * t,
  })

  return (
    <g
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
      aria-label={`Link ${link.a} ${link.a_interface} to ${link.b} ${link.b_interface}, ${label}${
        fault ? ', blamed by the diagnosis' : down ? ', down' : ''
      }`}
      className={cn(onSelect && 'cursor-pointer focus-visible:outline-none')}
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
      <line
        x1={start.x}
        y1={start.y}
        x2={end.x}
        y2={end.y}
        strokeWidth={fault ? 4 : inPath ? 3.5 : 2}
        strokeDasharray={fault || down ? '9 6' : undefined}
        className={cn(
          'transition-[stroke] duration-300',
          fault || down
            ? 'stroke-status-critical'
            : inPath
              ? 'stroke-primary'
              : selected
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
          y={mid.y + 24}
          textAnchor="middle"
          className="fill-status-critical text-[11px] font-semibold"
        >
          Root cause
        </text>
      )}
    </g>
  )
}

function DeviceBox({
  device,
  at,
  highlight,
  selected,
  onSelect,
}: {
  device: GraphDevice
  at: Point
  highlight: MapHighlight
  selected: boolean
  onSelect?: (name: string) => void
}) {
  const active = highlight.active.has(device.name)
  const checked = highlight.checked.get(device.name)
  const fault = highlight.faultDevices.has(device.name)
  const inPath = highlight.path.includes(device.name)
  const state = fault ? 'fault' : active ? 'checking' : checked ? `checked (${checked})` : 'idle'

  return (
    <g
      role={onSelect ? 'button' : undefined}
      tabIndex={onSelect ? 0 : undefined}
      aria-label={`${device.name}, ${device.role}, ${state}`}
      className={cn(onSelect && 'cursor-pointer focus-visible:outline-none')}
      onClick={() => onSelect?.(device.name)}
      onKeyDown={(event) => {
        if (onSelect && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault()
          onSelect(device.name)
        }
      }}
      transform={`translate(${at.x - NODE_WIDTH / 2}, ${at.y - NODE_HEIGHT / 2})`}
    >
      {active && (
        // A real state (a command is running on this device), so it may move; still when reduced
        // motion is asked for.
        <rect
          x={-5}
          y={-5}
          width={NODE_WIDTH + 10}
          height={NODE_HEIGHT + 10}
          rx={9}
          className="animate-pulse fill-none stroke-primary stroke-2 motion-reduce:animate-none"
        />
      )}
      <rect
        width={NODE_WIDTH}
        height={NODE_HEIGHT}
        rx={6}
        strokeWidth={fault || active || selected ? 2.5 : inPath ? 2 : 1.25}
        className={cn(
          'transition-[fill,stroke] duration-300',
          fault
            ? 'fill-status-critical-bg stroke-status-critical'
            : active
              ? 'fill-secondary stroke-primary'
              : checked === 'ok'
                ? 'fill-status-healthy-bg stroke-status-healthy-border'
                : checked === 'error'
                  ? 'fill-status-warning-bg stroke-status-warning-border'
                  : inPath || selected
                    ? 'fill-card stroke-primary'
                    : 'fill-card stroke-border',
        )}
      />
      <foreignObject x={NODE_WIDTH - 24} y={7} width={17} height={17}>
        {fault ? (
          <TriangleAlert aria-hidden="true" className="size-4 text-status-critical" />
        ) : active ? (
          <Loader2
            aria-hidden="true"
            className="size-4 animate-spin text-primary motion-reduce:animate-none"
          />
        ) : checked === 'ok' ? (
          <CircleCheck aria-hidden="true" className="size-4 text-status-healthy" />
        ) : checked === 'error' ? (
          <TriangleAlert aria-hidden="true" className="size-4 text-status-warning" />
        ) : null}
      </foreignObject>
      <text x={11} y={23} className="fill-foreground text-[13px] font-semibold">
        {device.name}
      </text>
      <text x={11} y={41} className="fill-muted-foreground text-[11px]">
        {device.role.replace('-', ' ')} · {device.platform === 'juniper_junos' ? 'Junos' : 'IOS'}
      </text>
    </g>
  )
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
  const positions = layoutDevices(topology.devices)
  const sites = siteOrder(topology.devices)
  const columnWidth = VIEW_WIDTH / Math.max(sites.length, 1)
  const edges = showEdges ? edgeInterfaces(topology.devices, topology.links) : []
  // Without the edge labels, zoom to the devices so the map is readable in a narrow panel.
  const xs = [...positions.values()].map((p) => p.x)
  const zoom = !showEdges && xs.length > 0
  const viewLeft = zoom ? Math.max(0, Math.min(...xs) - NODE_WIDTH / 2 - 40) : 0
  const viewRight = zoom ? Math.min(VIEW_WIDTH, Math.max(...xs) + NODE_WIDTH / 2 + 40) : VIEW_WIDTH
  const viewBox = `${viewLeft} 0 ${viewRight - viewLeft} ${VIEW_HEIGHT}`

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
            selected={selected === device.name}
            onSelect={onSelect}
          />
        ) : null
      })}
    </svg>
  )
}

// The agent on the live map: a marker that travels along the links to each device the agent runs
// a command on, the numbered trail of where it went, a light running round the device while a
// command runs, and a console under the map with the command and the first lines the device
// answered. All of it shows real steps only, and the timeline says the same in words (so this
// layer is aria-hidden).

import { CircleCheck, CircleSlash, CircleX, SquareTerminal, TriangleAlert } from 'lucide-react'
import { motion } from 'motion/react'
import { useEffect, useState, type CSSProperties } from 'react'
import type { GraphLink } from '@/api'
import { DURATION, EASE_IN_OUT, EASE_OUT } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { AgentConsole, AgentWalk } from './highlight'
import { TILE, VIEW_HEIGHT, VIEW_WIDTH, type Point } from './layout'
import { routeBetween } from './route'

/** Where the marker sits on a device: just above the middle of its tile's top edge. */
const anchor = (p: Point): Point => ({ x: p.x, y: p.y - TILE / 2 - 4 })

function pathThrough(names: string[], positions: Map<string, Point>): Point[] {
  return names.map((n) => positions.get(n)).filter((p): p is Point => !!p)
}

/** The way the agent walked: from each device to the next along the links. */
function TrailLine({ walk, positions, links }: AgentProps) {
  const points: Point[] = []
  walk.trail.forEach((device, i) => {
    const leg = i === 0 ? [device] : routeBetween(walk.trail[i - 1], device, links).slice(1)
    points.push(...pathThrough(leg, positions).map(anchor))
  })
  if (points.length < 2) return null
  return (
    <polyline
      points={points.map((p) => `${p.x},${p.y}`).join(' ')}
      className="fill-none stroke-provenance-ai/45"
      strokeWidth={2}
      strokeDasharray="2 5"
      strokeLinecap="round"
    />
  )
}

/** On each device the agent went to: when, as numbers in the order of its visits. */
function TrailNumbers({ walk, positions }: AgentProps) {
  const visits = new Map<string, number[]>()
  walk.trail.forEach((device, i) => visits.set(device, [...(visits.get(device) ?? []), i + 1]))
  return (
    <>
      {[...visits].map(([device, numbers]) => {
        const p = positions.get(device)
        if (!p) return null
        const label = numbers.join('·')
        const width = 10 + label.length * 6.5
        const x = p.x - TILE / 2 - 2
        const y = p.y - TILE / 2 - 2
        return (
          <motion.g
            key={device}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: DURATION.base, ease: EASE_OUT }}
          >
            <rect
              x={x - width / 2}
              y={y - 8}
              width={width}
              height={16}
              rx={8}
              className="fill-provenance-ai stroke-card"
              strokeWidth={1.5}
            />
            <text
              x={x}
              y={y}
              textAnchor="middle"
              dominantBaseline="central"
              className="fill-white font-mono text-[10px] font-semibold"
            >
              {label}
            </text>
          </motion.g>
        )
      })}
    </>
  )
}

/** A light running round the device's border while a command runs on it. */
function ScanBorder({ at }: { at: Point }) {
  const width = TILE + 14
  const height = TILE + 14
  const perimeter = 2 * (width + height)
  return (
    <rect
      x={at.x - width / 2}
      y={at.y - height / 2}
      width={width}
      height={height}
      rx={18}
      strokeWidth={3}
      strokeLinecap="round"
      strokeDasharray={`${perimeter * 0.18} ${perimeter * 0.82}`}
      style={{ '--perimeter': `${perimeter}px` } as CSSProperties}
      className="scan-run fill-none stroke-provenance-ai drop-shadow-[0_0_4px_var(--ai-glow)]"
    />
  )
}

/** The AINOPS marker: travels along the links to the device of each new command. */
function Marker({ walk, positions, links }: AgentProps) {
  // Where it was before, kept so it can travel from there (React's "state from the previous
  // render" pattern: updated while rendering, no effect needed).
  const [move, setMove] = useState({ at: walk.at, from: walk.at })
  if (move.at !== walk.at) setMove({ at: walk.at, from: move.at })
  if (!walk.at) return null
  const route = move.from ? routeBetween(move.from, walk.at, links) : [walk.at]
  const points = pathThrough(route, positions).map(anchor)
  if (points.length === 0) return null
  const thinking = walk.mode === 'thinking'
  return (
    <motion.g
      initial={false}
      animate={{ x: points.map((p) => p.x), y: points.map((p) => p.y) }}
      transition={{ duration: Math.min(0.9, 0.3 * (points.length - 1)), ease: EASE_IN_OUT }}
    >
      {thinking && (
        // The AI is deciding the next step: a slow violet pulse where the agent stands.
        <circle
          r={13}
          className="origin-center animate-ping fill-provenance-ai/35 [animation-duration:1.6s] [transform-box:fill-box] motion-reduce:hidden"
        />
      )}
      <circle r={12} className="fill-provenance-ai drop-shadow-[0_0_8px_var(--ai-glow)]" />
      <path
        d="M12 2l1.9 6.1L20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z"
        transform="translate(-7.2 -7) scale(0.6)"
        className="fill-white"
      />
    </motion.g>
  )
}

/** The knowledge graph answered: a blue wave goes over each device the answer names, in order. */
function LookupSweep({
  lookup,
  positions,
}: { lookup: { key: string; devices: string[] } } & Pick<AgentProps, 'positions'>) {
  return (
    <g key={lookup.key}>
      {lookup.devices.map((device, i) => {
        const p = positions.get(device)
        if (!p) return null
        return (
          <motion.rect
            key={device}
            x={p.x - TILE / 2 - 5}
            y={p.y - TILE / 2 - 5}
            width={TILE + 10}
            height={TILE + 10}
            rx={17}
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: [0, 0.9, 0], scale: [0.96, 1, 1.08] }}
            transition={{ duration: 1.2, delay: i * 0.18, ease: EASE_OUT }}
            className="origin-center fill-provenance-rule-bg/50 stroke-provenance-rule [transform-box:fill-box]"
            strokeWidth={2}
          />
        )
      })}
    </g>
  )
}

const BLOCKED_LABEL = {
  read_only: 'Blocked: AINOPS is read-only',
  address: 'Blocked: address not seen in the evidence',
} as const

/** A call a safety rule blocked: it hits a shield at the device and stops there. */
function BlockedShield({ at, rule }: { at: Point; rule: keyof typeof BLOCKED_LABEL }) {
  const width = BLOCKED_LABEL[rule].length * 6.6 + 24
  // The shield sits on the top edge of the box, its label above it (never over the box).
  const y = at.y - TILE / 2 - 22
  return (
    <motion.g
      initial={{ x: at.x, y: y - 40, opacity: 0 }}
      animate={{ x: at.x, y: [y - 40, y, y - 10, y], opacity: 1 }}
      transition={{ duration: 0.8, ease: EASE_OUT }}
    >
      <g transform="scale(1.5)">
        <path
          d="M0 -16l13 5v9c0 8-5.5 14-13 17-7.5-3-13-9-13-17v-9z"
          className="fill-status-critical-bg stroke-status-critical drop-shadow-[0_0_6px_var(--glow)]"
          strokeWidth={2}
          strokeLinejoin="round"
        />
        <path
          d="M-5 -4l10 10M5 -4l-10 10"
          className="stroke-status-critical"
          strokeWidth={2.4}
          strokeLinecap="round"
        />
      </g>
      <g transform="translate(0, -44)">
        <rect
          x={-width / 2}
          y={-11}
          width={width}
          height={22}
          rx={11}
          className="fill-status-critical stroke-card"
        />
        <text
          textAnchor="middle"
          dominantBaseline="central"
          className="fill-white text-[11.5px] font-semibold"
        >
          {BLOCKED_LABEL[rule]}
        </text>
      </g>
    </motion.g>
  )
}

const PORT_CLASS: Record<string, string> = {
  up: 'fill-status-healthy',
  down: 'fill-status-critical',
  'admin-down': 'fill-status-warning',
}

/** The ports of a checked device as a row of small lights along the bottom of its tile. */
function PortLights({ at, ports }: { at: Point; ports: { name: string; status: string }[] }) {
  const shown = ports.slice(0, 10)
  const size = 3.5
  const gap = 1.5
  const left = at.x - (shown.length * (size + gap) - gap) / 2
  const y = at.y + TILE / 2 - size - 4
  return (
    <g>
      {shown.map((port, i) => (
        <rect
          key={port.name}
          x={left + i * (size + gap)}
          y={y}
          width={size}
          height={size}
          rx={1}
          className={PORT_CLASS[port.status] ?? 'fill-status-unknown'}
        >
          <title>{`${port.name}: ${port.status}`}</title>
        </rect>
      ))}
    </g>
  )
}

interface AgentProps {
  walk: AgentWalk
  positions: Map<string, Point>
  links: GraphLink[]
}

/** The parts drawn inside the map's SVG. */
export function AgentLayer(props: AgentProps) {
  const { walk, positions } = props
  const at = walk.at ? positions.get(walk.at) : undefined
  // A blocked command meant for no device on the map is stopped in the middle of the map.
  const shieldAt = walk.blocked
    ? ((walk.blocked.device ? positions.get(walk.blocked.device) : undefined) ?? {
        x: VIEW_WIDTH / 2,
        y: VIEW_HEIGHT / 2,
      })
    : null
  return (
    <g aria-hidden="true" className="pointer-events-none">
      {[...walk.ports].map(([device, ports]) => {
        const p = positions.get(device)
        return p ? <PortLights key={device} at={p} ports={ports} /> : null
      })}
      <TrailLine {...props} />
      {walk.lookup && (
        <LookupSweep key={walk.lookup.key} lookup={walk.lookup} positions={positions} />
      )}
      {at && walk.console?.state === 'running' && <ScanBorder at={at} />}
      <TrailNumbers {...props} />
      <Marker {...props} />
      {walk.blocked && shieldAt && (
        <BlockedShield key={walk.blocked.key} at={shieldAt} rule={walk.blocked.rule} />
      )}
    </g>
  )
}

/** The command, typed out as it is sent. */
function Typed({ text, instant }: { text: string; instant: boolean }) {
  const [count, setCount] = useState(0)
  useEffect(() => {
    if (instant) return
    const timer = setInterval(() => setCount((c) => Math.min(c + 2, text.length)), 18)
    return () => clearInterval(timer)
  }, [text, instant])
  const shown = instant ? text : text.slice(0, count)
  return (
    <>
      {shown}
      {shown.length < text.length && <span className="animate-pulse">▍</span>}
    </>
  )
}

const VERDICT = {
  ok: { icon: CircleCheck, className: 'text-status-healthy' },
  problem: { icon: TriangleAlert, className: 'text-status-warning' },
  error: { icon: CircleX, className: 'text-status-critical' },
  not_run: { icon: CircleSlash, className: 'text-muted-foreground' },
} as const

function ConsoleCard({ console, instant }: { console: AgentConsole; instant: boolean }) {
  const verdict = console.state === 'running' ? null : VERDICT[console.state]
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: DURATION.base, ease: EASE_OUT }}
      className="flex h-full flex-col overflow-hidden rounded-md border glass font-mono text-[11px] leading-[1.5]"
    >
      <p className="flex shrink-0 items-center gap-1.5 border-b px-2.5 py-1 font-sans text-[10.5px] text-muted-foreground">
        <SquareTerminal aria-hidden="true" className="size-3.5 text-provenance-ai" />
        <span className="font-semibold text-foreground">{console.device}</span>
        <span className="ml-auto">read-only command</span>
      </p>
      <div className="min-h-0 flex-1 space-y-px overflow-hidden px-2.5 py-1.5">
        <p className="break-all text-foreground">
          <span className="text-primary">{console.device}#</span>{' '}
          <Typed text={console.command} instant={instant} />
        </p>
        {console.lines.map((line, i) => (
          <motion.p
            key={i}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: instant ? 0 : 0.15 + i * 0.05, duration: DURATION.fast }}
            className={cn(
              'truncate whitespace-pre text-muted-foreground',
              line === '…' && 'text-[10px] leading-[0.8] opacity-60',
            )}
          >
            {line}
          </motion.p>
        ))}
        {console.state === 'running' && (
          <p className="animate-pulse text-muted-foreground motion-reduce:animate-none">
            waiting for the device…
          </p>
        )}
      </div>
      {verdict && (
        <motion.p
          initial={{ opacity: 0, scale: 1.15 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{
            delay: instant ? 0 : 0.2 + console.lines.length * 0.05,
            duration: DURATION.base,
            ease: EASE_OUT,
          }}
          className={cn(
            'flex shrink-0 items-start gap-1.5 border-t px-2.5 py-1.5 font-sans text-xs font-semibold',
            verdict.className,
          )}
        >
          <verdict.icon aria-hidden="true" className="mt-px size-3.5 shrink-0" />
          <span className="line-clamp-2">{console.verdict}</span>
        </motion.p>
      )}
    </motion.div>
  )
}

/**
 * The agent's console, in a strip under the map: over the map it would hide devices (the live run
 * of 2026-10-22). It keeps the latest command until the next one starts; the timeline keeps all.
 * Its height is fixed, so the page does not jump as commands come and go.
 */
export function AgentConsoleStrip({
  console,
  instant,
}: {
  console: AgentConsole | null
  /** Reduced motion: no typing, no staggered lines. */
  instant: boolean
}) {
  return (
    <div aria-hidden="true" className="mt-2 h-48">
      {console ? (
        <ConsoleCard key={console.key} console={console} instant={instant} />
      ) : (
        <p className="flex h-full items-center justify-center gap-1.5 rounded-md border border-dashed text-xs text-muted-foreground">
          <SquareTerminal aria-hidden="true" className="size-3.5 text-provenance-ai" />
          The commands the agent runs on a device show here
        </p>
      )}
    </div>
  )
}

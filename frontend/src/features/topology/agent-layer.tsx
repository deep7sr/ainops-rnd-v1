// The agent on the live map: a glowing orb that travels along the links to each device the agent
// runs a command on, the numbered trail of where it went, a radar sweeping round the device while
// a command runs, and a console with the command and the first lines the device answered. All of it shows real steps only, and the timeline says the same in words (so this
// layer is aria-hidden).

import { CircleCheck, CircleSlash, CircleX, SquareTerminal, TriangleAlert } from 'lucide-react'
import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
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

const RADAR = 48

/**
 * While a command runs on a device: a breathing glow behind its tile and a radar sweeping round
 * it. Drawn under the tile (see AgentBeneath); still for reduced motion.
 */
function Radar({ at, sweep }: { at: Point; sweep: string }) {
  return (
    <g transform={`translate(${at.x}, ${at.y})`}>
      <circle r={42} className="breathe fill-(--glow)" />
      <circle r={RADAR} className="fill-none stroke-ring" strokeWidth={1.5} strokeDasharray="3 5" />
      {/* The circle gives the group its size, so it turns round the device's centre. */}
      <g className="origin-center animate-[spin_1.6s_linear_infinite] [transform-box:fill-box] motion-reduce:animate-none">
        <circle r={RADAR} className="fill-none" />
        <path
          d={`M0 0 L${RADAR} 0 A${RADAR} ${RADAR} 0 0 0 33.9 -33.9 Z`}
          fill={`url(#${sweep})`}
        />
      </g>
    </g>
  )
}

/** The AINOPS marker: travels along the links to the device of each new command. */
function Marker({ walk, positions, links, orb }: AgentProps & { orb: string }) {
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
        // The AI is deciding the next step: a slow violet ripple where the agent stands.
        <circle
          r={14}
          className="origin-center animate-ping fill-provenance-ai/35 [animation-duration:1.6s] [transform-box:fill-box] motion-reduce:hidden"
        />
      )}
      <circle r={17} className="orb-pulse fill-(--ai-glow)" />
      <circle r={9} fill={`url(#${orb})`} className="drop-shadow-[0_0_6px_var(--ai-glow)]" />
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

/** Gradients of the orb and the radar sweep (ids unique to this map). */
function AgentDefs({ ids }: { ids: AgentIds }) {
  return (
    <defs>
      <radialGradient id={ids.orb} cx="35%" cy="35%" r="70%">
        <stop offset="0%" stopColor="#ffffff" />
        <stop offset="45%" style={{ stopColor: 'var(--provenance-ai-border)' }} />
        <stop offset="100%" style={{ stopColor: 'var(--provenance-ai)' }} />
      </radialGradient>
      <linearGradient id={ids.sweep} x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" style={{ stopColor: 'var(--ring)', stopOpacity: 0 }} />
        <stop offset="100%" style={{ stopColor: 'var(--ring)', stopOpacity: 0.45 }} />
      </linearGradient>
    </defs>
  )
}

export interface AgentIds {
  orb: string
  sweep: string
}

/** The parts drawn under the device tiles: the radar round the device a command runs on. */
export function AgentBeneath({
  walk,
  positions,
  ids,
}: Pick<AgentProps, 'walk' | 'positions'> & { ids: AgentIds }) {
  const at = walk.at ? positions.get(walk.at) : undefined
  return (
    <g aria-hidden="true" className="pointer-events-none">
      <AgentDefs ids={ids} />
      {at && walk.console?.state === 'running' && <Radar at={at} sweep={ids.sweep} />}
    </g>
  )
}

/** The parts drawn over the device tiles. */
export function AgentLayer(props: AgentProps & { ids: AgentIds }) {
  const { walk, positions } = props
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
      <TrailNumbers {...props} />
      <Marker {...props} orb={props.ids.orb} />
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
  ok: { icon: CircleCheck, className: 'border-terminal-ok/50 bg-terminal-ok/15 text-terminal-ok' },
  problem: {
    icon: TriangleAlert,
    className: 'border-terminal-warn/50 bg-terminal-warn/15 text-terminal-warn',
  },
  error: {
    icon: CircleX,
    className: 'border-terminal-bad/50 bg-terminal-bad/15 text-terminal-bad',
  },
  not_run: {
    icon: CircleSlash,
    className: 'border-terminal-muted/50 bg-terminal-muted/10 text-terminal-muted',
  },
} as const

/** The console: a dark terminal with the command typed, the device's first lines, the verdict. */
export function ConsoleCard({ console, instant }: { console: AgentConsole; instant: boolean }) {
  const verdict = console.state === 'running' ? null : VERDICT[console.state]
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-[9px] bg-terminal font-mono text-[11px] leading-[1.5] text-terminal-foreground shadow-[0_10px_30px_rgb(0_0_0/0.28),0_0_0_1px_rgb(0_151_172/0.4)]">
      <p className="flex shrink-0 items-center gap-1.5 bg-terminal-bar px-2.5 py-1 text-[10.5px] text-terminal-muted">
        <span aria-hidden="true" className="size-1.5 rounded-full bg-terminal-ok" />
        <span className="font-semibold text-terminal-foreground">{console.device}</span> console
        <span className="ml-auto">read-only command</span>
      </p>
      <div className="min-h-0 flex-1 space-y-px overflow-hidden px-2.5 py-1.5">
        <p className="break-all">
          <span className="text-terminal-muted">{console.device}#</span>{' '}
          <span className="text-terminal-command">
            <Typed text={console.command} instant={instant} />
          </span>
        </p>
        {console.lines.map((line, i) => (
          <motion.p
            key={i}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: instant ? 0 : 0.15 + i * 0.05, duration: DURATION.fast }}
            className={cn(
              'truncate whitespace-pre',
              line === '…' && 'text-[10px] leading-[0.8] text-terminal-muted',
            )}
          >
            {line}
          </motion.p>
        ))}
        {console.state === 'running' && (
          <p className="animate-pulse text-terminal-muted motion-reduce:animate-none">
            waiting for the device…
          </p>
        )}
      </div>
      {verdict && (
        // The verdict is stamped on, like the mock-up's stamp.
        <motion.p
          initial={{ opacity: 0, scale: 1.6, rotate: -6 }}
          animate={{ opacity: 1, scale: 1, rotate: 0 }}
          transition={{
            delay: instant ? 0 : 0.2 + console.lines.length * 0.05,
            duration: DURATION.base,
            ease: [0.2, 1.6, 0.4, 1],
          }}
          className={cn(
            'mx-2.5 mb-2 flex shrink-0 items-start gap-1.5 self-start rounded border px-2 py-0.5 font-sans text-xs font-semibold',
            verdict.className,
          )}
        >
          <verdict.icon aria-hidden="true" className="mt-px size-3.5 shrink-0" />
          <span className="line-clamp-2">{console.verdict}</span>
        </motion.p>
      )}
    </div>
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
        <motion.div
          key={console.key}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: DURATION.base, ease: EASE_OUT }}
          className="h-full"
        >
          <ConsoleCard console={console} instant={instant} />
        </motion.div>
      ) : (
        <p className="flex h-full items-center justify-center gap-1.5 rounded-md border border-dashed text-xs text-muted-foreground">
          <SquareTerminal aria-hidden="true" className="size-3.5 text-provenance-ai" />
          The commands the agent runs on a device show here
        </p>
      )}
    </div>
  )
}

// The agent at work, above the steps: its loop (think, act, observe), the phase of the investigation
// it is in, live counters, and the system behind it with a pulse along the wire of every real call.
// It keeps moving while the AI thinks, when the map has nothing new to show (the live run of
// 2026-10-22 waited about 30 s for the AI between checks). Data: hud.ts.

import {
  Brain,
  FileCheck,
  MessageSquareText,
  Router,
  SearchCheck,
  Sparkles,
  SquareTerminal,
  Timer,
  Waypoints,
  type LucideIcon,
} from 'lucide-react'
import { animate, motion } from 'motion/react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { usePrefersReducedMotion } from '@/hooks/use-reduced-motion'
import { DURATION, EASE_IN_OUT, EASE_OUT } from '@/lib/motion'
import { cn } from '@/lib/utils'
import { PHASES, type Hud, type Phase } from './hud'

const PHASE: Record<Phase, { label: string; icon: LucideIcon }> = {
  understand: { label: 'Understand', icon: MessageSquareText },
  locate: { label: 'Locate', icon: Waypoints },
  check: { label: 'Check live', icon: SquareTerminal },
  reason: { label: 'Reason', icon: Brain },
  verify: { label: 'Verify', icon: SearchCheck },
  report: { label: 'Report', icon: FileCheck },
}

/** How long the ring shows "observe" when a result comes back (the timeline holds it as long). */
const OBSERVE_MS = 1500

type Loop = 'think' | 'act' | 'observe'

/** True for a moment after a new result came back; not for the one there when the page opened. */
function useObserving(observed: string | null): boolean {
  const [first] = useState(observed)
  const [over, setOver] = useState<string | null>(null)
  useEffect(() => {
    if (observed === null || observed === first) return
    const timer = setTimeout(() => setOver(observed), OBSERVE_MS)
    return () => clearTimeout(timer)
  }, [observed, first])
  return observed !== null && observed !== first && over !== observed
}

/** A number that counts up to its new value (at once for reduced motion, and when the page opens). */
function CountUp({
  value,
  format = (n) => String(n),
}: {
  value: number
  format?: (n: number) => string
}) {
  const reduced = usePrefersReducedMotion()
  const [shown, setShown] = useState(value)
  const from = useRef(value)
  useEffect(() => {
    if (reduced) return
    const controls = animate(from.current, value, {
      duration: DURATION.slow * 2,
      ease: EASE_OUT,
      onUpdate: (latest) => {
        from.current = latest
        setShown(latest)
      },
    })
    return () => controls.stop()
  }, [value, reduced])
  return <>{format(reduced ? value : Math.round(shown))}</>
}

const minutes = (ms: number) => {
  const seconds = Math.floor(ms / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

const thousands = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n))

/**
 * Time into the reply: `baseMs` is when the last event happened, `arrivedAt` when it reached the
 * browser (performance.now()); while the reply runs the clock goes on from there every second.
 */
function useClock(baseMs: number, arrivedAt: number | null, running: boolean): number {
  const [now, setNow] = useState<number | null>(null)
  useEffect(() => {
    if (!running || arrivedAt === null) return
    const timer = setInterval(() => setNow(performance.now()), 1000)
    return () => clearInterval(timer)
  }, [running, arrivedAt])
  if (!running || arrivedAt === null || now === null || now < arrivedAt) return baseMs
  return baseMs + (now - arrivedAt)
}

function PhaseRail({ phase, visited }: { phase: Phase | null; visited: Set<Phase> }) {
  return (
    <ol aria-label="Phases of the investigation" className="flex flex-wrap gap-1">
      {PHASES.map((p) => {
        const { label, icon: Icon } = PHASE[p]
        const on = p === phase
        const been = !on && visited.has(p)
        return (
          <li
            key={p}
            aria-current={on ? 'step' : undefined}
            className={cn(
              'flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[11px] font-medium transition-colors duration-(--motion-base)',
              on
                ? 'border-provenance-ai bg-provenance-ai text-background ai-glow'
                : been
                  ? 'border-primary/30 bg-secondary text-primary'
                  : 'border-border text-muted-foreground',
            )}
          >
            <Icon aria-hidden="true" className="size-3" />
            {label}
            {been && <span className="sr-only"> (been through)</span>}
          </li>
        )
      })}
    </ol>
  )
}

/** A piece of the ring from angle a0 to a1 (degrees, 0 at the top, clockwise). */
function arc(a0: number, a1: number): string {
  const [cx, cy, r] = [60, 62, 42]
  const point = (a: number) => {
    const rad = ((a - 90) * Math.PI) / 180
    return `${(cx + r * Math.cos(rad)).toFixed(1)} ${(cy + r * Math.sin(rad)).toFixed(1)}`
  }
  return `M ${point(a0)} A ${r} ${r} 0 0 1 ${point(a1)}`
}

const ARCS: {
  loop: Loop
  d: string
  label: string
  x: number
  y: number
  anchor: 'middle' | 'start' | 'end'
  tone: string
}[] = [
  {
    loop: 'think',
    d: arc(-55, 55),
    label: 'THINK',
    x: 60,
    y: 11,
    anchor: 'middle',
    tone: 'text-provenance-ai',
  },
  {
    loop: 'act',
    d: arc(65, 175),
    label: 'ACT',
    x: 118,
    y: 117,
    anchor: 'end',
    tone: 'text-primary',
  },
  {
    loop: 'observe',
    d: arc(185, 295),
    label: 'OBSERVE',
    x: 2,
    y: 117,
    anchor: 'start',
    tone: 'text-ring',
  },
]

const LOOP_SAYS: Record<Loop, string> = {
  think: 'thinking',
  act: 'running a check',
  observe: 'reading a result',
}

/** Think, act, observe: the loop of a tool-using agent (ReAct), lit where the agent is now. */
function LoopRing({ loop, checks }: { loop: Loop | null; checks: number }) {
  return (
    <svg
      viewBox="0 0 120 120"
      role="img"
      aria-label={`The agent's loop: ${loop ? LOOP_SAYS[loop] : 'idle'}, ${checks} ${checks === 1 ? 'check' : 'checks'} so far`}
      className="size-24 shrink-0 xl:size-28"
    >
      {ARCS.map((a) => {
        const on = a.loop === loop
        return (
          <g key={a.loop} className={on ? a.tone : 'text-border'}>
            <path
              d={a.d}
              fill="none"
              stroke="currentColor"
              strokeWidth={7}
              strokeLinecap="round"
              className="transition-colors duration-(--motion-base)"
            />
            {/* Light running along the lit arc: the loop is turning. */}
            {on && (
              <path
                d={a.d}
                fill="none"
                stroke="var(--card)"
                strokeWidth={2}
                strokeLinecap="round"
                opacity={0.8}
                className="flow-dash"
              />
            )}
            <text
              x={a.x}
              y={a.y}
              textAnchor={a.anchor}
              className={cn(
                'text-[9px] font-bold tracking-wider',
                on ? 'fill-current' : 'fill-muted-foreground',
              )}
            >
              {a.label}
            </text>
          </g>
        )
      })}
      <text
        x={60}
        y={66}
        textAnchor="middle"
        className="fill-foreground text-[24px] font-semibold tabular-nums"
      >
        <CountUp value={checks} />
      </text>
      <text x={60} y={80} textAnchor="middle" className="fill-muted-foreground text-[9px]">
        {checks === 1 ? 'check' : 'checks'}
      </text>
    </svg>
  )
}

/** One box of the architecture strip. */
function Box({
  x,
  y,
  w,
  h,
  title,
  sub,
  tone,
}: {
  x: number
  y: number
  w: number
  h: number
  title: string
  sub: string[]
  tone: 'idle' | 'lit' | 'ai' | 'stopped'
}) {
  const cx = x + w / 2
  const top = y + h / 2 - (sub.length * 11) / 2 + 3
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={7}
        strokeWidth={1.5}
        className={cn(
          'transition-colors duration-(--motion-base)',
          tone === 'lit' && 'fill-secondary stroke-primary',
          tone === 'ai' && 'fill-provenance-ai-bg stroke-provenance-ai',
          tone === 'stopped' && 'fill-status-critical-bg stroke-status-critical',
          tone === 'idle' && 'fill-card stroke-border',
        )}
      />
      <text
        x={cx}
        y={top}
        textAnchor="middle"
        className="fill-foreground text-[10.5px] font-semibold"
      >
        {title}
      </text>
      {sub.map((line, i) => (
        <text
          key={line}
          x={cx}
          y={top + 12 + i * 11}
          textAnchor="middle"
          className={cn(
            'text-[9.5px]',
            tone === 'stopped' ? 'fill-status-critical' : 'fill-muted-foreground',
          )}
        >
          {line}
        </text>
      ))}
    </g>
  )
}

// Where the wires run in the strip (viewBox 300 x 124, about its size on screen, so its words stay
// readable): the agent on the left, the topology MCP server and the graph on the top row, the
// guard, the network MCP server and the devices below.
const WIRE = {
  topology: { y: 34, from: 65, to: 208 },
  network: { y: 94, from: 65, to: 236 },
} as const

function ArchStrip({ hud, deviceCount }: { hud: Hud; deviceCount: number }) {
  const reduced = usePrefersReducedMotion()
  // A call already there when the page opened sends no pulse.
  const [firstCall] = useState(hud.lastCall?.key ?? null)
  const pulse = hud.lastCall && hud.lastCall.key !== firstCall && !reduced ? hud.lastCall : null
  const net = hud.running === 'network'
  const topo = hud.running === 'topology'
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
  return (
    <svg
      viewBox="0 0 300 124"
      role="img"
      aria-label={`Behind the scenes: the AI agent called the topology MCP server ${plural(hud.topologyCalls, 'time')}, which reads the knowledge graph, and the network MCP server ${plural(hud.networkCalls, 'time')}, which runs read-only commands on the devices behind a safety guard (${hud.blocked} blocked).`}
      className="mx-auto max-h-36 w-full max-w-sm"
    >
      {(['topology', 'network'] as const).map((server) => {
        const { y, from, to } = WIRE[server]
        const on = hud.running === server
        return (
          <g key={server} className={on ? 'text-primary' : 'text-border'}>
            <path d={`M ${from} ${y} H ${to}`} stroke="currentColor" strokeWidth={2} />
            {on && (
              <path
                d={`M ${from} ${y} H ${to}`}
                stroke="currentColor"
                strokeWidth={2}
                className="flow-dash text-ring"
              />
            )}
          </g>
        )
      })}
      {/* The call travels out to the server and its answer comes back (behind the boxes). */}
      {pulse && (
        <motion.circle
          key={pulse.key}
          r={4.5}
          cy={WIRE[pulse.server].y}
          className="fill-ring"
          initial={{ cx: WIRE[pulse.server].from, opacity: 1 }}
          animate={{
            cx: [WIRE[pulse.server].from, WIRE[pulse.server].to, WIRE[pulse.server].from],
            opacity: [1, 1, 0],
          }}
          transition={{ duration: 1.6, ease: EASE_IN_OUT, times: [0, 0.5, 1] }}
        />
      )}
      <rect
        x={0}
        y={10}
        width={68}
        height={104}
        rx={10}
        className={cn(
          'fill-provenance-ai/15',
          hud.loop === 'think' ? 'animate-pulse motion-reduce:animate-none' : 'opacity-0',
        )}
      />
      <Box
        x={3}
        y={14}
        w={62}
        h={96}
        title="AI agent"
        sub={['LLM picks', 'the next tool']}
        tone="ai"
      />
      <Box
        x={102}
        y={14}
        w={92}
        h={40}
        title="Topology MCP"
        sub={[plural(hud.topologyCalls, 'call')]}
        tone={topo ? 'lit' : 'idle'}
      />
      <Box
        x={208}
        y={14}
        w={90}
        h={40}
        title="Knowledge"
        sub={['graph · Neo4j']}
        tone={topo ? 'lit' : 'idle'}
      />
      <Box
        x={80}
        y={74}
        w={54}
        h={40}
        title="Guard"
        sub={[hud.blocked ? `${hud.blocked} blocked` : 'read-only']}
        tone={hud.guardStopped ? 'stopped' : net ? 'lit' : 'idle'}
      />
      <Box
        x={144}
        y={74}
        w={82}
        h={40}
        title="Network MCP"
        sub={[plural(hud.networkCalls, 'call')]}
        tone={net ? 'lit' : 'idle'}
      />
      <Box
        x={236}
        y={74}
        w={62}
        h={40}
        title={plural(deviceCount, 'device')}
        sub={[`${hud.devices} checked`]}
        tone={net ? 'lit' : 'idle'}
      />
    </svg>
  )
}

function Counter({
  icon: Icon,
  label,
  children,
  ai = false,
}: {
  icon: LucideIcon
  label: string
  children: ReactNode
  ai?: boolean
}) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1 text-[11px] text-muted-foreground">
        <Icon aria-hidden="true" className={cn('size-3 shrink-0', ai && 'text-provenance-ai')} />
        <span className="truncate">{label}</span>
      </dt>
      <dd className="text-lg leading-tight font-semibold tabular-nums">{children}</dd>
    </div>
  )
}

export function AgentHud({
  hud,
  running,
  clock: { ms, arrivedAt },
  deviceCount,
}: {
  hud: Hud
  running: boolean
  /** Time into the reply of its latest event (hud.ts lastTime), and when that event reached the
   *  browser (performance.now(); null: unknown). */
  clock: { ms: number; arrivedAt: number | null }
  /** Devices on the map. */
  deviceCount: number
}) {
  const observing = useObserving(hud.observed)
  const loop: Loop | null = observing ? 'observe' : hud.loop
  const elapsed = useClock(ms, arrivedAt, running)
  return (
    <section aria-label="The agent at work" className="space-y-3 rounded-lg border glass p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-xs font-semibold tracking-wider text-eyebrow uppercase">
          <Sparkles aria-hidden="true" className="size-3.5 text-provenance-ai" /> The agent at work
        </p>
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {running && (
            <span
              aria-hidden="true"
              className="size-2 animate-pulse rounded-full bg-provenance-ai motion-reduce:animate-none"
            />
          )}
          {running ? 'live' : hud.phase === 'report' ? 'finished' : 'stopped'}
        </p>
      </div>
      <PhaseRail phase={hud.phase} visited={hud.visited} />
      <div className="flex items-center gap-3">
        <LoopRing loop={loop} checks={hud.checks} />
        <dl className="grid min-w-0 flex-1 grid-cols-2 gap-x-2 gap-y-2">
          <Counter icon={Timer} label="Time">
            {minutes(elapsed)}
          </Counter>
          <Counter icon={Router} label="Devices">
            <CountUp value={hud.devices} />
          </Counter>
          <Counter icon={SquareTerminal} label="Commands">
            <CountUp value={hud.commands} />
          </Counter>
          <Counter icon={FileCheck} label="Evidence">
            <CountUp value={hud.evidence} />
          </Counter>
          <Counter icon={Sparkles} label="AI tokens" ai>
            {hud.tokens === null ? '–' : <CountUp value={hud.tokens} format={thousands} />}
          </Counter>
        </dl>
      </div>
      <ArchStrip hud={hud} deviceCount={deviceCount} />
    </section>
  )
}

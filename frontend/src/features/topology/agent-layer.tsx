// The agent on the live map: a marker that travels along the links to each device the agent runs
// a command on, the numbered trail of where it went, a radar sweep while a command runs, and a
// console beside the device with the command and the first lines the device answered. All of it
// shows real steps only, and the timeline says the same in words (so this layer is aria-hidden).

import { CircleCheck, CircleX, SquareTerminal, TriangleAlert } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState, type CSSProperties } from 'react'
import type { GraphLink } from '@/api'
import { DURATION, EASE_IN_OUT, EASE_OUT } from '@/lib/motion'
import { cn } from '@/lib/utils'
import type { AgentConsole, AgentWalk } from './highlight'
import { NODE_HEIGHT, NODE_WIDTH, VIEW_HEIGHT, type Point } from './layout'
import { routeBetween } from './route'

/** A console folds away this long after its result is in (the timeline keeps it). */
const FOLD_MS = 4500

/** Where the marker sits on a device: the middle of the box's top edge. */
const anchor = (p: Point): Point => ({ x: p.x, y: p.y - NODE_HEIGHT / 2 })

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
        const x = p.x - NODE_WIDTH / 2 - 4
        const y = p.y - NODE_HEIGHT / 2 - 4
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
  const width = NODE_WIDTH + 14
  const height = NODE_HEIGHT + 14
  const perimeter = 2 * (width + height)
  return (
    <rect
      x={at.x - width / 2}
      y={at.y - height / 2}
      width={width}
      height={height}
      rx={10}
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

interface AgentProps {
  walk: AgentWalk
  positions: Map<string, Point>
  links: GraphLink[]
}

/** The parts drawn inside the map's SVG. */
export function AgentLayer(props: AgentProps) {
  const { walk, positions } = props
  const at = walk.at ? positions.get(walk.at) : undefined
  return (
    <g aria-hidden="true" className="pointer-events-none">
      <TrailLine {...props} />
      {at && walk.console?.state === 'running' && <ScanBorder at={at} />}
      <TrailNumbers {...props} />
      <Marker {...props} />
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
} as const

function ConsoleCard({ console, instant }: { console: AgentConsole; instant: boolean }) {
  const verdict = console.state === 'running' ? null : VERDICT[console.state]
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.94 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.94 }}
      transition={{ duration: DURATION.base, ease: EASE_OUT }}
      className="overflow-hidden rounded-md border glass font-mono text-[11px] leading-[1.5]"
    >
      <p className="flex items-center gap-1.5 border-b px-2.5 py-1 font-sans text-[10.5px] text-muted-foreground">
        <SquareTerminal aria-hidden="true" className="size-3.5 text-provenance-ai" />
        <span className="font-semibold text-foreground">{console.device}</span>
        <span className="ml-auto">read-only command</span>
      </p>
      <div className="space-y-px px-2.5 py-1.5">
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
            className="truncate whitespace-pre text-muted-foreground"
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
            'flex items-start gap-1.5 border-t px-2.5 py-1.5 font-sans text-xs font-semibold',
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

/** The console beside the device, as HTML over the map so its text keeps a readable size. */
export function AgentConsoleOverlay({
  console,
  positions,
  viewLeft,
  viewWidth,
  instant,
}: {
  console: AgentConsole | null
  positions: Map<string, Point>
  viewLeft: number
  viewWidth: number
  /** Reduced motion: no typing, no staggered lines. */
  instant: boolean
}) {
  const [foldedKey, setFoldedKey] = useState<string | null>(null)
  const key = console?.key ?? null
  const finished = console !== null && console.state !== 'running'
  useEffect(() => {
    if (!key || !finished) return
    const timer = setTimeout(() => setFoldedKey(key), FOLD_MS)
    return () => clearTimeout(timer)
  }, [key, finished])

  const at = console ? positions.get(console.device) : undefined
  const shown = console && at && foldedKey !== console.key
  // Docked at the edge of the map away from the device (top band for a device in the lower half,
  // bottom band otherwise), over the device's column: beside the box it would hide its neighbours.
  const x = at ? ((at.x - viewLeft) / viewWidth) * 100 : 50
  const left = `clamp(0px, calc(${x}% - min(8.5rem, 23%)), calc(100% - min(17rem, 46%)))`
  const edge = at && at.y < VIEW_HEIGHT / 2 ? { bottom: '3%' } : { top: '3%' }

  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0">
      <AnimatePresence>
        {shown && (
          <div
            key={console.key}
            className="absolute z-10 w-[min(17rem,46%)]"
            style={{ left, ...edge }}
          >
            <ConsoleCard console={console} instant={instant} />
          </div>
        )}
      </AnimatePresence>
    </div>
  )
}

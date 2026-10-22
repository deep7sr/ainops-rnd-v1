// The agent HUD (heads-up display) beside the map: where the agent is in its loop, which phase of
// the investigation it is in, live counters, and the board of devices it suspects. Everything comes
// from the steps and events of the run, like the map: nothing is estimated or invented.

import type { RunEvent } from '@/api'
import { deviceStates, isSafetyBlock, type InvestigationView, type Now, type Step } from './derive'

/**
 * think: the AI is deciding (waiting for the LLM). act: a tool runs. The AI reads a result and
 * decides the next step in one call, so "observe" is not a separate event: the ring shows it for a
 * moment when a result comes back (`observed` changes), then goes back to think.
 */
export type LoopPhase = 'think' | 'act' | null

export const PHASES = ['understand', 'locate', 'check', 'reason', 'verify', 'report'] as const
export type Phase = (typeof PHASES)[number]

export type SuspectColumn = 'todo' | 'healthy' | 'problem' | 'cause'

export interface Suspect {
  device: string
  /** A check runs on it right now (it stays in its column meanwhile). */
  checking: boolean
  /** The problem seen, or the blamed interfaces; null when there is nothing to add. */
  note: string | null
}

export interface Hud {
  loop: LoopPhase
  /** While the AI thinks: the last step that finished. A new one means a result just came back. */
  observed: string | null
  /** The phase the agent is in now; null once it stopped without an answer. */
  phase: Phase | null
  /** Phases of the latest reply the agent has been in (it can go back to one). */
  visited: Set<Phase>
  /** Tool calls (the evidence ids handed out). */
  checks: number
  /** Devices the agent learned something about (a trace counts for every hop it read). */
  devices: number
  /** Commands sent to devices (not the calls the guard or the tool turned down). */
  commands: number
  /** Checks that came back with a result: evidence the answer can cite. */
  evidence: number
  topologyCalls: number
  networkCalls: number
  /** Calls the safety rules stopped. */
  blocked: number
  /** The MCP server a tool runs on right now. */
  running: 'topology' | 'network' | null
  /** The latest tool call: a new one sends a pulse along its wire. */
  lastCall: { key: string; server: 'topology' | 'network' } | null
  /** The latest step is a call the safety rules stopped. */
  guardStopped: boolean
  /** AI tokens of the whole conversation; null in runs recorded before they were counted. */
  tokens: number | null
  suspects: Record<SuspectColumn, Suspect[]>
}

function phaseNow(now: Now, turn: Step[]): Phase | null {
  switch (now.kind) {
    case 'starting':
      return 'understand'
    case 'working':
      return now.step.server === 'topology' ? 'locate' : 'check'
    case 'thinking':
      if (!turn.some((s) => s.kind === 'tool')) return 'understand'
      return turn[turn.length - 1]?.kind === 'recheck' ? 'verify' : 'reason'
    case 'done':
      return 'report'
    case 'stopped':
      return null
  }
}

function visitedPhases(now: Now, turn: Step[], phase: Phase | null): Set<Phase> {
  const tools = turn.filter((s) => s.kind === 'tool')
  // The AI has read a result once something came after it.
  const readResult = turn.some(
    (s, i) => s.kind === 'tool' && s.state !== 'running' && i < turn.length - 1,
  )
  const seen: [Phase, boolean][] = [
    ['understand', true],
    ['locate', tools.some((s) => s.server === 'topology')],
    ['check', tools.some((s) => s.server === 'network')],
    ['reason', readResult || now.kind === 'done'],
    ['verify', turn.some((s) => s.kind === 'recheck')],
    ['report', now.kind === 'done'],
  ]
  const visited = new Set(seen.filter(([, yes]) => yes).map(([p]) => p))
  if (phase) visited.add(phase)
  return visited
}

/** Tokens per reply: the latest count a reply sent (each thought, then the report), summed. */
function conversationTokens(events: RunEvent[]): number | null {
  let done = 0
  let current: number | null = null
  let known = false
  for (const event of events) {
    const used =
      event.type === 'thought' || event.type === 'report'
        ? event.tokens
          ? event.tokens.input + event.tokens.output
          : null
        : null
    if (event.type === 'message') {
      done += current ?? 0
      current = null
    } else if (used !== null) {
      current = used
      known = true
    }
  }
  return known ? done + (current ?? 0) : null
}

/**
 * How far into the latest reply the last event with a time happened, and its index (-1: none).
 * The page ticks the clock on from there while the reply runs.
 */
export function lastTime(events: RunEvent[]): { ms: number; index: number } {
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i]
    if (event.type === 'message') return { ms: 0, index: i }
    if ('at_ms' in event && typeof event.at_ms === 'number') return { ms: event.at_ms, index: i }
  }
  return { ms: 0, index: -1 }
}

function suspects(view: InvestigationView, onMap: Set<string>): Record<SuspectColumn, Suspect[]> {
  const { path, issues, faultDevices, faultInterfaces } = view.highlight
  // Where each device stands from the checks that came back: a device being checked again keeps
  // its place on the board while the check runs.
  const settled = deviceStates(view.steps.filter((s) => s.state !== 'running'))
  const checking = new Set(
    view.steps
      .filter((s) => s.kind === 'tool' && s.server === 'network' && s.state === 'running')
      .map((s) => s.device)
      .filter((d): d is string => d !== null),
  )
  const board: Record<SuspectColumn, Suspect[]> = { todo: [], healthy: [], problem: [], cause: [] }
  const order = new Set([...path, ...settled.keys(), ...checking, ...faultDevices])
  for (const device of order) {
    if (!onMap.has(device)) continue
    const card = { device, checking: checking.has(device), note: null as string | null }
    const state = settled.get(device)
    if (faultDevices.has(device)) {
      const blamed = [...faultInterfaces]
        .filter((key) => key.startsWith(`${device}:`))
        .map((key) => key.slice(device.length + 1))
      board.cause.push({ ...card, note: blamed.length ? blamed.join(', ') : null })
    } else if (state === 'problem') {
      board.problem.push({ ...card, note: issues.get(device)?.[0] ?? null })
    } else if (state === 'unreachable') {
      board.problem.push({ ...card, note: 'Did not answer' })
    } else if (state === 'ok' || state === 'checked') {
      board.healthy.push(card)
    } else {
      board.todo.push(card)
    }
  }
  return board
}

function serverOf(step: Step): 'topology' | 'network' | null {
  return step.server === 'topology' || step.server === 'network' ? step.server : null
}

export function deriveHud(
  view: InvestigationView,
  now: Now,
  events: RunEvent[],
  onMap: Set<string>,
): Hud {
  const { steps } = view
  const turn = steps.filter((s) => s.turn === view.turn)
  const tools = steps.filter((s) => s.kind === 'tool')
  const phase = phaseNow(now, turn)
  const lastResult = [...steps].reverse().find((s) => s.kind === 'tool' || s.kind === 'refused')
  const lastCall = [...tools].reverse().find((s) => serverOf(s) !== null)
  const last = steps[steps.length - 1]
  return {
    loop:
      now.kind === 'working'
        ? 'act'
        : now.kind === 'thinking' || now.kind === 'starting'
          ? 'think'
          : null,
    observed: now.kind === 'thinking' ? (lastResult?.key ?? null) : null,
    phase,
    visited: visitedPhases(now, turn, phase),
    checks: tools.length,
    devices: deviceStates(steps).size,
    commands: tools.filter(
      (s) => s.server === 'network' && s.failure !== 'request' && s.failure !== 'blocked',
    ).length,
    evidence: tools.filter((s) => s.state === 'ok').length,
    topologyCalls: tools.filter((s) => s.server === 'topology').length,
    networkCalls: tools.filter((s) => s.server === 'network').length,
    blocked: steps.filter(isSafetyBlock).length,
    running: now.kind === 'working' ? serverOf(now.step) : null,
    lastCall: lastCall ? { key: lastCall.key, server: serverOf(lastCall)! } : null,
    guardStopped: last !== undefined && isSafetyBlock(last),
    tokens: conversationTokens(events),
    suspects: suspects(view, onMap),
  }
}

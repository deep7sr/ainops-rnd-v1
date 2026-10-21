import type { Evidence, Report, RunEvent, ToolHealth } from '@/api'
import type { DeviceState, MapHighlight, MapPing } from '@/features/topology/highlight'
import { describeCall, shortCall } from './describe'
import { readTrace } from './trace'

// Turns the raw event stream of an investigation into what the page shows: the steps of the
// timeline, the final report, and what to highlight on the map.
//
// An investigation is a conversation: each follow-up message from the engineer starts a new turn.
// The steps and the map keep everything checked so far; the report, the "Now" line and the
// error belong to the latest turn.

export interface Step {
  /** 'skill': the agent opened an expert skill (no tool ran). 'hints': similar past cases were
   *  looked up for this reply (no tool ran; hints, never evidence). 'recheck': AINOPS sent the
   *  answer back because no cited check showed what it blamed (no tool ran). */
  kind: 'tool' | 'refused' | 'skill' | 'hints' | 'recheck'
  key: string
  evidenceId: string | null
  tool: string
  server: string
  args: Record<string, unknown>
  why: string
  /** The call as a plain sentence, e.g. "Checking the interfaces of IPLC-RTR-MAA". */
  sentence: string
  state: 'running' | 'ok' | 'error'
  summary: string
  data: unknown
  evidence: Evidence | null
  /** Code-computed verdict on the result (network tools); null when there is none. */
  health: ToolHealth | null
  device: string | null
  durationMs: number | null
  atMs: number
  /** Step of the open skill this call carries out; 0 = beyond the skill; null = no skill open. */
  skillStep: number | null
  /** Which message of the conversation this step answers (1 = the question). */
  turn: number
}

/** The expert skill the agent opened (the latest one, if it opened two). */
export interface ActiveSkill {
  name: string
  description: string
  steps: string[]
  author: string
  reviewedBy: string
}

export interface Verdict {
  report: Report
  confidence: 'high' | 'medium' | 'low'
  reasons: string[]
  toolCalls: number
  skillsUsed: string[]
  /** What the AI read and wrote for this reply; null in runs recorded before it was counted. */
  tokens: { input: number; output: number } | null
  atMs: number
}

/** A refusal or a plain answer needs no network evidence: no confidence is shown for it. */
export function needsEvidence(outcome: Report['outcome']): boolean {
  return outcome !== 'refused' && outcome !== 'answered'
}

/** The map appears once the agent uses a tool; a greeting or a refusal has nothing to show. */
export function touchesNetwork(steps: Step[]): boolean {
  return steps.some((s) => s.kind === 'tool')
}

/** What the agent is doing right now, for the "Now" line above the map. */
export type Now =
  | { kind: 'starting' }
  | { kind: 'working'; step: Step }
  | { kind: 'thinking'; last: Step | null }
  | { kind: 'done'; verdict: Verdict }
  | { kind: 'stopped'; message: string }

export interface InvestigationView {
  /** The latest message: the question, or the engineer's latest follow-up. */
  question: string | null
  /** Messages the engineer sent so far (the question counts as 1). */
  turn: number
  steps: Step[]
  notes: string[]
  verdict: Verdict | null
  error: string | null
  now: Now
  skill: ActiveSkill | null
  highlight: MapHighlight
}

const LONG_TO_SHORT: [string, string][] = [
  ['TenGigabitEthernet', 'Te'],
  ['GigabitEthernet', 'Gi'],
  ['FastEthernet', 'Fa'],
  ['Ethernet', 'E'],
  ['Serial', 'Se'],
  ['Loopback', 'Lo'],
]

/** "FastEthernet2/0" and "Fa2/0" -> "Fa2/0", the spelling the graph uses. */
export function shortInterface(name: string): string {
  for (const [long, short] of LONG_TO_SHORT) {
    if (name.toLowerCase().startsWith(long.toLowerCase())) return short + name.slice(long.length)
  }
  return name
}

const INTERFACE_PATTERN = /^[A-Za-z]{1,20}-?\d{1,3}(?:\/\d{1,3}){0,3}(?:\.\d{1,5})?,?$/

/** Devices and "DEVICE:interface" keys named in the report's `affected` list. */
export function parseAffected(affected: string[], deviceNames: string[]) {
  const devices = new Set<string>()
  const interfaces = new Set<string>()
  const byUpper = new Map(deviceNames.map((name) => [name.toUpperCase(), name]))
  for (const entry of affected) {
    const words = entry.split(/[\s,;()]+/).filter(Boolean)
    const device = words.map((w) => byUpper.get(w.toUpperCase())).find(Boolean)
    if (!device) continue
    devices.add(device)
    for (const word of words) {
      if (word.toUpperCase() !== device.toUpperCase() && INTERFACE_PATTERN.test(word)) {
        interfaces.add(`${device}:${shortInterface(word.replace(/,$/, ''))}`)
      }
    }
  }
  return { devices, interfaces }
}

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
const text = (value: unknown): string => (typeof value === 'string' ? value : '')
const stepNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null

function deviceOf(args: Record<string, unknown>): string | null {
  return typeof args.device === 'string' ? args.device : null
}

export function deriveInvestigation(events: RunEvent[], deviceNames: string[]): InvestigationView {
  const steps: Step[] = []
  const byId = new Map<string, Step>()
  const notes: string[] = []
  let question: string | null = null
  let verdict: Verdict | null = null
  let error: string | null = null
  let path: string[] = []
  let pathEnds: [string, string] = ['', '']
  let traced = false // a traced route (the way traffic really goes) beats the cabled path
  let skill: ActiveSkill | null = null
  let turn = 1
  const canonical = new Map(deviceNames.map((name) => [name.toUpperCase(), name]))
  // Events come from the server and from old recordings: anything but a device name is ignored.
  const resolve = (name: unknown) =>
    typeof name === 'string' && name ? (canonical.get(name.toUpperCase()) ?? name) : null

  for (const event of events) {
    switch (event.type) {
      case 'started':
        question = event.question
        break
      case 'message':
        // A follow-up: a new turn. Its reply has not started, nor failed, nor reported yet.
        turn = typeof event.turn === 'number' ? event.turn : turn + 1
        question = text(event.text)
        verdict = null
        error = null
        skill = null
        break
      case 'thought':
        if (event.text) notes.push(event.text)
        break
      case 'tool_call': {
        const step: Step = {
          kind: 'tool',
          key: event.id,
          evidenceId: event.id,
          tool: event.tool,
          server: event.server,
          args: event.args,
          why: event.why ?? '',
          sentence: describeCall(event.tool, event.args),
          state: 'running',
          summary: '',
          data: null,
          evidence: null,
          health: null,
          device: resolve(deviceOf(event.args)) ?? traceStart(event.tool, event.args, canonical),
          durationMs: null,
          atMs: event.at_ms,
          skillStep: skill ? stepNumber(event.skill_step) : null,
          turn,
        }
        steps.push(step)
        byId.set(event.id, step)
        break
      }
      case 'tool_result': {
        const step = byId.get(event.id)
        if (!step) break
        step.state = event.ok ? 'ok' : 'error'
        step.summary = event.summary
        step.data = event.data
        step.evidence = event.evidence
        step.health = event.health ?? null
        step.durationMs = event.duration_ms
        step.device = resolve(event.device) ?? step.device
        const trace = event.ok && event.tool === 'trace_route' ? readTrace(event.data) : null
        if (trace && trace.hops.length >= 2) {
          path = trace.hops.map((hop) => resolve(hop.device) ?? hop.device)
          pathEnds = [String(step.args.source ?? ''), trace.destination]
          traced = true
        }
        if (event.ok && event.tool === 'get_path' && !traced) {
          const devices = (event.data as { devices?: unknown } | null)?.devices
          if (Array.isArray(devices)) {
            path = devices.map((d) => resolve(String(d)) ?? String(d))
            pathEnds = [String(step.args.source ?? ''), String(step.args.destination ?? '')]
          }
        }
        break
      }
      case 'skill': {
        const name = text(event.name)
        if (!name) break
        skill = {
          name,
          description: text(event.description),
          steps: strings(event.steps),
          author: text(event.author),
          reviewedBy: text(event.reviewed_by),
        }
        steps.push({
          kind: 'skill',
          key: `skill-${steps.length}`,
          evidenceId: null,
          tool: 'use_skill',
          server: 'agent',
          args: { skill: name, reviewed_by: skill.reviewedBy, status: text(event.status) },
          why: text(event.why),
          sentence: `Using the expert skill "${name}"`,
          state: 'ok',
          summary: skill.description,
          data: skill.steps,
          evidence: null,
          health: null,
          device: null,
          durationMs: 0,
          atMs: event.at_ms,
          skillStep: null,
          turn,
        })
        break
      }
      case 'hints': {
        const found = Array.isArray(event.cases) ? event.cases : []
        // "None yet" is said once, for the question; later replies show only what they found.
        if (found.length === 0 && turn > 1) break
        steps.push({
          kind: 'hints',
          key: `hints-${turn}`,
          evidenceId: null,
          tool: 'similar_cases',
          server: 'agent',
          args: {},
          why: '',
          sentence: found.length
            ? `Found ${found.length} similar past case${found.length === 1 ? '' : 's'}: hints, not evidence`
            : 'Looked for similar past cases: none yet',
          state: 'ok',
          summary: found.length
            ? 'From cases engineers approved. AINOPS still checks the live devices.'
            : (event.error ?? 'AINOPS learns from the cases engineers approve.'),
          data: found,
          evidence: null,
          health: null,
          device: null,
          durationMs: 0,
          atMs: event.at_ms,
          skillStep: null,
          turn,
        })
        break
      }
      case 'recheck':
        steps.push({
          kind: 'recheck',
          key: `recheck-${steps.length}`,
          evidenceId: null,
          tool: 'recheck',
          server: 'agent',
          args: {},
          why: '',
          sentence: `AINOPS check: no check showed ${strings(event.blamed).join(', ')}`,
          state: 'ok',
          summary:
            'The answer blamed it without proof, so the AI was sent back to check it on that device before answering.',
          data: null,
          evidence: null,
          health: null,
          device: null,
          durationMs: 0,
          atMs: event.at_ms,
          skillStep: null,
          turn,
        })
        break
      case 'refused':
        steps.push({
          kind: 'refused',
          key: `refused-${steps.length}`,
          evidenceId: null,
          tool: event.tool,
          server: '',
          args: event.args,
          why: event.why ?? '',
          sentence: describeCall(event.tool, event.args),
          state: 'error',
          summary: event.reason,
          data: null,
          evidence: null,
          health: null,
          device: resolve(deviceOf(event.args)),
          durationMs: 0,
          atMs: event.at_ms,
          skillStep: skill ? stepNumber(event.skill_step) : null,
          turn,
        })
        break
      case 'report':
        verdict = {
          report: event.report,
          confidence: event.confidence,
          reasons: event.confidence_reasons,
          toolCalls: event.tool_calls,
          skillsUsed: strings(event.skills_used),
          tokens: event.tokens ?? null,
          atMs: event.at_ms,
        }
        break
      case 'error':
      case 'stopped':
        error = event.type === 'stopped' ? 'You stopped AINOPS before it finished.' : event.message
        // A check that never came back is not running any more.
        for (const step of steps) {
          if (step.state === 'running') {
            step.state = 'error'
            step.summary = event.type === 'stopped' ? 'Did not finish: stopped.' : 'Did not finish.'
          }
        }
        break
      default:
        break
    }
  }

  const fault = blamed(verdict, steps, deviceNames)
  return {
    question,
    turn,
    steps,
    notes,
    verdict,
    error,
    now: nowOf(steps, verdict, error),
    skill,
    highlight: {
      path,
      states: deviceStates(steps),
      issues: deviceIssues(steps),
      faultDevices: fault.devices,
      faultInterfaces: fault.interfaces,
      faultEvidence:
        verdict?.report.outcome === 'diagnosed' ? verdict.report.root_cause_evidence : [],
      pings: pings(steps, path, pathEnds),
      caption: caption(steps),
    },
  }
}

function deviceSteps(steps: Step[]): Step[] {
  return steps.filter((s) => s.kind === 'tool' && s.server === 'network' && s.device)
}

/** A running trace shows on its start device when the source is a device name (not an IP). */
function traceStart(tool: string, args: Record<string, unknown>, canonical: Map<string, string>) {
  if (tool !== 'trace_route' || typeof args.source !== 'string') return null
  return canonical.get(args.source.toUpperCase()) ?? null
}

/** What one step tells about one device. A trace tells something about every hop it read. */
interface Mark {
  device: string
  state: Step['state']
  health: ToolHealth | null
}

const OK: ToolHealth = { status: 'ok', issues: [] }

function marks(steps: Step[]): Mark[] {
  const out: Mark[] = []
  for (const step of deviceSteps(steps)) {
    const trace = step.tool === 'trace_route' && step.state === 'ok' ? readTrace(step.data) : null
    if (!trace) {
      out.push({ device: step.device as string, state: step.state, health: step.health })
      continue
    }
    trace.hops.forEach((hop, index) => {
      if (index < trace.hops.length - 1) {
        out.push({ device: hop.device, state: 'ok', health: OK }) // it routed the traffic on
      } else if (trace.status === 'device_failed') {
        out.push({ device: hop.device, state: 'error', health: null })
      } else {
        out.push({ device: hop.device, state: 'ok', health: step.health }) // where the walk ended
      }
    })
  }
  return out
}

/** The device a step's problem is about: for a trace, where the route stops. */
function problemDevice(step: Step): string | null {
  if (step.tool === 'trace_route') return readTrace(step.data)?.stoppedAt ?? step.device
  return step.device
}

/** One state per device the agent touched; a problem found on it outweighs everything else. */
export function deviceStates(steps: Step[]): Map<string, DeviceState> {
  const byDevice = new Map<string, Mark[]>()
  for (const mark of marks(steps)) {
    byDevice.set(mark.device, [...(byDevice.get(mark.device) ?? []), mark])
  }
  const states = new Map<string, DeviceState>()
  for (const [device, list] of byDevice) {
    if (list.some((s) => s.state === 'running')) states.set(device, 'checking')
    else if (list.some((s) => s.health?.status === 'problem')) states.set(device, 'problem')
    else if (list.every((s) => s.state === 'error')) states.set(device, 'unreachable')
    else if (list.some((s) => s.health?.status === 'ok')) states.set(device, 'ok')
    else states.set(device, 'checked')
  }
  return states
}

function deviceIssues(steps: Step[]): Map<string, string[]> {
  const issues = new Map<string, string[]>()
  for (const { device, health } of marks(steps)) {
    if (health?.status !== 'problem') continue
    for (const issue of health.issues) {
      const list = issues.get(device) ?? []
      if (!list.includes(issue.text)) issues.set(device, [...list, issue.text])
    }
  }
  return issues
}

/**
 * What the diagnosis blames: the devices and interfaces named in the report, plus the problems
 * the code found in the evidence the root cause cites (so the map does not depend on wording).
 */
function blamed(verdict: Verdict | null, steps: Step[], deviceNames: string[]) {
  if (verdict?.report.outcome !== 'diagnosed') {
    return { devices: new Set<string>(), interfaces: new Set<string>() }
  }
  const { devices, interfaces } = parseAffected(verdict.report.affected, deviceNames)
  for (const id of verdict.report.root_cause_evidence) {
    const step = steps.find((s) => s.evidenceId === id)
    const device = step ? problemDevice(step) : null
    if (!step || !device || step.health?.status !== 'problem') continue
    devices.add(device)
    for (const issue of step.health.issues) {
      if (issue.interface) interfaces.add(`${device}:${shortInterface(issue.interface)}`)
    }
  }
  return { devices, interfaces }
}

/**
 * Pings, with the devices their packet travels along on the map. Only a ping towards an end of the
 * path the agent found travels along it; any other ping stays on its device (its way is unknown).
 */
function pings(steps: Step[], path: string[], pathEnds: [string, string]): MapPing[] {
  return steps
    .filter((s) => s.kind === 'tool' && s.tool === 'ping' && s.device)
    .map((step) => {
      const from = step.device as string
      const destination = String(step.args.destination ?? '')
      const index = path.indexOf(from)
      let route = [from]
      if (index >= 0 && destination === pathEnds[1]) route = path.slice(index)
      else if (index >= 0 && destination === pathEnds[0]) route = path.slice(0, index + 1).reverse()
      return {
        key: step.key,
        from,
        destination,
        route,
        ok: step.state === 'running' ? null : step.health?.status === 'ok',
        summary: step.summary,
      }
    })
}

function caption(steps: Step[]) {
  const running = [...deviceSteps(steps)].reverse().find((s) => s.state === 'running')
  return running ? { device: running.device as string, label: shortCall(running.tool) } : null
}

function nowOf(steps: Step[], verdict: Verdict | null, error: string | null): Now {
  if (verdict) return { kind: 'done', verdict }
  if (error) return { kind: 'stopped', message: error }
  const running = [...steps].reverse().find((s) => s.state === 'running')
  if (running) return { kind: 'working', step: running }
  return steps.length ? { kind: 'thinking', last: steps[steps.length - 1] } : { kind: 'starting' }
}

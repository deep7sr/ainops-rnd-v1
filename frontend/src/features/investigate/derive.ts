import type { Evidence, Report, RunEvent, ToolHealth } from '@/api'
import type { DeviceState, MapHighlight, MapPing } from '@/features/topology/highlight'
import { describeCall, shortCall } from './describe'

// Turns the raw event stream of an investigation into what the page shows: the steps of the
// timeline, the final report, and what to highlight on the map.

export interface Step {
  kind: 'tool' | 'refused'
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
}

export interface Verdict {
  report: Report
  confidence: 'high' | 'medium' | 'low'
  reasons: string[]
  toolCalls: number
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
  question: string | null
  steps: Step[]
  notes: string[]
  verdict: Verdict | null
  error: string | null
  now: Now
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
  const canonical = new Map(deviceNames.map((name) => [name.toUpperCase(), name]))
  // Events come from the server and from old recordings: anything but a device name is ignored.
  const resolve = (name: unknown) =>
    typeof name === 'string' && name ? (canonical.get(name.toUpperCase()) ?? name) : null

  for (const event of events) {
    switch (event.type) {
      case 'started':
        question = event.question
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
          device: resolve(deviceOf(event.args)),
          durationMs: null,
          atMs: event.at_ms,
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
        if (event.ok && event.tool === 'get_path') {
          const devices = (event.data as { devices?: unknown } | null)?.devices
          if (Array.isArray(devices)) {
            path = devices.map((d) => resolve(String(d)) ?? String(d))
            pathEnds = [String(step.args.source ?? ''), String(step.args.destination ?? '')]
          }
        }
        break
      }
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
        })
        break
      case 'report':
        verdict = {
          report: event.report,
          confidence: event.confidence,
          reasons: event.confidence_reasons,
          toolCalls: event.tool_calls,
          atMs: event.at_ms,
        }
        break
      case 'error':
        error = event.message
        break
      default:
        break
    }
  }

  const fault = blamed(verdict, steps, deviceNames)
  return {
    question,
    steps,
    notes,
    verdict,
    error,
    now: nowOf(steps, verdict, error),
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

/** One state per device the agent touched; a problem found on it outweighs everything else. */
export function deviceStates(steps: Step[]): Map<string, DeviceState> {
  const byDevice = new Map<string, Step[]>()
  for (const step of deviceSteps(steps)) {
    const device = step.device as string
    byDevice.set(device, [...(byDevice.get(device) ?? []), step])
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
  for (const step of deviceSteps(steps)) {
    if (step.health?.status !== 'problem') continue
    const device = step.device as string
    for (const issue of step.health.issues) {
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
    if (!step?.device || step.health?.status !== 'problem') continue
    devices.add(step.device)
    for (const issue of step.health.issues) {
      if (issue.interface) interfaces.add(`${step.device}:${shortInterface(issue.interface)}`)
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

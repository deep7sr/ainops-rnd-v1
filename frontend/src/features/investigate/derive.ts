import type { Evidence, Report, RunEvent } from '@/api'
import type { MapHighlight } from '@/features/topology/highlight'

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
  state: 'running' | 'ok' | 'error'
  summary: string
  data: unknown
  evidence: Evidence | null
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

export interface InvestigationView {
  question: string | null
  steps: Step[]
  notes: string[]
  verdict: Verdict | null
  error: string | null
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
  const canonical = new Map(deviceNames.map((name) => [name.toUpperCase(), name]))
  const resolve = (name: string | null) =>
    name ? (canonical.get(name.toUpperCase()) ?? name) : null

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
          state: 'running',
          summary: '',
          data: null,
          evidence: null,
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
        step.durationMs = event.duration_ms
        step.device = resolve(event.device) ?? step.device
        if (event.ok && event.tool === 'get_path') {
          const devices = (event.data as { devices?: unknown } | null)?.devices
          if (Array.isArray(devices)) path = devices.map((d) => resolve(String(d)) ?? String(d))
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
          state: 'error',
          summary: event.reason,
          data: null,
          evidence: null,
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

  const active = new Set<string>()
  const checked = new Map<string, 'ok' | 'error'>()
  for (const step of steps) {
    if (step.kind !== 'tool' || step.server !== 'network' || !step.device) continue
    if (step.state === 'running') active.add(step.device)
    else if (step.state === 'error') checked.set(step.device, 'error')
    else if (!checked.has(step.device)) checked.set(step.device, 'ok')
  }
  const fault =
    verdict?.report.outcome === 'diagnosed'
      ? parseAffected(verdict.report.affected, deviceNames)
      : { devices: new Set<string>(), interfaces: new Set<string>() }

  return {
    question,
    steps,
    notes,
    verdict,
    error,
    highlight: {
      path,
      active,
      checked,
      faultDevices: fault.devices,
      faultInterfaces: fault.interfaces,
    },
  }
}

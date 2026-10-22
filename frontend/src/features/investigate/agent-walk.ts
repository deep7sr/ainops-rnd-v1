// Where the agent is on the map and what its console shows, from the steps of the investigation
// (already paced, see director.ts). Only real steps: the agent goes to a device when it runs a
// command there, the console shows the command it ran and the lines the device answered.

import type { CommandCatalog } from '@/api'
import type { AgentConsole, AgentWalk } from '@/features/topology/highlight'
import { isSafetyBlock, type Step } from './derive'

/** The device a network step ran on, if it is one on the map. */
function deviceOfStep(step: Step, onMap: Map<string, string>): string | null {
  if (step.kind !== 'tool' || step.server !== 'network') return null
  const source = step.tool === 'trace_route' ? step.args.source : null
  const device = step.device ?? (typeof source === 'string' ? source : null)
  return device && onMap.has(device) ? device : null
}

const GAP = '…'

/** Output lines the console under the map has room for (plus its "…" gaps). */
const CONSOLE_LINES = 4

/**
 * At most `max` lines of an excerpt for the console on the map, chosen like the excerpt itself:
 * the lines that start a block (not indented) first, then the others, in their original order,
 * with "…" wherever lines were left out.
 */
export function consoleLines(lines: string[], max = 5): string[] {
  const real = lines.flatMap((line, i) => (line === GAP ? [] : [i]))
  const headings = real.filter((i) => !/^\s/.test(lines[i]))
  const details = real.filter((i) => /^\s/.test(lines[i]))
  const keep = [...headings, ...details].slice(0, max).sort((a, b) => a - b)
  const shown: string[] = []
  keep.forEach((index, k) => {
    if (index > (k === 0 ? 0 : keep[k - 1] + 1)) shown.push(GAP)
    shown.push(lines[index])
  })
  if (keep.length > 0 && keep[keep.length - 1] < lines.length - 1) shown.push(GAP)
  return shown
}

/** The devices on the map that a result names, in the order it first names them. */
export function devicesNamed(data: unknown, onMap: Iterable<string>): string[] {
  const text = JSON.stringify(data) ?? ''
  const at = (name: string) => {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return text.search(new RegExp(`(?<![\\w-])${escaped}(?![\\w-])`))
  }
  return [...onMap]
    .map((name) => ({ name, index: at(name) }))
    .filter(({ index }) => index >= 0)
    .sort((a, b) => a.index - b.index)
    .map(({ name }) => name)
}

/** Each device's ports from its latest interfaces check (rows with a name and a status). */
function portsOf(steps: Step[], onMap: Map<string, string>) {
  const ports = new Map<string, { name: string; status: string }[]>()
  for (const step of steps) {
    if (step.tool !== 'get_interfaces' || step.state !== 'ok' || !Array.isArray(step.data)) continue
    const device = deviceOfStep(step, onMap)
    if (!device) continue
    const rows = (step.data as unknown[]).flatMap((row) => {
      const r = row as { name?: unknown; status?: unknown }
      return typeof r.name === 'string' && typeof r.status === 'string'
        ? [{ name: r.name, status: r.status }]
        : []
    })
    ports.set(device, rows)
  }
  return ports
}

/** A catalog template with the call's arguments filled in, e.g. "ping {destination}". */
export function fillCommand(template: string, args: Record<string, unknown>): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const value = args[name]
    return typeof value === 'string' || typeof value === 'number' ? String(value) : whole
  })
}

/**
 * @param platforms each device on the map and its platform (e.g. "cisco_ios")
 * @param running whether the investigation is still going
 */
export function agentWalk(
  steps: Step[],
  running: boolean,
  platforms: Map<string, string>,
  catalog: CommandCatalog | undefined,
): AgentWalk {
  const trail: string[] = []
  let last: { step: Step; device: string } | null = null
  for (const step of steps) {
    const device = deviceOfStep(step, platforms)
    if (!device) continue
    if (trail[trail.length - 1] !== device) trail.push(device)
    last = { step, device }
  }
  const latest = steps[steps.length - 1]
  const mode = !running ? 'resting' : latest?.state === 'running' ? 'checking' : 'thinking'

  let console: AgentConsole | null = null
  if (running && last) {
    const { step, device } = last
    const template = catalog?.[platforms.get(device) ?? '']?.[step.tool]
    const problem = step.health?.status === 'problem' ? step.health.issues[0]?.text : undefined
    console = {
      key: step.key,
      device,
      command: step.evidence?.command ?? (template ? fillCommand(template, step.args) : ''),
      lines: consoleLines(step.evidence?.excerpt ?? [], CONSOLE_LINES),
      state:
        step.state === 'running'
          ? 'running'
          : step.failure === 'request'
            ? 'not_run'
            : step.state === 'error'
              ? 'error'
              : problem
                ? 'problem'
                : 'ok',
      verdict: step.failure === 'request' ? `Not sent: ${step.summary}` : (problem ?? step.summary),
    }
  }
  // One-off moments, only while the investigation runs and only for the latest step.
  const fresh = running && latest && latest.state !== 'running' ? latest : null
  const lookup =
    fresh?.kind === 'tool' && fresh.server === 'topology' && fresh.state === 'ok'
      ? { key: fresh.key, devices: devicesNamed(fresh.data, platforms.keys()) }
      : null
  // Only a safety rule raises the shield: a limit of the investigation (the check budget) is not
  // a block.
  const target = fresh?.device ?? fresh?.args.device
  const blocked =
    fresh && isSafetyBlock(fresh)
      ? {
          key: fresh.key,
          device: typeof target === 'string' && platforms.has(target) ? target : null,
          rule: fresh.rule === 'address' ? ('address' as const) : ('read_only' as const),
        }
      : null
  return {
    trail,
    at: last?.device ?? null,
    mode,
    console,
    lookup,
    blocked,
    ports: portsOf(steps, platforms),
  }
}

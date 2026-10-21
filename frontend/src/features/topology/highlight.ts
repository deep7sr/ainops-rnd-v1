// What the map highlights while an investigation runs (see network-map.tsx). Everything here comes
// from real events of the run: nothing moves or changes colour unless the agent did something.

/**
 * - checking:    a tool is running on the device right now
 * - ok:          checked, and the code-computed verdict says healthy
 * - problem:     a check found something wrong (see `issues`)
 * - unreachable: every check on it failed (no answer)
 * - checked:     checked with tools that only report facts (no verdict)
 */
export type DeviceState = 'checking' | 'ok' | 'problem' | 'unreachable' | 'checked'

export interface MapPing {
  key: string
  /** Device the ping is sent from. */
  from: string
  destination: string
  /** Devices the packet travels along on the map: the known path from `from` towards the target. */
  route: string[]
  /** null while the ping runs. */
  ok: boolean | null
  summary: string
}

export interface MapCaption {
  device: string
  /** Short label for inside the device box, e.g. "checking interfaces". */
  label: string
}

export interface MapHighlight {
  /** Devices on the path the agent is following, in order. */
  path: string[]
  /** What the agent knows about each device it touched. */
  states: Map<string, DeviceState>
  /** Problems found per device, as plain sentences. */
  issues: Map<string, string[]>
  /** Devices the diagnosis blames. */
  faultDevices: Set<string>
  /** Interfaces the diagnosis blames, as "DEVICE:Fa2/0". */
  faultInterfaces: Set<string>
  /** Evidence ids behind the root cause, shown on the blamed link. */
  faultEvidence: string[]
  pings: MapPing[]
  /** The device being checked right now, if any. */
  caption: MapCaption | null
}

/** The agent on the map (features/investigate/agent-walk.ts). */
export interface AgentConsole {
  /** The step it belongs to: a new step is a new console. */
  key: string
  device: string
  /** The command run on the device: the real one once the result is in, before that the one the
   *  reviewed catalog has for this tool and platform ('' when neither is known). */
  command: string
  /** The first lines the device answered (redacted; "…" where lines were left out). */
  lines: string[]
  state: 'running' | 'ok' | 'problem' | 'error'
  /** One line: the summary, the problem found, or why it failed. */
  verdict: string
}

export interface AgentWalk {
  /** The devices the agent ran commands on, in order (a device twice in a row counts once). */
  trail: string[]
  /** Where the agent is: the device of its latest command (null before the first). */
  at: string | null
  /** checking: a tool is running. thinking: the AI is deciding the next step. resting: done. */
  mode: 'checking' | 'thinking' | 'resting'
  console: AgentConsole | null
  /** The knowledge-graph answer that just came in, and the devices it names (in its order). */
  lookup: { key: string; devices: string[] } | null
  /** A command the safety check just blocked, and the device it was meant for (if on the map). */
  blocked: { key: string; device: string | null } | null
  /** Each device's ports from its latest interfaces check: up, down or admin-down. */
  ports: Map<string, { name: string; status: string }[]>
}

export const NO_HIGHLIGHT: MapHighlight = {
  path: [],
  states: new Map(),
  issues: new Map(),
  faultDevices: new Set(),
  faultInterfaces: new Set(),
  faultEvidence: [],
  pings: [],
  caption: null,
}

/** About 26 characters fit in a box; the full sentence is in the tooltip, Now line and panel. */
export function boxIssue(text: string): string {
  const shut = /^(\S+) is administratively down/.exec(text)
  if (shut) return `${shut[1]} shut (admin down)`
  const noRoute = /has no route to (\S+)$/.exec(text)
  if (noRoute) return `no route to ${noRoute[1]}`
  const down = /^(\S+) is down$/.exec(text)
  return down ? `${down[1]} down` : text
}

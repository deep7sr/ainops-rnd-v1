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

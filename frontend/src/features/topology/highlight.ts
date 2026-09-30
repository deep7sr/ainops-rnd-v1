// What the map highlights while an investigation runs (see network-map.tsx).

export interface MapHighlight {
  /** Devices on the path the agent is following, in order. */
  path: string[]
  /** Devices a tool is running on right now. */
  active: Set<string>
  /** Devices already checked, with whether every check on them succeeded. */
  checked: Map<string, 'ok' | 'error'>
  /** Devices the diagnosis blames. */
  faultDevices: Set<string>
  /** Interfaces the diagnosis blames, as "DEVICE:Fa2/0". */
  faultInterfaces: Set<string>
}

export const NO_HIGHLIGHT: MapHighlight = {
  path: [],
  active: new Set(),
  checked: new Map(),
  faultDevices: new Set(),
  faultInterfaces: new Set(),
}

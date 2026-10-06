// trace_route results: the routing tables followed hop by hop (see backend network/trace.py).
// Data comes from the server and from old recordings, so it is read defensively: anything that is
// not a well-formed trace gives null, never an exception.

export interface TraceRoute {
  prefix: string
  protocol: string
  nextHop: string
  interface: string
  distanceMetric: string
}

export interface TraceHop {
  device: string
  /** The route the device uses for the destination; null when it has none. */
  route: TraceRoute | null
  nextHopDevice: string | null
  equalPaths: number
  note: string | null
}

export type TraceStatus =
  'reached' | 'no_route' | 'loop' | 'left_network' | 'device_failed' | 'too_many_hops'

export interface Trace {
  status: TraceStatus
  destination: string
  stoppedAt: string
  startNote: string | null
  hops: TraceHop[]
}

const STATUSES: TraceStatus[] = [
  'reached',
  'no_route',
  'loop',
  'left_network',
  'device_failed',
  'too_many_hops',
]

type Loose = Record<string, unknown>

const isObject = (value: unknown): value is Loose =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
const text = (value: unknown): string => (typeof value === 'string' ? value : '')

function readRoute(value: unknown): TraceRoute | null {
  if (!isObject(value) || !text(value.prefix)) return null
  return {
    prefix: text(value.prefix),
    protocol: text(value.protocol),
    nextHop: text(value.next_hop),
    interface: text(value.interface),
    distanceMetric: text(value.distance_metric),
  }
}

export function readTrace(data: unknown): Trace | null {
  if (!isObject(data) || !Array.isArray(data.hops)) return null
  const status = STATUSES.find((s) => s === data.status)
  if (!status) return null
  const hops: TraceHop[] = []
  for (const hop of data.hops) {
    if (!isObject(hop) || !text(hop.device)) return null
    hops.push({
      device: text(hop.device),
      route: readRoute(hop.route),
      nextHopDevice: text(hop.next_hop_device) || null,
      equalPaths: typeof hop.equal_paths === 'number' ? hop.equal_paths : 0,
      note: text(hop.note) || null,
    })
  }
  if (hops.length === 0) return null
  return {
    status,
    destination: text(data.destination),
    stoppedAt: text(data.stopped_at) || hops[hops.length - 1].device,
    startNote: text(data.start_note) || null,
    hops,
  }
}

/** Where a route came from, in words an engineer new to routing can follow. */
export function routeSource(protocol: string): string {
  const p = protocol.toLowerCase()
  if (p === 'connected' || p === 'direct') return 'directly connected'
  if (p === 'local') return 'this device itself'
  if (p === 'static') return 'static route (set by hand)'
  if (p.startsWith('ospf')) return 'learned from OSPF'
  if (p === 'bgp') return 'learned from BGP'
  if (p === 'eigrp') return 'learned from EIGRP'
  if (p === 'rip') return 'learned from RIP'
  return protocol || 'unknown source'
}

/** Cisco "110/13" -> "distance 110, metric 13"; Junos "10" -> "preference 10". */
export function distanceText(value: string): string {
  const [distance, metric] = value.split('/')
  if (!distance) return ''
  return metric !== undefined ? `distance ${distance}, metric ${metric}` : `preference ${distance}`
}

/** One line on how the walk ended, for the end of the hop list. */
export function endText(trace: Trace): string {
  switch (trace.status) {
    case 'reached':
      return `Arrived: ${trace.destination} is on ${trace.stoppedAt}'s own network`
    case 'no_route':
      return `${trace.stoppedAt} has no route to ${trace.destination}: traffic stops here`
    case 'loop':
      return `Routing loop: ${trace.stoppedAt} sends the traffic back the way it came`
    case 'left_network':
      return `Traffic leaves the devices AINOPS knows at ${trace.stoppedAt}`
    case 'device_failed':
      return `${trace.stoppedAt} did not answer: the trace could not continue`
    case 'too_many_hops':
      return 'Stopped after too many hops without arriving'
  }
}

/** The devices whose routing table a trace step read (none for any other step). */
export function hopsOf(step: { tool: string; data: unknown }): string[] {
  if (step.tool !== 'trace_route') return []
  return readTrace(step.data)?.hops.map((hop) => hop.device) ?? []
}

// The stops of the path strip under the map (path-strip.tsx): the path the agent found, with the
// source and destination LANs of the question at its ends.

import type { EndpointTag, LanEndpoint } from '@/features/topology/lan'

export interface Stop {
  name: string
  /** The role for its picture ("lan" for a LAN). */
  role: string
  lan: boolean
}

/** The stops: the path, with the source and destination LANs of the question at its ends. */
export function pathStops(
  path: string[],
  lans: LanEndpoint[],
  tags: Map<string, EndpointTag>,
  roles: Map<string, string>,
): Stop[] {
  if (path.length < 2) return []
  const end = (tag: EndpointTag, device: string) =>
    lans
      .filter((lan) => lan.device === device && tags.get(lan.key) === tag)
      .map((lan) => ({ name: lan.name, role: 'lan', lan: true }))
  return [
    ...end('source', path[0]),
    ...path.map((name) => ({ name, role: roles.get(name) ?? '', lan: false })),
    ...end('destination', path[path.length - 1]),
  ]
}

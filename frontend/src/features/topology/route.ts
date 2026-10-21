import type { GraphLink } from '@/api'

/**
 * The devices from `from` to `to` along the links (fewest hops), for the agent marker to travel.
 * Just the two when the map knows no way between them (the marker then flies straight).
 */
export function routeBetween(from: string, to: string, links: GraphLink[]): string[] {
  if (from === to) return [to]
  const next = new Map<string, string[]>()
  for (const link of links) {
    next.set(link.a, [...(next.get(link.a) ?? []), link.b])
    next.set(link.b, [...(next.get(link.b) ?? []), link.a])
  }
  const cameFrom = new Map<string, string>([[from, from]])
  const queue = [from]
  while (queue.length > 0 && !cameFrom.has(to)) {
    const here = queue.shift() as string
    for (const neighbour of next.get(here) ?? []) {
      if (!cameFrom.has(neighbour)) {
        cameFrom.set(neighbour, here)
        queue.push(neighbour)
      }
    }
  }
  if (!cameFrom.has(to)) return [from, to]
  const route = [to]
  while (route[0] !== from) route.unshift(cameFrom.get(route[0]) as string)
  return route
}

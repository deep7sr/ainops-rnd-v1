// The user LANs at the edge of the map: addressed ports on core switches that no link uses, where
// the users' hosts are. Questions are often about them ("the TRV LAN cannot reach MAA"), so the
// investigation map draws them as the end points of the network, from the graph (a LAN discovery
// finds tomorrow shows up by itself).

import type { GraphDevice, GraphLink } from '@/api'

export interface LanEndpoint {
  /** "DEVICE:interface". */
  key: string
  /** "TRV LAN" (a second LAN at the same site: "TRV LAN 2"). */
  name: string
  device: string
  interface: string
  /** The LAN's network, e.g. "192.168.100.0/24". */
  subnet: string
}

/** Roles whose free ports face users (an ISP router's free port faces the Internet). */
const LAN_ROLES = ['core', 'distribution', 'access']

function toNumber(ip: string): number | null {
  const parts = ip.split('.')
  if (parts.length !== 4) return null
  let value = 0
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part) || Number(part) > 255) return null
    value = value * 256 + Number(part)
  }
  return value
}

const toText = (n: number) =>
  [24, 16, 8, 0].map((shift) => Math.floor(n / 2 ** shift) % 256).join('.')

/** "192.168.100.1/24" -> its network: start, size, and "192.168.100.0/24". */
function network(cidr: string): { start: number; size: number; text: string } | null {
  const [ip, bits] = cidr.split('/')
  const address = toNumber(ip)
  const prefix = Number(bits)
  if (address === null || !Number.isInteger(prefix) || prefix < 0 || prefix > 32) return null
  const size = 2 ** (32 - prefix)
  const start = Math.floor(address / size) * size
  return { start, size, text: `${toText(start)}/${prefix}` }
}

export function lanEndpoints(devices: GraphDevice[], links: GraphLink[]): LanEndpoint[] {
  const linked = new Set(
    links.flatMap((l) => [`${l.a}:${l.a_interface}`, `${l.b}:${l.b_interface}`]),
  )
  const lans: LanEndpoint[] = []
  const perSite = new Map<string, number>()
  for (const device of devices) {
    if (!LAN_ROLES.some((role) => device.role.toLowerCase().startsWith(role))) continue
    for (const iface of device.interfaces) {
      const key = `${device.name}:${iface.name}`
      const net = iface.ipv4.length ? network(iface.ipv4[0]) : null
      // A /31 or /32 is a point-to-point link or a loopback, not a LAN.
      if (linked.has(key) || !net || net.size < 4) continue
      const count = (perSite.get(device.site) ?? 0) + 1
      perSite.set(device.site, count)
      lans.push({
        key,
        name: `${device.site} LAN${count > 1 ? ` ${count}` : ''}`,
        device: device.name,
        interface: iface.name,
        subnet: net.text,
      })
    }
  }
  return lans
}

/** Whether an address ("192.168.100.10") or a network ("192.168.100.0/24") is inside a subnet. */
export function inSubnet(address: string, subnet: string): boolean {
  const net = network(subnet)
  const [ip] = address.split('/')
  const value = toNumber(ip)
  return net !== null && value !== null && value >= net.start && value < net.start + net.size
}

/**
 * source / destination: the LAN is named in the question and hangs off the first / last device
 * of the path the agent found. question: named in the question, the path does not say which end
 * it is (yet).
 */
export type EndpointTag = 'source' | 'destination' | 'question'

export function endpointTags(
  lans: LanEndpoint[],
  path: string[],
  question: string,
): Map<string, EndpointTag> {
  const addresses = question.match(/\b\d{1,3}(?:\.\d{1,3}){3}(?:\/\d{1,2})?\b/g) ?? []
  const tags = new Map<string, EndpointTag>()
  for (const lan of lans) {
    if (!addresses.some((address) => inSubnet(address, lan.subnet))) continue
    const ends = path.length >= 2
    tags.set(
      lan.key,
      ends && lan.device === path[0]
        ? 'source'
        : ends && lan.device === path[path.length - 1]
          ? 'destination'
          : 'question',
    )
  }
  return tags
}

import type { GraphDevice, GraphLink } from '@/api'

// Positions for the map, worked out from the graph (site + role), not drawn by hand: a device that
// discovery adds tomorrow gets a place automatically.

export const VIEW_WIDTH = 1000
export const VIEW_HEIGHT = 560
export const NODE_WIDTH = 176
export const NODE_HEIGHT = 58

const SITE_ORDER = ['TRV', 'MAA']
export const SITE_NAMES: Record<string, string> = { TRV: 'Trivandrum', MAA: 'Chennai' }

// Top to bottom inside a site: the Internet edge, the firewall, the core, then the WAN router.
const ROLE_ROWS: Record<string, number> = {
  'isp-router': 0,
  firewall: 1,
  core: 2,
  'wan-router': 3,
}
const ROW_Y = [118, 232, 346, 460]

export interface Point {
  x: number
  y: number
}

export function siteOrder(devices: GraphDevice[]): string[] {
  const sites = [...new Set(devices.map((d) => d.site))]
  return sites.sort((a, b) => {
    const ia = SITE_ORDER.indexOf(a)
    const ib = SITE_ORDER.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b)
  })
}

/** Centre point of every device box. */
export function layoutDevices(devices: GraphDevice[]): Map<string, Point> {
  const sites = siteOrder(devices)
  const positions = new Map<string, Point>()
  const columnWidth = VIEW_WIDTH / Math.max(sites.length, 1)
  sites.forEach((site, siteIndex) => {
    const centre = columnWidth * siteIndex + columnWidth / 2
    // With two sites, WAN routers move towards the middle, where the link between the sites is.
    const inward = sites.length === 2 ? (siteIndex === 0 ? 1 : -1) : 0
    const used = new Map<number, number>()
    for (const device of devices.filter((d) => d.site === site)) {
      const row = ROLE_ROWS[device.role] ?? 3
      const count = used.get(row) ?? 0
      used.set(row, count + 1)
      const shift = row === 3 ? inward * 70 : 0
      const spread = count === 0 ? 0 : (count % 2 === 1 ? 1 : -1) * Math.ceil(count / 2) * 200
      positions.set(device.name, {
        x: centre + shift + spread,
        y: row in ROW_Y ? ROW_Y[row] : ROW_Y[3] + 100 * (row - 3),
      })
    }
  })
  return positions
}

/** Where a line from one box to another should stop: on the edge, not the centre. */
export function edgePoint(from: Point, to: Point, pad = 4): Point {
  const dx = to.x - from.x
  const dy = to.y - from.y
  if (dx === 0 && dy === 0) return from
  const halfW = NODE_WIDTH / 2 + pad
  const halfH = NODE_HEIGHT / 2 + pad
  const scale = Math.min(
    dx === 0 ? Infinity : halfW / Math.abs(dx),
    dy === 0 ? Infinity : halfH / Math.abs(dy),
  )
  return { x: from.x + dx * scale, y: from.y + dy * scale }
}

export function linkIsDown(link: GraphLink): boolean {
  return [link.a_status, link.b_status].some((s) => s !== null && s !== 'up')
}

/** Addressed interfaces that are not part of any link: LANs, uplinks, or mis-addressed links. */
export function edgeInterfaces(devices: GraphDevice[], links: GraphLink[]) {
  const linked = new Set(
    links.flatMap((l) => [`${l.a}:${l.a_interface}`, `${l.b}:${l.b_interface}`]),
  )
  return devices.flatMap((device) =>
    device.interfaces
      .filter((i) => i.ipv4.length > 0 && !linked.has(`${device.name}:${i.name}`))
      .map((i) => ({ device: device.name, ...i })),
  )
}

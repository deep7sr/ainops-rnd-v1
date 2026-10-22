import type { GraphDevice, GraphLink } from '@/api'
import type { LanEndpoint } from './lan'

// Positions for the map, worked out from the graph (site + role), not drawn by hand: a device that
// discovery adds tomorrow gets a place automatically.

export const VIEW_WIDTH = 1000
export const VIEW_HEIGHT = 560
/** Side of a device's tile: the rounded square with its picture, centred on its position. */
export const TILE = 58
/** The room a device takes: its tile, and under it its name and one line. */
export const NODE_WIDTH = 150
export const NODE_TOP = TILE / 2 + 4
export const NODE_BOTTOM = 66
export const NODE_HEIGHT = NODE_TOP + NODE_BOTTOM

const SITE_ORDER = ['TRV', 'MAA']
export const SITE_NAMES: Record<string, string> = { TRV: 'Trivandrum', MAA: 'Chennai' }

// Top to bottom inside a site: the Internet edge, the firewall, the core, then the WAN router.
const ROLE_ROWS: Record<string, number> = {
  'isp-router': 0,
  firewall: 1,
  core: 2,
  'wan-router': 3,
}
const ROW_Y = [88, 204, 320, 470]

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

/** Centre point of every device tile. */
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
      const shift = row === 3 ? inward * 100 : 0
      const spread = count === 0 ? 0 : (count % 2 === 1 ? 1 : -1) * Math.ceil(count / 2) * 200
      positions.set(device.name, {
        x: centre + shift + spread,
        y: row in ROW_Y ? ROW_Y[row] : ROW_Y[3] + 100 * (row - 3),
      })
    }
  })
  return positions
}

/** Where a line from one tile to another should stop: just outside the tile, not the centre. */
export function edgePoint(from: Point, to: Point, pad = 6): Point {
  const dx = to.x - from.x
  const dy = to.y - from.y
  if (dx === 0 && dy === 0) return from
  const half = TILE / 2 + pad
  const scale = Math.min(
    dx === 0 ? Infinity : half / Math.abs(dx),
    dy === 0 ? Infinity : half / Math.abs(dy),
  )
  return { x: from.x + dx * scale, y: from.y + dy * scale }
}

/**
 * Where along a link (0 = at a, 1 = at b) its subnet label goes: in the middle of a level link;
 * on a link that climbs, in the gap between the upper device's name and the lower device's tile
 * (the middle would sit on the upper device's name).
 */
export function labelAt(a: Point, b: Point): number {
  const dy = b.y - a.y
  if (Math.abs(dy) < 40) return 0.5
  const [upper, lower] = dy > 0 ? [a, b] : [b, a]
  const y = (upper.y + NODE_BOTTOM + lower.y - TILE / 2) / 2
  const t = Math.min(0.85, Math.max(0.15, (y - upper.y) / Math.abs(dy)))
  return dy > 0 ? t : 1 - t
}

/** Where each LAN end point sits: beside its core switch, towards the outside of the map. */
export function layoutLans(
  lans: LanEndpoint[],
  devices: GraphDevice[],
  positions: Map<string, Point>,
): Map<string, Point> {
  const sites = siteOrder(devices)
  const columnWidth = VIEW_WIDTH / Math.max(sites.length, 1)
  const out = new Map<string, Point>()
  const used = new Map<string, number>()
  for (const lan of lans) {
    const at = positions.get(lan.device)
    const site = devices.find((d) => d.name === lan.device)?.site
    if (!at || site === undefined) continue
    const index = sites.indexOf(site)
    const outward = index === sites.length - 1 && sites.length > 1 ? 1 : -1
    const count = used.get(lan.device) ?? 0
    used.set(lan.device, count + 1)
    out.set(lan.key, {
      x: columnWidth * index + columnWidth / 2 + outward * 168,
      y: at.y + count * 126,
    })
  }
  return out
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

/** A part of the map: what the camera shows. */
export interface View {
  x: number
  y: number
  width: number
  height: number
}

/**
 * The part of `whole` that frames these points (device centres) with room around their boxes, in the
 * same proportions as `whole` (so the map keeps its height) and never outside it. No points: whole.
 */
export function frameView(whole: View, points: Point[]): View {
  if (points.length === 0) return whole
  const xs = points.map((p) => p.x)
  const ys = points.map((p) => p.y)
  let x = Math.min(...xs) - NODE_WIDTH / 2 - 40
  let y = Math.min(...ys) - NODE_TOP - 60
  let width = Math.max(...xs) - Math.min(...xs) + NODE_WIDTH + 80
  let height = Math.max(...ys) - Math.min(...ys) + NODE_HEIGHT + 120
  // Never closer than 60% of the whole: the neighbours stay in view, so the fault keeps its place.
  const least = whole.width * 0.6
  if (width < least) {
    x -= (least - width) / 2
    width = least
  }
  const aspect = whole.width / whole.height
  if (width / height < aspect) {
    x -= (height * aspect - width) / 2
    width = height * aspect
  } else {
    y -= (width / aspect - height) / 2
    height = width / aspect
  }
  if (width >= whole.width) return whole
  x = Math.min(Math.max(x, whole.x), whole.x + whole.width - width)
  y = Math.min(Math.max(y, whole.y), whole.y + whole.height - height)
  return { x, y, width, height }
}

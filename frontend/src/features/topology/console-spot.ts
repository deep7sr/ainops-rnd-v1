// Where the agent's console opens on the map: next to the device it runs a command on, like a
// terminal popping out of it, but never over a device that matters. On 2026-10-22 a console docked
// over the map hid ISP-TRV-1 and the site name; this picks a spot that covers only devices the
// investigation has not touched (they are faded), and says when there is none (the console then
// goes under the map).

import type { MapHighlight } from './highlight'
import type { EndpointTag } from './lan'
import { NODE_BOTTOM, NODE_TOP, NODE_WIDTH, TILE, type Point, type View } from './layout'

export interface Box {
  x: number
  y: number
  width: number
  height: number
}

const MARGIN = 8
/** Room above the device being checked: the agent's orb sits on its tile. */
const ORB_ROOM = 24

function overlaps(a: Box, b: Box): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
}

/** The room a device takes on the map (its tile, name and line). */
export function footprint(at: Point, extraTop = 0): Box {
  return {
    x: at.x - NODE_WIDTH / 2,
    y: at.y - NODE_TOP - extraTop,
    width: NODE_WIDTH,
    height: NODE_TOP + NODE_BOTTOM + extraTop,
  }
}

/**
 * What the console must not cover: the device it belongs to (and the orb on it), every device on
 * the path, checked or blamed, and the LANs the question names.
 */
export function keepClear(
  current: string,
  positions: Map<string, Point>,
  highlight: MapHighlight,
  lanAt: Map<string, Point>,
  lanTags: Map<string, EndpointTag>,
): Box[] {
  const boxes: Box[] = []
  for (const [name, at] of positions) {
    if (name === current) boxes.push(footprint(at, ORB_ROOM))
    else if (
      highlight.path.includes(name) ||
      highlight.states.has(name) ||
      highlight.faultDevices.has(name)
    ) {
      boxes.push(footprint(at))
    }
  }
  for (const [key, at] of lanAt) {
    if (lanTags.has(key)) boxes.push(footprint(at, 20)) // and its tag above it
  }
  return boxes
}

/**
 * The first free spot for a console of `size` (map units) for the device at `at`: beside the
 * device first (above it, then to its sides, then below), then the corners of the view. null:
 * none is free.
 */
export function consoleSpot(
  at: Point,
  size: { width: number; height: number },
  view: View,
  keep: Box[],
): Box | null {
  const { width, height } = size
  const gap = 12
  const above = at.y - TILE / 2 - ORB_ROOM - gap - height
  const below = at.y + NODE_BOTTOM + gap
  const right = at.x + NODE_WIDTH / 2 + gap
  const left = at.x - NODE_WIDTH / 2 - gap - width
  const middle = at.y - height / 2
  const [x0, y0] = [view.x + MARGIN, view.y + MARGIN]
  const [x1, y1] = [view.x + view.width - MARGIN - width, view.y + view.height - MARGIN - height]
  // The corners of the view, the nearest to the device first.
  const corners: [number, number][] = [
    [x0, y0],
    [x1, y0],
    [x0, y1],
    [x1, y1],
  ]
  const distance = ([cx, cy]: [number, number]) =>
    Math.hypot(cx + width / 2 - at.x, cy + height / 2 - at.y)
  corners.sort((a, b) => distance(a) - distance(b))
  const candidates: [number, number][] = [
    [at.x - 40, above], // above, opening to the right
    [at.x + 40 - width, above], // above, opening to the left
    [at.x - width / 2, above],
    [right, middle],
    [left, middle],
    [at.x - 40, below],
    [at.x + 40 - width, below],
    ...corners,
  ]
  for (const [cx, cy] of candidates) {
    // Inside the view: a spot partly outside slides in (and must still be free there).
    const box = {
      x: Math.min(Math.max(cx, x0), x1),
      y: Math.min(Math.max(cy, y0), y1),
      width,
      height,
    }
    if (x1 < x0 || y1 < y0) return null // the console is bigger than the view
    if (!keep.some((k) => overlaps(box, k))) return box
  }
  return null
}

/** The point of a box nearest to a point: where the leader line to the device ends. */
export function nearestPoint(box: Box, p: Point): Point {
  return {
    x: Math.min(Math.max(p.x, box.x), box.x + box.width),
    y: Math.min(Math.max(p.y, box.y), box.y + box.height),
  }
}

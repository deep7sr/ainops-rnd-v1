import { describe, expect, it } from 'vitest'
import type { GraphDevice } from '@/api'
import { consoleSpot, footprint, keepClear, nearestPoint, type Box } from './console-spot'
import { NO_HIGHLIGHT, type MapHighlight } from './highlight'
import { layoutDevices, layoutLans } from './layout'

const device = (name: string, site: string, role: string): GraphDevice => ({
  name,
  site,
  role,
  platform: 'cisco_ios',
  description: '',
  interfaces: [],
})
// The lab, laid out as on the investigation map.
const DEVICES = [
  device('ISP-TRV-1', 'TRV', 'isp-router'),
  device('FWL-TRV', 'TRV', 'firewall'),
  device('CORE-SW-TRV', 'TRV', 'core'),
  device('IPLC-RTR-TRV', 'TRV', 'wan-router'),
  device('IPLC-RTR-MAA', 'MAA', 'wan-router'),
  device('CORE-SW-MAA', 'MAA', 'core'),
  device('FWL-MAA', 'MAA', 'firewall'),
  device('ISP-MAA-1', 'MAA', 'isp-router'),
]
const positions = layoutDevices(DEVICES)
const at = (name: string) => positions.get(name)!
const lans = [
  { key: 'trv', name: 'TRV LAN', device: 'CORE-SW-TRV', interface: 'E1/0', subnet: '' },
  { key: 'maa', name: 'MAA LAN', device: 'CORE-SW-MAA', interface: 'E1/0', subnet: '' },
]
const lanAt = layoutLans(lans, DEVICES, positions)
const tags = new Map([
  ['trv', 'source' as const],
  ['maa', 'destination' as const],
])
const VIEW = { x: 0, y: 0, width: 1000, height: 560 }
// A 300 x 184 px console on a map drawn about 830 px wide.
const SIZE = { width: 361, height: 221 }
const fault1: MapHighlight = {
  ...NO_HIGHLIGHT,
  path: ['CORE-SW-TRV', 'IPLC-RTR-TRV', 'IPLC-RTR-MAA', 'CORE-SW-MAA'],
  states: new Map([['CORE-SW-TRV', 'ok' as const]]),
}

const overlaps = (a: Box, b: Box) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height

describe('where the console opens', () => {
  it('above the device, over the faded devices only', () => {
    const keep = keepClear('CORE-SW-TRV', positions, fault1, lanAt, tags)
    const spot = consoleSpot(at('CORE-SW-TRV'), SIZE, VIEW, keep)!
    expect(spot.y + spot.height).toBeLessThan(at('CORE-SW-TRV').y)
    expect(spot.x).toBe(at('CORE-SW-TRV').x - 40) // opening to the right of the device
    expect(keep.some((k) => overlaps(spot, k))).toBe(false)
  })

  it('never over a device on the path: a router low on the map gets a free corner', () => {
    const keep = keepClear('IPLC-RTR-TRV', positions, fault1, lanAt, tags)
    const spot = consoleSpot(at('IPLC-RTR-TRV'), SIZE, VIEW, keep)!
    expect(spot).not.toBeNull()
    expect(keep.some((k) => overlaps(spot, k))).toBe(false)
    // Every device on the path and both LANs stay in view.
    for (const name of fault1.path) expect(overlaps(spot, footprint(at(name)))).toBe(false)
    // The corner nearest the device: TRV is on the left.
    expect(spot.x).toBe(8)
  })

  it('a device on the MAA side gets the corner on its side', () => {
    const keep = keepClear('IPLC-RTR-MAA', positions, fault1, lanAt, tags)
    const spot = consoleSpot(at('IPLC-RTR-MAA'), SIZE, VIEW, keep)!
    expect(spot.x + spot.width).toBe(992)
    expect(spot.y).toBe(8)
  })

  it('never over its own device or the orb on it', () => {
    const keep = keepClear('ISP-TRV-1', positions, NO_HIGHLIGHT, new Map(), new Map())
    const spot = consoleSpot(at('ISP-TRV-1'), SIZE, VIEW, keep)!
    expect(overlaps(spot, footprint(at('ISP-TRV-1'), 24))).toBe(false)
  })

  it('stays inside the map', () => {
    const keep = keepClear('ISP-MAA-1', positions, NO_HIGHLIGHT, new Map(), new Map())
    const spot = consoleSpot(at('ISP-MAA-1'), SIZE, VIEW, keep)!
    expect(spot.x).toBeGreaterThanOrEqual(8)
    expect(spot.y).toBeGreaterThanOrEqual(8)
    expect(spot.x + spot.width).toBeLessThanOrEqual(992)
    expect(spot.y + spot.height).toBeLessThanOrEqual(552)
  })

  it('says so when no spot is free (it then goes under the map)', () => {
    const everything: MapHighlight = { ...NO_HIGHLIGHT, path: DEVICES.map((d) => d.name) }
    const keep = keepClear('IPLC-RTR-TRV', positions, everything, lanAt, tags)
    expect(consoleSpot(at('IPLC-RTR-TRV'), SIZE, VIEW, keep)).toBeNull()
    expect(consoleSpot(at('IPLC-RTR-TRV'), { width: 1200, height: 100 }, VIEW, [])).toBeNull()
  })
})

describe('what the console keeps clear', () => {
  it('the devices that matter and the LANs of the question, not the faded ones', () => {
    const keep = keepClear('CORE-SW-TRV', positions, fault1, lanAt, new Map([['trv', 'source']]))
    expect(keep).toHaveLength(4 + 1) // the path, and the TRV LAN
    expect(keep).toContainEqual(footprint(at('CORE-SW-TRV'), 24))
    expect(keep).not.toContainEqual(footprint(at('ISP-TRV-1')))
  })

  it('a blamed device and a checked device off the path too', () => {
    const highlight: MapHighlight = {
      ...NO_HIGHLIGHT,
      states: new Map([['FWL-MAA', 'ok' as const]]),
      faultDevices: new Set(['ISP-MAA-1']),
    }
    const keep = keepClear('CORE-SW-TRV', positions, highlight, new Map(), new Map())
    expect(keep).toContainEqual(footprint(at('FWL-MAA')))
    expect(keep).toContainEqual(footprint(at('ISP-MAA-1')))
  })
})

it('the leader line ends on the edge of the console nearest the device', () => {
  const box = { x: 100, y: 100, width: 200, height: 100 }
  expect(nearestPoint(box, { x: 50, y: 150 })).toEqual({ x: 100, y: 150 })
  expect(nearestPoint(box, { x: 400, y: 300 })).toEqual({ x: 300, y: 200 })
})

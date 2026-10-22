import { describe, expect, it } from 'vitest'
import type { GraphDevice } from '@/api'
import { edgePoint, labelAt, layoutDevices, layoutLans, NODE_BOTTOM, TILE } from './layout'
import type { LanEndpoint } from './lan'

const device = (name: string, site: string, role: string): GraphDevice => ({
  name,
  site,
  role,
  platform: 'cisco_ios',
  description: '',
  interfaces: [],
})
const DEVICES = [
  device('CORE-SW-TRV', 'TRV', 'core'),
  device('IPLC-RTR-TRV', 'TRV', 'wan-router'),
  device('IPLC-RTR-MAA', 'MAA', 'wan-router'),
  device('CORE-SW-MAA', 'MAA', 'core'),
]
const lan = (key: string, d: string): LanEndpoint => ({
  key,
  name: 'LAN',
  device: d,
  interface: 'E1/0',
  subnet: '192.168.0.0/24',
})

describe('the map layout', () => {
  it('a link stops just outside the tiles', () => {
    expect(edgePoint({ x: 0, y: 0 }, { x: 300, y: 0 })).toEqual({ x: TILE / 2 + 6, y: 0 })
    expect(edgePoint({ x: 0, y: 0 }, { x: 0, y: -200 })).toEqual({ x: 0, y: -(TILE / 2 + 6) })
  })

  it("a level link's label sits in the middle", () => {
    expect(labelAt({ x: 0, y: 470 }, { x: 300, y: 470 })).toBe(0.5)
  })

  it("a climbing link's label sits under the upper device's name, above the lower tile", () => {
    const upper = { x: 250, y: 320 }
    const lower = { x: 350, y: 470 }
    const t = labelAt(upper, lower)
    const y = upper.y + (lower.y - upper.y) * t
    expect(y).toBeGreaterThan(upper.y + NODE_BOTTOM)
    expect(y).toBeLessThan(lower.y - TILE / 2)
    expect(labelAt(lower, upper)).toBeCloseTo(1 - t, 10) // the same place, from the other end
  })

  it('the label stays on the link, however short the climb', () => {
    expect(labelAt({ x: 0, y: 0 }, { x: 10, y: 45 })).toBe(0.85)
  })

  it('a LAN sits beside its core switch, towards the outside of the map', () => {
    const positions = layoutDevices(DEVICES)
    const lans = layoutLans(
      [lan('trv', 'CORE-SW-TRV'), lan('maa', 'CORE-SW-MAA'), lan('trv2', 'CORE-SW-TRV')],
      DEVICES,
      positions,
    )
    const core = (name: string) => positions.get(name)!
    expect(lans.get('trv')).toEqual({ x: 82, y: core('CORE-SW-TRV').y })
    expect(lans.get('maa')).toEqual({ x: 918, y: core('CORE-SW-MAA').y })
    expect(lans.get('trv2')).toEqual({ x: 82, y: core('CORE-SW-TRV').y + 126 }) // under the first
  })

  it('a LAN of a device that is not on the map is left out', () => {
    expect(layoutLans([lan('x', 'GONE')], DEVICES, layoutDevices(DEVICES)).size).toBe(0)
  })
})

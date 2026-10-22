import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { DeviceState } from '@/features/topology/highlight'
import type { EndpointTag, LanEndpoint } from '@/features/topology/lan'
import { pathStops } from './path-stops'
import { PathStrip } from './path-strip'

const PATH = ['CORE-SW-TRV', 'IPLC-RTR-TRV', 'IPLC-RTR-MAA', 'CORE-SW-MAA']
const lan = (key: string, name: string, device: string): LanEndpoint => ({
  key,
  name,
  device,
  interface: 'E1/0',
  subnet: '',
})
const LANS = [lan('trv', 'TRV LAN', 'CORE-SW-TRV'), lan('maa', 'MAA LAN', 'CORE-SW-MAA')]
const ROLES = new Map([
  ['CORE-SW-TRV', 'core'],
  ['IPLC-RTR-TRV', 'wan-router'],
])
const names = (stops: { name: string }[]) => stops.map((s) => s.name)

describe('the stops of the path', () => {
  it('runs from the source LAN to the destination LAN', () => {
    const tags = new Map<string, EndpointTag>([
      ['trv', 'source'],
      ['maa', 'destination'],
    ])
    const stops = pathStops(PATH, LANS, tags, ROLES)
    expect(names(stops)).toEqual(['TRV LAN', ...PATH, 'MAA LAN'])
    expect(stops[0]).toEqual({ name: 'TRV LAN', role: 'lan', lan: true })
    expect(stops[1]).toEqual({ name: 'CORE-SW-TRV', role: 'core', lan: false })
  })

  it('a LAN joins only at its own end, and only once the path says which end it is', () => {
    const question = new Map<string, EndpointTag>([
      ['trv', 'question'],
      ['maa', 'question'],
    ])
    expect(names(pathStops(PATH, LANS, question, ROLES))).toEqual(PATH)
    // Tagged the wrong way round for this path: neither end matches.
    const swapped = new Map<string, EndpointTag>([
      ['trv', 'destination'],
      ['maa', 'source'],
    ])
    expect(names(pathStops(PATH, LANS, swapped, ROLES))).toEqual(PATH)
  })

  it('no path yet, no strip', () => {
    expect(pathStops([], LANS, new Map(), ROLES)).toEqual([])
    expect(pathStops(['CORE-SW-TRV'], LANS, new Map(), ROLES)).toEqual([])
  })
})

describe('the path strip', () => {
  const stops = pathStops(PATH, LANS, new Map([['trv', 'source' as const]]), ROLES)

  it('counts the hops and says what was found at each stop', () => {
    const states = new Map<string, DeviceState>([
      ['CORE-SW-TRV', 'ok'],
      ['IPLC-RTR-TRV', 'checking'],
    ])
    render(<PathStrip stops={stops} states={states} faults={new Set(['IPLC-RTR-MAA'])} />)
    expect(screen.getByText('Path · 4 hops')).toBeInTheDocument()
    const list = screen.getByRole('list', { name: 'The path, hop by hop' })
    expect([...list.querySelectorAll('li')].map((li) => li.textContent)).toEqual([
      'TRV LAN',
      'CORE-SW-TRV: checked, healthy',
      'IPLC-RTR-TRV: being checked now',
      'IPLC-RTR-MAA: root cause',
      'CORE-SW-MAA',
    ])
    expect(screen.getByText('IPLC-RTR-TRV')).toHaveClass('glow')
  })

  it('is not there without a path', () => {
    const { container } = render(<PathStrip stops={[]} states={new Map()} faults={new Set()} />)
    expect(container).toBeEmptyDOMElement()
  })
})

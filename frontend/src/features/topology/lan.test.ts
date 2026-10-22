import { describe, expect, it } from 'vitest'
import type { GraphDevice, GraphLink } from '@/api'
import { endpointTags, inSubnet, lanEndpoints } from './lan'

const device = (
  name: string,
  site: string,
  role: string,
  interfaces: [string, string[]][],
): GraphDevice => ({
  name,
  site,
  role,
  platform: 'cisco_ios',
  description: '',
  interfaces: interfaces.map(([n, ipv4]) => ({ name: n, status: 'up', ipv4 })),
})

// The lab as discovered: each core switch has its users' LAN on E1/0; the ISP router's free port
// faces the Internet.
const DEVICES = [
  device('CORE-SW-TRV', 'TRV', 'core', [
    ['Fa2/0', ['10.10.3.1/24']],
    ['E1/0', ['192.168.100.1/24']],
    ['Lo0', ['1.1.1.1/32']],
  ]),
  device('CORE-SW-MAA', 'MAA', 'core', [
    ['Fa2/0', ['10.10.5.2/24']],
    ['E1/0', ['192.168.200.1/24']],
    ['E1/1', []],
  ]),
  device('ISP-MAA-1', 'MAA', 'isp-router', [['Fa0/0', ['172.20.10.5/28']]]),
]
const LINKS = [
  { a: 'CORE-SW-TRV', a_interface: 'Fa2/0', b: 'IPLC-RTR-TRV', b_interface: 'Fa0/0' },
  { a: 'IPLC-RTR-MAA', a_interface: 'Fa0/0', b: 'CORE-SW-MAA', b_interface: 'Fa2/0' },
] as GraphLink[]

describe('LAN end points', () => {
  it('are the free addressed ports of core switches, named after their site', () => {
    expect(lanEndpoints(DEVICES, LINKS)).toEqual([
      {
        key: 'CORE-SW-TRV:E1/0',
        name: 'TRV LAN',
        device: 'CORE-SW-TRV',
        interface: 'E1/0',
        subnet: '192.168.100.0/24',
      },
      {
        key: 'CORE-SW-MAA:E1/0',
        name: 'MAA LAN',
        device: 'CORE-SW-MAA',
        interface: 'E1/0',
        subnet: '192.168.200.0/24',
      },
    ])
  })

  it('a second LAN at a site gets a number', () => {
    const two = device('CORE-SW-TRV', 'TRV', 'core', [
      ['E1/0', ['192.168.100.1/24']],
      ['E1/1', ['192.168.101.1/25']],
    ])
    expect(lanEndpoints([two], []).map((l) => [l.name, l.subnet])).toEqual([
      ['TRV LAN', '192.168.100.0/24'],
      ['TRV LAN 2', '192.168.101.0/25'],
    ])
  })

  it('a point-to-point /31 is not a LAN', () => {
    const p2p = device('CORE-SW-TRV', 'TRV', 'core', [['E1/0', ['10.0.0.0/31']]])
    expect(lanEndpoints([p2p], [])).toEqual([])
  })
})

it('knows whether an address or a network is inside a subnet', () => {
  expect(inSubnet('192.168.100.10', '192.168.100.0/24')).toBe(true)
  expect(inSubnet('192.168.100.0/24', '192.168.100.0/24')).toBe(true)
  expect(inSubnet('192.168.100.255', '192.168.100.0/24')).toBe(true)
  expect(inSubnet('192.168.101.0', '192.168.100.0/24')).toBe(false)
  expect(inSubnet('192.168.99.255', '192.168.100.0/24')).toBe(false)
  expect(inSubnet('300.1.1.1', '192.168.100.0/24')).toBe(false)
  // 192.168.100.300 is no address (it is not 192.168.101.44).
  expect(inSubnet('192.168.100.300', '192.168.101.0/24')).toBe(false)
})

describe('which end of the question a LAN is', () => {
  const lans = lanEndpoints(DEVICES, LINKS)
  const question = 'Why can the TRV LAN (192.168.100.10) not reach the MAA LAN (192.168.200.10)?'

  it('before the path is known: named in the question', () => {
    expect([...endpointTags(lans, [], question)]).toEqual([
      ['CORE-SW-TRV:E1/0', 'question'],
      ['CORE-SW-MAA:E1/0', 'question'],
    ])
  })

  it('the path the agent found says which end is which', () => {
    const path = ['CORE-SW-TRV', 'IPLC-RTR-TRV', 'IPLC-RTR-MAA', 'CORE-SW-MAA']
    expect([...endpointTags(lans, path, question)]).toEqual([
      ['CORE-SW-TRV:E1/0', 'source'],
      ['CORE-SW-MAA:E1/0', 'destination'],
    ])
    expect([...endpointTags(lans, [...path].reverse(), question)]).toEqual([
      ['CORE-SW-TRV:E1/0', 'destination'],
      ['CORE-SW-MAA:E1/0', 'source'],
    ])
  })

  it('a path of one device has no ends yet', () => {
    expect([...endpointTags(lans, ['CORE-SW-TRV'], question)][0]).toEqual([
      'CORE-SW-TRV:E1/0',
      'question',
    ])
  })

  it('a LAN the question does not name gets no tag', () => {
    const path = ['CORE-SW-TRV', 'CORE-SW-MAA']
    expect([...endpointTags(lans, path, 'Users at TRV (192.168.100.0/24) are slow')]).toEqual([
      ['CORE-SW-TRV:E1/0', 'source'],
    ])
  })
})

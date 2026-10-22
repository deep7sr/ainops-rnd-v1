import { describe, expect, it } from 'vitest'
import type { CommandCatalog, GraphLink, RunEvent } from '@/api'
import { routeBetween } from '@/features/topology/route'
import { agentWalk, consoleLines, devicesNamed, fillCommand } from './agent-walk'
import { deriveInvestigation } from './derive'

// The fault-1 investigation recorded on the live lab: three graph lookups, then interface checks
// on CORE-SW-TRV, IPLC-RTR-TRV and IPLC-RTR-MAA.
const files = import.meta.glob<{ events: RunEvent[] }>('../../../../fixtures/runs/*.json', {
  eager: true,
  import: 'default',
})
const RECORDED = Object.entries(files).find(([path]) =>
  path.endsWith('/fault1-leased-line-shut-run1.json'),
)?.[1].events as RunEvent[]

const PLATFORMS = new Map(
  ['ISP-TRV-1', 'FWL-TRV', 'CORE-SW-TRV', 'IPLC-RTR-TRV', 'IPLC-RTR-MAA', 'CORE-SW-MAA'].map(
    (name) => [name, name.startsWith('FWL') ? 'juniper_junos' : 'cisco_ios'],
  ),
)
const CATALOG: CommandCatalog = {
  cisco_ios: { get_interfaces: 'show ip interface', ping: 'ping {destination}' },
}

/** The investigation as the engineer saw it after the first `count` events. */
function at(count: number, running = true) {
  const view = deriveInvestigation(RECORDED.slice(0, count), [...PLATFORMS.keys()])
  return agentWalk(view.steps, running, PLATFORMS, CATALOG)
}
const index = (type: RunEvent['type'], id: string) =>
  RECORDED.findIndex((e) => e.type === type && 'id' in e && e.id === id) + 1

describe('the agent on the map', () => {
  it('is not on the map while it only asks the knowledge graph', () => {
    const walk = at(index('tool_result', 'E3'))
    expect(walk.at).toBeNull()
    expect(walk.trail).toEqual([])
    expect(walk.console).toBeNull()
  })

  it('goes to a device when it runs a command there, and the console shows the command', () => {
    const walk = at(index('tool_call', 'E4'))
    expect(walk).toMatchObject({ at: 'CORE-SW-TRV', mode: 'checking', trail: ['CORE-SW-TRV'] })
    expect(walk.console).toMatchObject({
      device: 'CORE-SW-TRV',
      command: 'show ip interface', // from the catalog: the result is not in yet
      state: 'running',
      lines: [],
    })
  })

  it('shows the verdict when the result is in, then thinks about the next step', () => {
    const walk = at(index('tool_result', 'E6'))
    expect(walk.mode).toBe('thinking')
    expect(walk.console).toMatchObject({ device: 'IPLC-RTR-MAA', state: 'problem' })
    expect(walk.console?.verdict).toMatch(/administratively down/)
  })

  it('leaves a trail in the order it went', () => {
    expect(at(RECORDED.length, false).trail).toEqual([
      'CORE-SW-TRV',
      'IPLC-RTR-TRV',
      'IPLC-RTR-MAA',
    ])
  })

  it('rests, without a console, when the investigation is over', () => {
    const walk = at(RECORDED.length, false)
    expect(walk).toMatchObject({ at: 'IPLC-RTR-MAA', mode: 'resting', console: null })
  })

  it('counts a device once while the agent stays there, again when it comes back', () => {
    const check = (id: string, device: string): RunEvent[] => [
      {
        type: 'tool_call',
        id,
        tool: 'get_interfaces',
        server: 'network',
        args: { device },
        at_ms: 1,
      },
      {
        type: 'tool_result',
        id,
        tool: 'get_interfaces',
        server: 'network',
        device,
        ok: true,
        summary: 'ok',
        data: [],
        evidence: null,
        duration_ms: 1,
        at_ms: 2,
      },
    ]
    const events = [
      ...check('E1', 'CORE-SW-TRV'),
      ...check('E2', 'CORE-SW-TRV'),
      ...check('E3', 'IPLC-RTR-TRV'),
      ...check('E4', 'CORE-SW-TRV'),
    ]
    const view = deriveInvestigation(events, [...PLATFORMS.keys()])
    expect(agentWalk(view.steps, true, PLATFORMS, CATALOG).trail).toEqual([
      'CORE-SW-TRV',
      'IPLC-RTR-TRV',
      'CORE-SW-TRV',
    ])
  })

  it('a device not on the map (an alias, a typo) is not a place to go', () => {
    const view = deriveInvestigation(RECORDED.slice(0, index('tool_call', 'E4')), [])
    const walk = agentWalk(view.steps, true, new Map(), CATALOG)
    expect(walk.at).toBeNull()
  })

  it('keeps the console short: headings first, gaps marked', () => {
    // The excerpt of `show ip interface` on IPLC-RTR-MAA with fault-1 on (simulator, 2026-10-21).
    const excerpt = [
      'FastEthernet0/0 is up, line protocol is up',
      '  Internet address is 10.10.5.1/24',
      '  Broadcast address is 255.255.255.255',
      '  MTU is 1500 bytes',
      '…',
      'FastEthernet1/0 is administratively down, line protocol is down',
      '…',
      'FastEthernet2/0 is administratively down, line protocol is down',
      '…',
    ]
    expect(consoleLines(excerpt, 5)).toEqual([
      'FastEthernet0/0 is up, line protocol is up',
      '  Internet address is 10.10.5.1/24',
      '  Broadcast address is 255.255.255.255',
      '…',
      'FastEthernet1/0 is administratively down, line protocol is down',
      '…',
      'FastEthernet2/0 is administratively down, line protocol is down',
      '…',
    ])
    expect(consoleLines(['a', '  b'])).toEqual(['a', '  b']) // short: whole
    expect(consoleLines([])).toEqual([])
  })

  it('fills the catalog command with the arguments of the call', () => {
    expect(fillCommand('ping {destination}', { destination: '10.10.4.1' })).toBe('ping 10.10.4.1')
    expect(fillCommand('show interfaces {interface}', {})).toBe('show interfaces {interface}')
  })
})

describe('moments on the map', () => {
  it('a knowledge-graph answer names its devices, in its order, while it is the latest step', () => {
    const walk = at(index('tool_result', 'E3')) // get_path
    expect(walk.lookup?.devices).toEqual([
      'CORE-SW-TRV',
      'IPLC-RTR-TRV',
      'IPLC-RTR-MAA',
      'CORE-SW-MAA',
    ])
    expect(at(index('tool_call', 'E4')).lookup).toBeNull() // the next check started
    expect(at(index('tool_result', 'E3'), false).lookup).toBeNull() // reopened: no replay
  })

  it('finds whole device names only', () => {
    expect(devicesNamed({ text: 'CORE-SW-TRV2 and XCORE-SW-TRV' }, ['CORE-SW-TRV'])).toEqual([])
    expect(devicesNamed([{ device: 'FWL-TRV' }, 'CORE-SW-TRV'], PLATFORMS.keys())).toEqual([
      'FWL-TRV',
      'CORE-SW-TRV',
    ])
  })

  it('a blocked command is stopped at the device it was meant for', () => {
    const refused = (device: string): RunEvent => ({
      type: 'refused',
      tool: 'configure_interface',
      args: { device },
      reason: 'AINOPS only reads the network',
      at_ms: 10,
    })
    const blockedAt = (device: string) => {
      const view = deriveInvestigation([refused(device)], [...PLATFORMS.keys()])
      return agentWalk(view.steps, true, PLATFORMS, CATALOG).blocked
    }
    expect(blockedAt('IPLC-RTR-MAA')).toMatchObject({ device: 'IPLC-RTR-MAA', rule: 'read_only' })
    expect(blockedAt('NOT-A-DEVICE')).toMatchObject({ device: null }) // shown, but not on a box
  })

  it('raises the shield for a safety rule only, not for the check limit', () => {
    const walkAfter = (reason: string, rule: 'budget' | 'address') => {
      const event: RunEvent = {
        type: 'refused',
        tool: 'ping',
        args: { device: 'IPLC-RTR-TRV', destination: '10.9.9.9' },
        reason,
        rule,
        at_ms: 10,
      }
      return agentWalk(
        deriveInvestigation([event], [...PLATFORMS.keys()]).steps,
        true,
        PLATFORMS,
        CATALOG,
      )
    }
    expect(walkAfter('the tool budget (16 calls) is used up', 'budget').blocked).toBeNull()
    expect(walkAfter('destination 10.9.9.9 did not come from …', 'address').blocked).toMatchObject({
      device: 'IPLC-RTR-TRV',
      rule: 'address',
    })
  })

  it('a request the tool turned down was never sent to the device', () => {
    // The live run of 2026-10-22 (inv-88c9b4bc, E7): a network given where an address goes.
    const events: RunEvent[] = [
      {
        type: 'tool_call',
        id: 'E7',
        tool: 'get_interfaces',
        server: 'network',
        args: { device: 'IPLC-RTR-TRV' },
        at_ms: 1,
      },
      {
        type: 'tool_result',
        id: 'E7',
        tool: 'get_interfaces',
        server: 'network',
        device: 'IPLC-RTR-TRV',
        ok: false,
        failure: 'request',
        summary: "Error executing tool get_interfaces: destination '192.168.200.0/24' is not valid",
        data: null,
        evidence: null,
        duration_ms: 1,
        at_ms: 2,
      },
    ]
    const view = deriveInvestigation(events, [...PLATFORMS.keys()])
    expect(agentWalk(view.steps, true, PLATFORMS, CATALOG).console).toMatchObject({
      state: 'not_run',
      verdict: "Not sent: destination '192.168.200.0/24' is not valid",
    })
  })

  it('remembers the ports of each device from its latest interfaces check', () => {
    const ports = at(RECORDED.length, false).ports
    expect([...ports.keys()]).toEqual(['CORE-SW-TRV', 'IPLC-RTR-TRV', 'IPLC-RTR-MAA'])
    expect(ports.get('IPLC-RTR-MAA')).toContainEqual({ name: 'Fa2/0', status: 'admin-down' })
  })
})

describe('the way the marker travels', () => {
  const link = (a: string, b: string) => ({ a, b }) as GraphLink
  const LINKS = [
    link('CORE-SW-TRV', 'IPLC-RTR-TRV'),
    link('IPLC-RTR-TRV', 'IPLC-RTR-MAA'),
    link('IPLC-RTR-MAA', 'CORE-SW-MAA'),
    link('FWL-TRV', 'CORE-SW-TRV'),
  ]

  it('follows the links, fewest hops', () => {
    expect(routeBetween('FWL-TRV', 'CORE-SW-MAA', LINKS)).toEqual([
      'FWL-TRV',
      'CORE-SW-TRV',
      'IPLC-RTR-TRV',
      'IPLC-RTR-MAA',
      'CORE-SW-MAA',
    ])
  })

  it('flies straight when the map knows no way', () => {
    expect(routeBetween('FWL-TRV', 'ISP-MAA-1', LINKS)).toEqual(['FWL-TRV', 'ISP-MAA-1'])
    expect(routeBetween('FWL-TRV', 'FWL-TRV', LINKS)).toEqual(['FWL-TRV'])
  })
})

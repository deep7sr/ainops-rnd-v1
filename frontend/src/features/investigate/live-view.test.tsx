import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { RunEvent, Topology } from '@/api'
import { boxIssue, faultFrame, type AgentWalk } from '@/features/topology/highlight'
import { frameView, NODE_WIDTH } from '@/features/topology/layout'
import { NetworkMap } from '@/features/topology/network-map'
import { deriveInvestigation, touchesNetwork } from './derive'
import { NowBanner } from './now-banner'

// What the engineer sees for the recorded fault-1 run: the map and the "Now" line.

const files = import.meta.glob<{ events: RunEvent[] }>('../../../../fixtures/runs/*.json', {
  eager: true,
  import: 'default',
})
const recorded = (name: string) =>
  Object.entries(files).find(([p]) => p.endsWith(`/${name}.json`))?.[1].events as RunEvent[]
const events = recorded('fault1-leased-line-shut-run1')

const iface = (name: string, ipv4: string[] = []) => ({ name, status: 'up', ipv4 })
const device = (name: string, site: string, role: string) => ({
  name,
  site,
  role,
  platform: 'cisco_ios',
  description: '',
  interfaces: [iface('Fa0/0', ['10.0.0.1/24']), iface('Fa2/0', ['10.10.4.1/24'])],
})
const link = (a: string, ai: string, b: string, bi: string, subnet: string) => ({
  key: `${a}:${ai}|${b}:${bi}`,
  a,
  a_interface: ai,
  a_status: 'up',
  b,
  b_interface: bi,
  b_status: 'up',
  subnet,
  sources: ['cdp'],
})
const TOPOLOGY: Topology = {
  devices: [
    device('CORE-SW-TRV', 'TRV', 'core'),
    device('IPLC-RTR-TRV', 'TRV', 'wan-router'),
    device('FWL-TRV', 'TRV', 'firewall'),
    device('IPLC-RTR-MAA', 'MAA', 'wan-router'),
    device('CORE-SW-MAA', 'MAA', 'core'),
  ],
  links: [
    link('CORE-SW-TRV', 'Fa2/0', 'IPLC-RTR-TRV', 'Fa0/0', '10.10.3.0/24'),
    link('IPLC-RTR-TRV', 'Fa2/0', 'IPLC-RTR-MAA', 'Fa2/0', '10.10.4.0/24'),
    link('IPLC-RTR-MAA', 'Fa0/0', 'CORE-SW-MAA', 'Fa2/0', '10.10.5.0/24'),
  ],
  discovery: null,
}
const NAMES = TOPOLOGY.devices.map((d) => d.name)

function at(match: (e: RunEvent) => boolean) {
  return deriveInvestigation(events.slice(0, events.findIndex(match) + 1), NAMES)
}

describe('live map', () => {
  it('names the state and the problem of each device it checked', () => {
    const view = deriveInvestigation(events, NAMES)
    render(<NetworkMap topology={TOPOLOGY} highlight={view.highlight} showEdges={false} />)
    expect(screen.getByLabelText(/^IPLC-RTR-MAA, wan-router, root cause/)).toHaveAttribute(
      'aria-label',
      'IPLC-RTR-MAA, wan-router, root cause, Fa2/0 is administratively down (shut)',
    )
    expect(screen.getByLabelText(/^IPLC-RTR-TRV/)).toHaveAttribute(
      'aria-label',
      'IPLC-RTR-TRV, wan-router, checked, healthy',
    )
    expect(screen.getByLabelText(/10\.10\.4\.0\/24, blamed by the diagnosis/)).toBeInTheDocument()
    expect(screen.getByText('Root cause · E6')).toBeInTheDocument()
    // FWL-TRV is not on the path: faded, no state.
    expect(screen.getByLabelText(/^FWL-TRV/)).toHaveClass('opacity-35')
  })

  it('shows what runs on the device being checked', () => {
    const view = at((e) => e.type === 'tool_call' && e.id === 'E6')
    render(<NetworkMap topology={TOPOLOGY} highlight={view.highlight} showEdges={false} />)
    expect(screen.getByLabelText(/^IPLC-RTR-MAA/)).toHaveAttribute(
      'aria-label',
      'IPLC-RTR-MAA, wan-router, being checked now',
    )
    expect(screen.getByText('checking interfaces…')).toBeInTheDocument()
  })
})

describe('Now line', () => {
  it('says what the agent is doing and why', () => {
    const view = at((e) => e.type === 'tool_call' && e.id === 'E6')
    render(<NowBanner now={view.now} stepCount={view.steps.length} />)
    expect(screen.getByText('Checking the interfaces of IPLC-RTR-MAA')).toBeInTheDocument()
    expect(
      screen.getByText('Check interface status on MAA side of leased line'),
    ).toBeInTheDocument()
  })

  it('reports a problem the moment the code finds it', () => {
    const view = at((e) => e.type === 'tool_result' && e.id === 'E6')
    render(<NowBanner now={view.now} stepCount={view.steps.length} />)
    expect(
      screen.getByText(/Found a problem on IPLC-RTR-MAA: Fa2\/0 is administratively down/),
    ).toBeInTheDocument()
  })

  it('ends with the root cause', () => {
    const view = deriveInvestigation(events, NAMES)
    render(<NowBanner now={view.now} stepCount={view.steps.length} />)
    expect(screen.getByText(/^Root cause: The leased‑line interface/)).toBeInTheDocument()
  })
})

it('writes the latest ping result in the box of the device that replied', () => {
  const view = deriveInvestigation(recorded('healthy-baseline'), NAMES)
  render(<NetworkMap topology={TOPOLOGY} highlight={view.highlight} showEdges={false} />)
  expect(screen.getByText('✓ 192.168.200.10 replied')).toBeInTheDocument()
  expect(screen.getByLabelText(/^CORE-SW-MAA/)).toHaveAttribute(
    'aria-label',
    'CORE-SW-MAA, core, checked, healthy, ✓ 192.168.200.10 replied',
  )
})

describe('the path and the pings in motion', () => {
  const hopNumbers = (map: HTMLElement) =>
    [...map.querySelectorAll('g[aria-hidden] > circle.fill-primary + text')].map(
      (t) => t.textContent,
    )

  it('numbers the hops of the path and lets traffic flow along them', () => {
    const view = at((e) => e.type === 'tool_result' && e.id === 'E3') // the path is known
    const { container } = render(
      <NetworkMap topology={TOPOLOGY} highlight={view.highlight} showEdges={false} />,
    )
    expect(hopNumbers(container)).toEqual(['1', '2', '3'])
    expect(container.querySelectorAll('.flow-dash')).toHaveLength(3)
  })

  it('stops the flow on the link the diagnosis blames', () => {
    const view = deriveInvestigation(events, NAMES)
    const { container } = render(
      <NetworkMap topology={TOPOLOGY} highlight={view.highlight} showEdges={false} />,
    )
    expect(hopNumbers(container)).toEqual(['1', '3'])
    expect(container.querySelectorAll('.flow-dash')).toHaveLength(2)
  })

  it('plays a ping answer once while the investigation runs, never when it is reopened', () => {
    const view = deriveInvestigation(recorded('healthy-baseline'), NAMES)
    const thinking: AgentWalk = {
      trail: [],
      at: null,
      mode: 'thinking',
      console: null,
      lookup: null,
      blocked: null,
      ports: new Map(),
    }
    const live = render(
      <NetworkMap
        topology={TOPOLOGY}
        highlight={view.highlight}
        agent={thinking}
        showEdges={false}
      />,
    )
    expect(live.container.querySelector('circle.fill-status-healthy')).not.toBeNull()
    live.unmount()

    const reopened = render(
      <NetworkMap topology={TOPOLOGY} highlight={view.highlight} showEdges={false} />,
    )
    expect(reopened.container.querySelector('circle.fill-status-healthy')).toBeNull()
  })
})

describe('the root-cause reveal', () => {
  const view = deriveInvestigation(events, NAMES)
  const viewBox = (map: HTMLElement) =>
    (map.querySelector('svg[aria-label="Network map"]')?.getAttribute('viewBox') ?? '')
      .split(' ')
      .map(Number)

  it('frames the blamed device and the other end of its blamed link', () => {
    expect(faultFrame(view.highlight, TOPOLOGY.links).sort()).toEqual([
      'IPLC-RTR-MAA',
      'IPLC-RTR-TRV',
    ])
    expect(
      faultFrame(at((e) => e.type === 'tool_result' && e.id === 'E6').highlight, TOPOLOGY.links),
    ).toEqual([])
  })

  it('a blamed interface brings both ends of its link into the frame', () => {
    const onlyInterface = (blamed: string) => ({
      ...view.highlight,
      faultDevices: new Set<string>(),
      faultInterfaces: new Set([blamed]),
    })
    const both = ['IPLC-RTR-MAA', 'IPLC-RTR-TRV']
    expect(faultFrame(onlyInterface('IPLC-RTR-TRV:Fa2/0'), TOPOLOGY.links).sort()).toEqual(both)
    expect(faultFrame(onlyInterface('IPLC-RTR-MAA:Fa2/0'), TOPOLOGY.links).sort()).toEqual(both)
  })

  it('zooms the map to the fault, keeping its proportions', () => {
    const whole = viewBox(
      render(<NetworkMap topology={TOPOLOGY} highlight={view.highlight} showEdges={false} />)
        .container,
    )
    const zoomed = viewBox(
      render(
        <NetworkMap
          topology={TOPOLOGY}
          highlight={view.highlight}
          focus={faultFrame(view.highlight, TOPOLOGY.links)}
          showEdges={false}
        />,
      ).container,
    )
    expect(zoomed[2]).toBeLessThan(whole[2])
    expect(zoomed[2] / zoomed[3]).toBeCloseTo(whole[2] / whole[3], 5)
    // Inside the whole map.
    expect(zoomed[0]).toBeGreaterThanOrEqual(whole[0])
    expect(zoomed[0] + zoomed[2]).toBeLessThanOrEqual(whole[0] + whole[2] + 1e-6)
  })

  it('marks where the blamed link breaks', () => {
    const { container } = render(
      <NetworkMap topology={TOPOLOGY} highlight={view.highlight} showEdges={false} />,
    )
    expect(
      container.querySelectorAll('circle.animate-ping.fill-status-critical\\/40'),
    ).toHaveLength(1)
  })
})

it('frames nothing narrower than the boxes, and never more than the whole map', () => {
  const whole = { x: 0, y: 0, width: 1000, height: 560 }
  expect(frameView(whole, [])).toEqual(whole)
  expect(
    frameView(whole, [
      { x: 10, y: 10 },
      { x: 990, y: 550 },
    ]),
  ).toEqual(whole)
  const one = frameView(whole, [{ x: 500, y: 300 }])
  expect(one.width).toBeGreaterThan(NODE_WIDTH)
  expect(one.width / one.height).toBeCloseTo(1000 / 560, 5)
})

it('shortens problems to fit a device box', () => {
  expect(boxIssue('Fa2/0 is administratively down (shut)')).toBe('Fa2/0 shut (admin down)')
  expect(boxIssue('Fa2/0 is down')).toBe('Fa2/0 down')
  expect(boxIssue('no OSPF neighbours')).toBe('no OSPF neighbours')
})

describe('answers that need no network', () => {
  const refused = deriveInvestigation(recorded('refused-change-request'), NAMES)

  it('show no map and no confidence', () => {
    expect(touchesNetwork(refused.steps)).toBe(false)
    expect(touchesNetwork(deriveInvestigation(events, NAMES).steps)).toBe(true)
    // A command blocked on a device does show the map: it shows where the command was stopped.
    const blocked: RunEvent = {
      type: 'refused',
      tool: 'configure_interface',
      args: { device: 'IPLC-RTR-MAA' },
      reason: 'AINOPS only reads the network',
      at_ms: 5,
    }
    expect(touchesNetwork(deriveInvestigation([blocked], NAMES).steps)).toBe(true)
    render(<NowBanner now={refused.now} stepCount={refused.steps.length} />)
    expect(
      screen.getByText('Refused before running any check: AINOPS only reads the network'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/confidence/)).not.toBeInTheDocument()
  })

  it('a plain answer says it checked nothing', () => {
    const answered = refused.verdict
      ? { ...refused.verdict, report: { ...refused.verdict.report, outcome: 'answered' as const } }
      : null
    if (!answered) throw new Error('recording has no report')
    render(<NowBanner now={{ kind: 'done', verdict: answered }} stepCount={0} />)
    expect(screen.getByText(/without checking any device/)).toBeInTheDocument()
    expect(screen.queryByText(/confidence/)).not.toBeInTheDocument()
  })
})

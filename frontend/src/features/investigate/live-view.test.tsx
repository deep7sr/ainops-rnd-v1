import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { RunEvent, Topology } from '@/api'
import { boxIssue } from '@/features/topology/highlight'
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

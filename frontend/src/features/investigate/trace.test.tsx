import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { RunEvent, ToolHealth } from '@/api'
import { boxIssue } from '@/features/topology/highlight'
import { deriveInvestigation } from './derive'
import { NowBanner } from './now-banner'
import { Timeline } from './timeline'
import { readTrace } from './trace'

// trace_route on the page. The samples are real backend output (backend test_trace.py writes them
// and fails while they differ from what the code produces).

interface Sample {
  device: string
  summary: string
  data: unknown
  health: ToolHealth
}

const files = import.meta.glob<Sample>('../../../../fixtures/routes/samples/*.json', {
  eager: true,
  import: 'default',
})
const sample = (name: string) =>
  Object.entries(files).find(([p]) => p.endsWith(`/${name}.json`))?.[1] as Sample

const NAMES = ['CORE-SW-TRV', 'IPLC-RTR-TRV', 'IPLC-RTR-MAA', 'CORE-SW-MAA', 'FWL-TRV']
const CABLED = ['CORE-SW-TRV', 'IPLC-RTR-TRV', 'IPLC-RTR-MAA', 'CORE-SW-MAA']

function call(
  id: string,
  tool: string,
  args: Record<string, unknown>,
  server = 'network',
): RunEvent {
  return { type: 'tool_call', id, tool, server, args, why: 'Follow it', at_ms: 1 }
}

function traced(id: string, result: Sample, source = '192.168.100.10'): RunEvent[] {
  return [
    call(id, 'trace_route', { source, destination: '192.168.200.10' }),
    {
      type: 'tool_result',
      id,
      tool: 'trace_route',
      server: 'network',
      device: result.device,
      ok: true,
      summary: result.summary,
      data: result.data,
      evidence: { command: 'show ip route', source: 'replay', collected_at: '', duration_ms: 9 },
      health: result.health,
      duration_ms: 9,
      at_ms: 2,
    },
  ]
}

function cabledPath(id: string, devices: string[] = CABLED): RunEvent[] {
  return [
    call(id, 'get_path', { source: 'CORE-SW-TRV', destination: 'CORE-SW-MAA' }, 'topology'),
    {
      type: 'tool_result',
      id,
      tool: 'get_path',
      server: 'topology',
      device: null,
      ok: true,
      summary: 'path',
      data: { devices },
      evidence: null,
      duration_ms: 1,
      at_ms: 2,
    },
  ]
}

const started: RunEvent = { type: 'started', question: 'Why?', tools: [], at_ms: 0 }

describe('trace_route on the map', () => {
  it('draws the route the routing tables chose and marks every hop that routed it on', () => {
    const view = deriveInvestigation([started, ...traced('E1', sample('healthy'))], NAMES)
    expect(view.highlight.path).toEqual(CABLED)
    expect([...view.highlight.states]).toEqual(CABLED.map((name) => [name, 'ok']))
  })

  it('marks where the route is missing and keeps the cabled path on the map', () => {
    const events = [
      started,
      ...cabledPath('E1'),
      ...traced('E2', sample('fault1'), '192.168.100.0/24'),
    ]
    const view = deriveInvestigation(events, NAMES)
    expect(view.highlight.path).toEqual(CABLED) // a one-device trace does not replace it
    expect(view.highlight.states.get('CORE-SW-TRV')).toBe('problem')
    expect(view.highlight.issues.get('CORE-SW-TRV')).toEqual([
      'CORE-SW-TRV has no route to 192.168.200.10',
    ])
    expect(boxIssue('CORE-SW-TRV has no route to 192.168.200.10')).toBe(
      'no route to 192.168.200.10',
    )
  })

  it('a traced route beats the cabled path, whichever came first', () => {
    // The graph's shortest path through the firewall is not where the routing tables send traffic.
    const viaFirewall = ['CORE-SW-TRV', 'FWL-TRV']
    const traceFirst = [
      started,
      ...traced('E1', sample('healthy')),
      ...cabledPath('E2', viaFirewall),
    ]
    const traceLast = [
      started,
      ...cabledPath('E1', viaFirewall),
      ...traced('E2', sample('healthy')),
    ]
    expect(deriveInvestigation(traceFirst, NAMES).highlight.path).toEqual(CABLED)
    expect(deriveInvestigation(traceLast, NAMES).highlight.path).toEqual(CABLED)
  })

  it('blames the device where the route stops, not the one it started from', () => {
    const health: ToolHealth = {
      status: 'problem',
      issues: [{ text: 'IPLC-RTR-TRV has no route to 192.168.200.10', interface: null }],
    }
    const stopsLater: Sample = {
      device: 'CORE-SW-TRV',
      summary: 'stops at IPLC-RTR-TRV',
      health,
      data: {
        status: 'no_route',
        destination: '192.168.200.10',
        stopped_at: 'IPLC-RTR-TRV',
        hops: [
          {
            device: 'CORE-SW-TRV',
            route: { prefix: '0.0.0.0/0', protocol: 'static', next_hop: '10.10.3.2' },
            next_hop_device: 'IPLC-RTR-TRV',
          },
          { device: 'IPLC-RTR-TRV', route: null },
        ],
      },
    }
    const report: RunEvent = {
      type: 'report',
      report: {
        outcome: 'diagnosed',
        summary: 'x',
        root_cause: 'no route on IPLC-RTR-TRV',
        root_cause_evidence: ['E1'],
        affected: [],
        findings: [],
        next_steps: [],
        limitations: [],
      },
      confidence: 'medium',
      confidence_reasons: [],
      tool_calls: 1,
      at_ms: 3,
    }
    const view = deriveInvestigation([started, ...traced('E1', stopsLater), report], NAMES)
    expect([...view.highlight.faultDevices]).toEqual(['IPLC-RTR-TRV'])
    expect(view.highlight.states.get('CORE-SW-TRV')).toBe('ok')
    expect(view.highlight.states.get('IPLC-RTR-TRV')).toBe('problem')
  })

  it('a hop that did not answer is unreachable', () => {
    const failed: Sample = {
      device: 'CORE-SW-TRV',
      summary: 'x',
      health: { status: 'info', issues: [] },
      data: {
        status: 'device_failed',
        destination: '192.168.200.10',
        stopped_at: 'IPLC-RTR-TRV',
        hops: [
          { device: 'CORE-SW-TRV', route: { prefix: '192.168.200.0/24', protocol: 'ospf' } },
          { device: 'IPLC-RTR-TRV', route: null, note: 'did not answer on the console' },
        ],
      },
    }
    const view = deriveInvestigation([started, ...traced('E1', failed)], NAMES)
    expect(view.highlight.states.get('IPLC-RTR-TRV')).toBe('unreachable')
  })
})

describe('readTrace', () => {
  it('turns anything that is not a trace into null instead of crashing the page', () => {
    const junk: unknown[] = [
      null,
      1,
      'x',
      [],
      { hops: 'x' },
      { status: 'reached', hops: [] },
      { status: 'reached', hops: [null] },
      { status: 'reached', hops: [{ device: 5 }] },
      { status: 'sideways', hops: [{ device: 'A' }] },
    ]
    for (const data of junk) {
      expect(readTrace(data)).toBeNull()
      const result = {
        device: 'CORE-SW-TRV',
        summary: '',
        data,
        health: { status: 'ok', issues: [] },
      }
      expect(() =>
        deriveInvestigation([started, ...traced('E1', result as Sample)], NAMES),
      ).not.toThrow()
    }
  })
})

describe('trace_route in the timeline', () => {
  it('shows the route each device chose, in plain words', () => {
    const view = deriveInvestigation([started, ...traced('E1', sample('healthy'))], NAMES)
    render(<Timeline steps={view.steps} focused={null} />)
    expect(
      screen.getByText('Following the routing tables from 192.168.100.10 to 192.168.200.10'),
    ).toBeInTheDocument()
    const hops = screen.getByRole('list', { name: 'Route followed' })
    expect(hops).toHaveTextContent(
      'CORE-SW-TRV uses 192.168.200.0/24, learned from OSPF (distance 110, metric 13)',
    )
    expect(hops).toHaveTextContent('next hop 10.10.3.2 (IPLC-RTR-TRV) out of Fa2/0')
    expect(hops).toHaveTextContent('CORE-SW-MAA uses 192.168.200.0/24, directly connected')
    expect(
      screen.getByText("192.168.100.10 is on CORE-SW-TRV's network 192.168.100.0/24 (E1/0)"),
    ).toBeInTheDocument()
    expect(
      screen.getByText("Arrived: 192.168.200.10 is on CORE-SW-MAA's own network"),
    ).toBeInTheDocument()
  })

  it('says where traffic stops when a route is missing', () => {
    const view = deriveInvestigation(
      [started, ...traced('E1', sample('fault1'), '192.168.100.0/24')],
      NAMES,
    )
    render(<Timeline steps={view.steps} focused={null} />)
    expect(screen.getByRole('list', { name: 'Route followed' })).toHaveTextContent(
      'CORE-SW-TRV has no route for it',
    )
    expect(
      screen.getByText('CORE-SW-TRV has no route to 192.168.200.10: traffic stops here'),
    ).toBeInTheDocument()
  })

  it('the Now line names the problem without a misleading device prefix', () => {
    const view = deriveInvestigation(
      [started, ...traced('E1', sample('fault1'), '192.168.100.0/24')],
      NAMES,
    )
    render(<NowBanner now={view.now} stepCount={view.steps.length} />)
    expect(
      screen.getByText(/Found a problem: CORE-SW-TRV has no route to 192\.168\.200\.10/),
    ).toBeInTheDocument()
  })
})

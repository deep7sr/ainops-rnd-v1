import { describe, expect, it } from 'vitest'
import type { RunEvent } from '@/api'
import {
  deriveInvestigation,
  deviceStates,
  parseAffected,
  shortInterface,
  type Step,
} from './derive'

const DEVICES = ['IPLC-RTR-TRV', 'IPLC-RTR-MAA', 'CORE-SW-MAA']

describe('parseAffected', () => {
  it('finds devices and interfaces in any spelling', () => {
    const { devices, interfaces } = parseAffected(
      ['IPLC-RTR-MAA FastEthernet2/0', 'iplc-rtr-trv Fa2/0 (leased line)', 'the Internet'],
      DEVICES,
    )
    expect([...devices]).toEqual(['IPLC-RTR-MAA', 'IPLC-RTR-TRV'])
    expect([...interfaces]).toEqual(['IPLC-RTR-MAA:Fa2/0', 'IPLC-RTR-TRV:Fa2/0'])
  })

  it('ignores words that are not interfaces', () => {
    const { interfaces } = parseAffected(['IPLC-RTR-MAA OSPF area 0'], DEVICES)
    expect([...interfaces]).toEqual([])
  })
})

it('shortens interface names like the graph', () => {
  expect(shortInterface('GigabitEthernet0/1')).toBe('Gi0/1')
  expect(shortInterface('ge-0/0/1')).toBe('ge-0/0/1')
})

describe('deriveInvestigation', () => {
  const events: RunEvent[] = [
    { type: 'started', question: 'Why is MAA-P2P down?', tools: [], at_ms: 0 },
    {
      type: 'tool_call',
      id: 'E1',
      tool: 'get_path',
      server: 'topology',
      args: { source: 'IPLC-RTR-MAA', destination: 'IPLC-RTR-TRV' },
      why: 'Find the path',
      at_ms: 10,
    },
    {
      type: 'tool_result',
      id: 'E1',
      tool: 'get_path',
      server: 'topology',
      device: null,
      ok: true,
      summary: 'path',
      data: { devices: ['IPLC-RTR-MAA', 'IPLC-RTR-TRV'] },
      evidence: null,
      duration_ms: 5,
      at_ms: 20,
    },
    {
      type: 'tool_call',
      id: 'E2',
      tool: 'get_interfaces',
      server: 'network',
      args: { device: 'iplc-rtr-maa' },
      at_ms: 30,
    },
    {
      type: 'tool_call',
      id: 'E3',
      tool: 'get_interfaces',
      server: 'network',
      args: { device: 'IPLC-RTR-TRV' },
      at_ms: 31,
    },
    {
      type: 'tool_result',
      id: 'E3',
      tool: 'get_interfaces',
      server: 'network',
      device: 'IPLC-RTR-TRV',
      ok: false,
      summary: 'no answer',
      data: null,
      evidence: null,
      duration_ms: 5,
      at_ms: 40,
    },
  ]

  it('pairs calls with results and follows the path', () => {
    const view = deriveInvestigation(events, DEVICES)
    expect(view.question).toBe('Why is MAA-P2P down?')
    expect(view.steps.map((s) => [s.evidenceId, s.state])).toEqual([
      ['E1', 'ok'],
      ['E2', 'running'],
      ['E3', 'error'],
    ])
    expect(view.highlight.path).toEqual(['IPLC-RTR-MAA', 'IPLC-RTR-TRV'])
    expect(view.highlight.states.get('IPLC-RTR-MAA')).toBe('checking') // name normalised
    expect(view.highlight.states.get('IPLC-RTR-TRV')).toBe('unreachable')
  })

  it('blames only a diagnosed fault', () => {
    const report = {
      type: 'report' as const,
      report: {
        outcome: 'no_fault_found' as const,
        summary: '',
        root_cause: null,
        root_cause_evidence: [],
        affected: ['IPLC-RTR-MAA Fa2/0'],
        findings: [],
        next_steps: [],
        limitations: [],
      },
      confidence: 'medium' as const,
      confidence_reasons: [],
      tool_calls: 3,
      at_ms: 50,
    }
    expect(deriveInvestigation([...events, report], DEVICES).highlight.faultDevices.size).toBe(0)
    const diagnosed = { ...report, report: { ...report.report, outcome: 'diagnosed' as const } }
    const view = deriveInvestigation([...events, diagnosed], DEVICES)
    expect([...view.highlight.faultInterfaces]).toEqual(['IPLC-RTR-MAA:Fa2/0'])
  })
})

describe('deviceStates', () => {
  const base: Step = {
    kind: 'tool',
    key: 'E1',
    evidenceId: 'E1',
    tool: 'get_interfaces',
    server: 'network',
    args: {},
    why: '',
    sentence: '',
    state: 'ok',
    summary: '',
    data: null,
    evidence: null,
    health: { status: 'ok', issues: [] },
    device: 'IPLC-RTR-MAA',
    durationMs: 1,
    atMs: 1,
    skillStep: null,
    turn: 1,
  }
  const problem = {
    status: 'problem' as const,
    issues: [{ text: 'Fa2/0 is down', interface: 'Fa2/0' }],
  }

  it('a problem found on a device outweighs later healthy checks', () => {
    const states = deviceStates([
      { ...base, health: problem },
      { ...base, key: 'E2', tool: 'get_ospf_neighbors' },
    ])
    expect(states.get('IPLC-RTR-MAA')).toBe('problem')
  })

  it('a device that answered once is not unreachable', () => {
    const states = deviceStates([
      { ...base, state: 'error', health: null },
      { ...base, key: 'E2' },
    ])
    expect(states.get('IPLC-RTR-MAA')).toBe('ok')
  })

  it('tools without a verdict only mark the device as checked', () => {
    const states = deviceStates([
      { ...base, tool: 'get_arp_table', health: { status: 'info', issues: [] } },
    ])
    expect(states.get('IPLC-RTR-MAA')).toBe('checked')
  })

  it('topology tools do not colour devices', () => {
    expect(deviceStates([{ ...base, server: 'topology' }]).size).toBe(0)
  })
})

it('does not crash when a result carries a device record instead of a name', () => {
  const events = [
    {
      type: 'tool_call',
      id: 'E1',
      tool: 'find_device',
      server: 'topology',
      args: { query: 'IPLC-RTR-TRV' },
      at_ms: 1,
    },
    {
      type: 'tool_result',
      id: 'E1',
      tool: 'find_device',
      server: 'topology',
      device: { name: 'IPLC-RTR-TRV', site: 'TRV' },
      ok: true,
      summary: 'IPLC-RTR-TRV',
      data: null,
      evidence: null,
      duration_ms: 5,
      at_ms: 2,
    },
  ] as unknown as RunEvent[]
  const view = deriveInvestigation(events, DEVICES)
  expect(view.steps[0].device).toBeNull()
  expect(view.steps[0].state).toBe('ok')
})

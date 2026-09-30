import { describe, expect, it } from 'vitest'
import type { RunEvent } from '@/api'
import { deriveInvestigation, parseAffected, shortInterface } from './derive'

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
    expect([...view.highlight.active]).toEqual(['IPLC-RTR-MAA']) // name normalised
    expect(view.highlight.checked.get('IPLC-RTR-TRV')).toBe('error')
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

import { describe, expect, it } from 'vitest'
import type { RunEvent } from '@/api'
import { deriveInvestigation } from './derive'
import { describeCall } from './describe'

// Real investigations recorded on the live lab on 5 Oct 2026 (fixtures/runs). What the engineer
// saw is rebuilt from the events, at the end and at moments in between, like a replay.

const files = import.meta.glob<{ events: RunEvent[] }>('../../../../fixtures/runs/*.json', {
  eager: true,
  import: 'default',
})

function recorded(name: string): RunEvent[] {
  const entry = Object.entries(files).find(([path]) => path.endsWith(`/${name}.json`))
  if (!entry) throw new Error(`no recorded run ${name}`)
  return entry[1].events
}

const DEVICES = [
  'ISP-TRV-1',
  'FWL-TRV',
  'CORE-SW-TRV',
  'IPLC-RTR-TRV',
  'IPLC-RTR-MAA',
  'CORE-SW-MAA',
  'FWL-MAA',
  'ISP-MAA-1',
]

/** The events up to and including the first one that matches. */
function until(events: RunEvent[], match: (e: RunEvent) => boolean): RunEvent[] {
  const index = events.findIndex(match)
  if (index < 0) throw new Error('event not found')
  return events.slice(0, index + 1)
}

describe('fault 1 (Fa2/0 shut on IPLC-RTR-MAA), recorded run 1', () => {
  const events = recorded('fault1-leased-line-shut-run1')

  it('ends with the blamed device and interface on the map', () => {
    const { highlight, now } = deriveInvestigation(events, DEVICES)
    expect(highlight.path).toEqual(['CORE-SW-TRV', 'IPLC-RTR-TRV', 'IPLC-RTR-MAA', 'CORE-SW-MAA'])
    expect(Object.fromEntries(highlight.states)).toEqual({
      'CORE-SW-TRV': 'ok',
      'IPLC-RTR-TRV': 'ok',
      'IPLC-RTR-MAA': 'problem',
    })
    expect(highlight.issues.get('IPLC-RTR-MAA')).toEqual(['Fa2/0 is administratively down (shut)'])
    expect([...highlight.faultInterfaces]).toEqual(['IPLC-RTR-MAA:Fa2/0'])
    expect(highlight.faultEvidence).toEqual(['E6'])
    expect(now.kind).toBe('done')
  })

  it('says what is being checked, and why, while the check runs', () => {
    const moment = until(events, (e) => e.type === 'tool_call' && e.id === 'E6')
    const { now, highlight } = deriveInvestigation(moment, DEVICES)
    expect(now.kind).toBe('working')
    if (now.kind !== 'working') return
    expect(now.step.sentence).toBe('Checking the interfaces of IPLC-RTR-MAA')
    expect(now.step.why).toBe('Check interface status on MAA side of leased line')
    expect(highlight.caption).toEqual({ device: 'IPLC-RTR-MAA', label: 'checking interfaces' })
    expect(highlight.states.get('IPLC-RTR-MAA')).toBe('checking')
    expect(highlight.faultInterfaces.size).toBe(0) // nothing is blamed before the report
  })

  it('shows the problem as soon as the result arrives, before the report', () => {
    const moment = until(events, (e) => e.type === 'tool_result' && e.id === 'E6')
    const { now, highlight } = deriveInvestigation(moment, DEVICES)
    expect(now.kind).toBe('thinking')
    if (now.kind === 'thinking') expect(now.last?.health?.status).toBe('problem')
    expect(highlight.states.get('IPLC-RTR-MAA')).toBe('problem')
    expect(highlight.caption).toBeNull()
  })

  it('blames the interface from the cited evidence even if the report names none', () => {
    const quiet = events.map((e) =>
      e.type === 'report' ? { ...e, report: { ...e.report, affected: [] } } : e,
    )
    const { highlight } = deriveInvestigation(quiet, DEVICES)
    expect([...highlight.faultInterfaces]).toEqual(['IPLC-RTR-MAA:Fa2/0'])
    expect([...highlight.faultDevices]).toEqual(['IPLC-RTR-MAA'])
  })
})

it('fault 1 is diagnosed the same way in all three recorded runs', () => {
  for (const run of [1, 2, 3]) {
    const { highlight } = deriveInvestigation(
      recorded(`fault1-leased-line-shut-run${run}`),
      DEVICES,
    )
    expect(highlight.states.get('IPLC-RTR-MAA')).toBe('problem')
    expect([...highlight.faultInterfaces]).toEqual(['IPLC-RTR-MAA:Fa2/0'])
  }
})

describe('healthy baseline, recorded', () => {
  const events = recorded('healthy-baseline')

  it('marks every checked device healthy and blames nothing', () => {
    const { highlight, now } = deriveInvestigation(events, DEVICES)
    expect([...highlight.states.values()].every((s) => s === 'ok' || s === 'checked')).toBe(true)
    expect(highlight.faultInterfaces.size).toBe(0)
    expect(now.kind === 'done' && now.verdict.report.outcome).toBe('no_fault_found')
  })

  it('sends the ping packet along the path towards the destination', () => {
    const { highlight } = deriveInvestigation(events, DEVICES)
    expect(highlight.pings).toHaveLength(1)
    expect(highlight.pings[0]).toMatchObject({
      from: 'CORE-SW-TRV',
      destination: '192.168.200.10',
      route: ['CORE-SW-TRV', 'IPLC-RTR-TRV', 'IPLC-RTR-MAA', 'CORE-SW-MAA'],
      ok: true,
    })
  })

  it('keeps a ping in flight until its answer arrives', () => {
    const moment = until(events, (e) => e.type === 'tool_call' && e.tool === 'ping')
    expect(deriveInvestigation(moment, DEVICES).highlight.pings[0].ok).toBeNull()
  })
})

it('a refused request has no device states', () => {
  const { highlight, now } = deriveInvestigation(recorded('refused-change-request'), DEVICES)
  expect(highlight.states.size).toBe(0)
  expect(now.kind === 'done' && now.verdict.report.outcome).toBe('refused')
})

it('describes calls as plain sentences', () => {
  expect(describeCall('get_path', { source: 'CORE-SW-TRV', destination: '192.168.200.10' })).toBe(
    'Working out the path from CORE-SW-TRV to 192.168.200.10',
  )
  expect(describeCall('ping', { device: 'CORE-SW-TRV', destination: '192.168.200.10' })).toBe(
    'Pinging 192.168.200.10 from CORE-SW-TRV',
  )
  expect(describeCall('get_routes', { device: 'CORE-SW-TRV' })).toBe(
    'Checking the routing table of CORE-SW-TRV',
  )
  expect(describeCall('new_tool', {})).toBe('Running new_tool')
})

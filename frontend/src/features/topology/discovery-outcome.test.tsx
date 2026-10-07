import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Discovery, RunEvent } from '@/api'
import { NotUpdated } from './topology-page'

const base: Discovery = {
  at: '2026-10-07T05:00:00+00:00',
  source: 'unknown',
  devices_ok: [],
  devices_failed: ['IPLC-RTR-MAA: did not answer on the console (TimeoutError)'],
  interface_count: 0,
  link_count: 0,
  findings: [
    'No device answered: the knowledge graph was not changed (it still shows the discovery of 2026-10-06T10:00:00+00:00)',
  ],
  added_links: [],
  removed_links: [],
}

const finished = (extra: Partial<Discovery>): RunEvent[] => [
  { type: 'discovery_done', ...base, ...extra },
]

describe('discovery that reached no device', () => {
  it('says the graph was kept, not emptied', () => {
    render(<NotUpdated events={finished({ graph_updated: false })} />)
    expect(screen.getByRole('alert')).toHaveTextContent(
      'No device answered: the knowledge graph was not changed',
    )
  })

  it('says nothing after a normal run or a run recorded before this existed', () => {
    const { container } = render(<NotUpdated events={finished({ graph_updated: true })} />)
    render(<NotUpdated events={finished({})} />)
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

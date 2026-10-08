import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DeviceStatus, InventoryDetail, InventoryList } from '@/api'
import { InventoryPage } from './inventory-page'
import { statusSentence } from './labels'

// The Inventory page with what the backend sends (fixtures/inventory/samples, written by
// backend tests/test_inventory_view.py): the real lab inventory, FWL-MAA not answering the last
// discovery and ISP-MAA-1 never reached.

const files = import.meta.glob<unknown>('../../../../fixtures/inventory/samples/*.json', {
  eager: true,
  import: 'default',
})
const sample = <T,>(name: string) =>
  structuredClone(Object.entries(files).find(([p]) => p.endsWith(`/${name}.json`))?.[1] as T)
const LIST = sample<InventoryList>('inventory')
const DEVICE = sample<InventoryDetail>('device')

let list: InventoryList = LIST
let check: { status: number; body: unknown } = { status: 200, body: {} }
let posts: { url: string; body: unknown }[] = []

beforeEach(() => {
  list = sample<InventoryList>('inventory')
  posts = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const respond = (status: number, body: unknown) =>
        Promise.resolve(new Response(JSON.stringify(body), { status }))
      if (init?.method === 'POST') {
        posts.push({ url, body: JSON.parse(String(init.body)) })
        return respond(check.status, check.body)
      }
      if (url === '/api/inventory') return respond(200, list)
      if (url === '/api/inventory/IPLC-RTR-MAA') return respond(200, DEVICE)
      return respond(404, { detail: 'unknown' })
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function open(path = '/inventory') {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/inventory/:name" element={<InventoryPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const names = () =>
  screen
    .queryAllByRole('row')
    .slice(0)
    .map((row) => within(row).queryAllByRole('link')[0]?.textContent)
    .filter(Boolean)

describe('the inventory list', () => {
  it('lists every device by site with its status from the last discovery', async () => {
    open()
    const trv = await screen.findByRole('region', { name: 'TRV devices' })
    const maa = screen.getByRole('region', { name: 'MAA devices' })
    expect(within(trv).getAllByRole('link')).toHaveLength(4)
    expect(within(maa).getAllByRole('link')).toHaveLength(4)
    const row = (name: string) => screen.getByRole('link', { name }).closest('tr') as HTMLElement
    expect(within(row('IPLC-RTR-TRV')).getByText('Reached')).toBeInTheDocument()
    expect(within(row('FWL-MAA')).getByText('Not reached')).toBeInTheDocument()
    expect(within(row('FWL-MAA')).getByText(/^last seen /)).toBeInTheDocument()
    expect(within(row('ISP-MAA-1')).getByText('Not discovered yet')).toBeInTheDocument()
  })

  it('shows interfaces that are down and the cases per device', async () => {
    open()
    const row = (await screen.findByRole('link', { name: 'IPLC-RTR-MAA' })).closest(
      'tr',
    ) as HTMLElement
    expect(row).toHaveTextContent('3· 1 down')
    expect(row).toHaveTextContent('MAA-P2P')
  })

  it('counts each status and filters by it', async () => {
    const user = userEvent.setup()
    open()
    await screen.findByRole('region', { name: 'TRV devices' })
    const status = screen.getByRole('group', { name: 'Status' })
    expect(within(status).getByRole('button', { name: /All\s*8/ })).toBeInTheDocument()
    expect(within(status).getByRole('button', { name: /^Reached\s*6/ })).toBeInTheDocument()
    await user.click(within(status).getByRole('button', { name: /Not reached\s*1/ }))
    expect(names()).toEqual(['FWL-MAA'])
  })

  it('finds a device by an alias, and filters by site', async () => {
    const user = userEvent.setup()
    open()
    await user.type(await screen.findByLabelText('Search devices'), 'p2p')
    expect(names()).toEqual(['IPLC-RTR-TRV', 'IPLC-RTR-MAA'])
    await user.clear(screen.getByLabelText('Search devices'))
    await user.selectOptions(screen.getByLabelText('Site'), 'MAA')
    expect(screen.queryByRole('region', { name: 'TRV devices' })).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('Search devices'), 'nothing-like-this')
    expect(screen.getByText('No device matches these filters.')).toBeInTheDocument()
  })

  it('without the knowledge graph it still lists the devices and says why', async () => {
    list = { ...LIST, graph_error: 'knowledge graph not reachable: ConnectionError' }
    open()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The status is unknown: knowledge graph not reachable: ConnectionError',
    )
  })
})

describe('a device', () => {
  it('shows how it is reached, what discovery found, its cases and investigations', async () => {
    open('/inventory/IPLC-RTR-MAA')
    const panel = await screen.findByRole('dialog')
    expect(await within(panel).findByText(/Answered the last discovery/)).toBeInTheDocument()
    expect(within(panel).getByText('EVE-NG console, port 32776')).toBeInTheDocument()
    expect(within(panel).getByText('none (the console needs no login)')).toBeInTheDocument()
    const fa20 = within(panel).getByText('Fa2/0', { selector: 'td' }).closest('tr') as HTMLElement
    expect(fa20).toHaveTextContent('administratively down')
    expect(within(panel).getByRole('link', { name: 'IPLC-RTR-TRV' })).toHaveAttribute(
      'href',
      '/inventory/IPLC-RTR-TRV',
    )
    expect(within(panel).getByText(/IPLC-RTR-TRV on/)).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: /was shut during a change/ })).toHaveAttribute(
      'href',
      `/cases/${DEVICE.cases?.[0].id}`,
    )
    expect(
      within(panel).getByRole('link', { name: /cannot reach 192\.168\.200\.10/ }),
    ).toHaveAttribute('href', '/investigations/inv-fault1')
  })

  it('"Check now" asks the device itself, read-only', async () => {
    const user = userEvent.setup()
    check = {
      status: 200,
      body: { is_error: false, structured: { summary: 'IOS 15.2(4)S7, up 3 days' }, text: '' },
    }
    open('/inventory/IPLC-RTR-MAA')
    await user.click(await screen.findByRole('button', { name: /Check now/ }))
    expect(posts).toEqual([
      {
        url: '/api/tools/network/get_device_facts',
        body: { arguments: { device: 'IPLC-RTR-MAA' } },
      },
    ])
    expect(await screen.findByText('Reached now: IOS 15.2(4)S7, up 3 days')).toBeInTheDocument()
  })

  it('a device that does not answer now says so', async () => {
    const user = userEvent.setup()
    check = { status: 200, body: { is_error: true, structured: null, text: 'TimeoutError' } }
    open('/inventory/IPLC-RTR-MAA')
    await user.click(await screen.findByRole('button', { name: /Check now/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Not reached now: TimeoutError')
  })
})

describe('the status in words', () => {
  const at = '2026-10-07T09:50:00+00:00'
  it('says why a device was not reached and since when', () => {
    const status: DeviceStatus = {
      state: 'not_reached',
      at,
      last_seen: '2026-10-06T08:00:00+00:00',
      error: 'NetmikoAuthenticationException: login failed',
    }
    expect(statusSentence(status)).toMatch(
      /^Did not answer the last discovery \(.+\): NetmikoAuthenticationException: login failed\. Last seen .+; its last known state is shown\.$/,
    )
  })
  it('says what to do for a device never discovered', () => {
    expect(
      statusSentence({ state: 'not_discovered', at: null, last_seen: null, error: null }),
    ).toMatch(/run discovery/)
  })
})

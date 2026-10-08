import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { InventoryDetail, InventoryList, NewDevice } from '@/api'
import { problemWith, splitAliases } from './add-device-rules'
import { InventoryPage } from './inventory-page'

// Adding a device on the Inventory page and removing one added there. The lists are what the
// backend sends (fixtures/inventory/samples).

const files = import.meta.glob<unknown>('../../../../fixtures/inventory/samples/*.json', {
  eager: true,
  import: 'default',
})
const sample = <T,>(name: string) =>
  structuredClone(Object.entries(files).find(([p]) => p.endsWith(`/${name}.json`))?.[1] as T)

const OPTIONS = {
  sites: { TRV: 'Trivandrum', MAA: 'Chennai' },
  roles: ['core', 'wan-router'],
  platforms: ['cisco_ios', 'juniper_junos'],
  credential_profiles: ['lab-ios-admin', 'lab-srx-admin'],
}
let detail: InventoryDetail
let answer: { status: number; body: unknown }
let posts: { url: string; body: unknown }[] = []

beforeEach(() => {
  window.localStorage.clear()
  detail = sample<InventoryDetail>('device')
  answer = {
    status: 200,
    body: { ...sample<InventoryList>('inventory').devices[0], name: 'BLR-RTR-1' },
  }
  posts = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const respond = (status: number, body: unknown) =>
        Promise.resolve(new Response(JSON.stringify(body), { status }))
      if (init?.method === 'POST') {
        posts.push({ url, body: JSON.parse(String(init.body)) })
        return respond(answer.status, answer.body)
      }
      if (url === '/api/inventory') return respond(200, sample('inventory'))
      if (url === '/api/inventory/options') return respond(200, OPTIONS)
      if (url.startsWith('/api/inventory/')) return respond(200, detail)
      return respond(404, { detail: 'unknown' })
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function open(path = '/inventory') {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/inventory/:name" element={<InventoryPage />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// ---------- the rules the form helps with ----------

const DEVICE: NewDevice = {
  name: 'BLR-RTR-1',
  site: 'TRV',
  role: 'wan-router',
  platform: 'cisco_ios',
  port: 32790,
  aliases: [],
  description: '',
  credential_ref: null,
  added_by: 'Deependra',
}

describe('what the form checks before sending', () => {
  it('names the first thing to fix', () => {
    const known = ['TRV', 'MAA']
    expect(problemWith(DEVICE, known)).toBeNull()
    expect(problemWith({ ...DEVICE, name: 'has space' }, known)).toMatch(/^Name/)
    expect(problemWith({ ...DEVICE, aliases: ['ok', 'not ok'] }, known)).toMatch(/not ok/)
    expect(problemWith({ ...DEVICE, site: 'BLR' }, known)).toBe(
      'BLR is a new site: give its name too.',
    )
    expect(problemWith({ ...DEVICE, site: 'BLR', site_name: 'Bengaluru' }, known)).toBeNull()
    expect(problemWith({ ...DEVICE, role: 'WAN Router' }, known)).toMatch(/^Role/)
    expect(problemWith({ ...DEVICE, port: Number('') || NaN }, known)).toMatch(/^Console port/)
    expect(problemWith({ ...DEVICE, added_by: ' ' }, known)).toMatch(/your name/)
  })

  it('reads aliases from a comma-separated list', () => {
    expect(splitAliases(' a, b ,, c ')).toEqual(['a', 'b', 'c'])
  })
})

// ---------- adding ----------

async function fill(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /Add device/ }))
  const dialog = await screen.findByRole('dialog')
  await user.type(within(dialog).getByLabelText('Name'), 'BLR-RTR-1')
  await user.type(within(dialog).getByLabelText(/Other names/), 'BLR-P2P')
  await within(dialog).findByRole('option', { name: 'TRV · Trivandrum' })
  await user.selectOptions(within(dialog).getByLabelText('Site'), 'TRV')
  await user.type(within(dialog).getByLabelText('Role'), 'wan-router')
  await user.type(within(dialog).getByLabelText('EVE-NG console port'), '32790')
  await user.selectOptions(within(dialog).getByLabelText('Login profile'), 'lab-ios-admin')
  await user.type(within(dialog).getByLabelText('Your name'), 'Deependra')
  return dialog
}

// Typing into every field of the form takes a few seconds when the whole suite runs at once.
describe('adding a device', { timeout: 20000 }, () => {
  it('never asks for a password, sends the device and opens it', async () => {
    const user = userEvent.setup()
    open()
    const dialog = await fill(user)
    expect(within(dialog).queryByLabelText(/password/i)).not.toBeInTheDocument()
    expect(dialog.querySelector('input[type="password"]')).toBeNull()
    await user.click(within(dialog).getByRole('button', { name: 'Add device' }))
    expect(posts).toEqual([
      {
        url: '/api/inventory',
        body: {
          name: 'BLR-RTR-1',
          site: 'TRV',
          role: 'wan-router',
          platform: 'cisco_ios',
          port: 32790,
          aliases: ['BLR-P2P'],
          description: '',
          credential_ref: 'lab-ios-admin',
          added_by: 'Deependra',
        },
      },
    ])
    await waitFor(() =>
      expect(screen.getByTestId('where')).toHaveTextContent('/inventory/BLR-RTR-1'),
    )
    expect(window.localStorage.getItem('ainops.reviewer')).toBe('Deependra')
  })

  it('a new site needs its name', async () => {
    const user = userEvent.setup()
    open()
    const dialog = await fill(user)
    await user.selectOptions(within(dialog).getByLabelText('Site'), 'New site…')
    await user.type(within(dialog).getByLabelText('Site code'), 'blr')
    expect(within(dialog).getByText('BLR is a new site: give its name too.')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Add device' })).toBeDisabled()
    await user.type(within(dialog).getByLabelText('Site name'), 'Bengaluru')
    // A console that needs no login: no profile is sent, not an empty one.
    await user.selectOptions(within(dialog).getByLabelText('Login profile'), '')
    await user.click(within(dialog).getByRole('button', { name: 'Add device' }))
    expect(posts[0].body).toMatchObject({
      site: 'BLR',
      site_name: 'Bengaluru',
      credential_ref: null,
    })
  })

  it('shows why the server did not add it', async () => {
    const user = userEvent.setup()
    answer = { status: 409, body: { detail: "console port 32790 is already BLR-OLD's" } }
    open()
    const dialog = await fill(user)
    await user.click(within(dialog).getByRole('button', { name: 'Add device' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      "Not added: console port 32790 is already BLR-OLD's",
    )
  })
})

// ---------- removing ----------

describe('removing a device', () => {
  it('a device added on the page can be removed, with a name', async () => {
    const user = userEvent.setup()
    detail.row.added = { by: 'Deependra', at: '2026-10-08T10:00:00+00:00' }
    answer = { status: 200, body: { removed: 'IPLC-RTR-MAA' } }
    open('/inventory/IPLC-RTR-MAA')
    const panel = await screen.findByRole('dialog')
    expect(await within(panel).findByText(/Added on this page by Deependra/)).toBeInTheDocument()
    await user.click(within(panel).getByRole('button', { name: /Remove from AINOPS/ }))
    const remove = within(panel).getByRole('button', { name: 'Remove' })
    expect(remove).toBeDisabled() // no name yet
    await user.type(within(panel).getByLabelText('Your name'), 'Deependra')
    await user.click(remove)
    expect(posts).toEqual([
      { url: '/api/inventory/IPLC-RTR-MAA/remove', body: { removed_by: 'Deependra' } },
    ])
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/inventory$/))
  })

  it('a hand-written device cannot be removed here', async () => {
    open('/inventory/IPLC-RTR-MAA')
    const panel = await screen.findByRole('dialog')
    expect(await within(panel).findByText(/hand-written inventory file/)).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
  })
})

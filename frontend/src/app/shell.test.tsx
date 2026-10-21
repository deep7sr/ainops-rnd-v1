import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Shell } from '@/app/shell'
import { ThemeProvider } from '@/app/theme/theme-provider'
import { TooltipProvider } from '@/components/ui/tooltip'

// The menu engineers find their way with: everyday pages first, the workings underneath after.

beforeEach(() => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      matches: false,
      addEventListener: () => {},
      removeEventListener: () => {},
    })),
  )
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise(() => {})),
  )
})
afterEach(() => vi.unstubAllGlobals())

function openAt(path: string) {
  render(
    <ThemeProvider>
      <QueryClientProvider client={new QueryClient()}>
        <TooltipProvider>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route element={<Shell />}>
                <Route path="*" element={<p>page</p>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  )
}

const menu = (group: string) => {
  const label = screen.getByText(group)
  const section = label.closest('[data-slot="sidebar-group"]') as HTMLElement
  return within(section)
    .getAllByRole('link')
    .map((link) => [link.textContent, link.getAttribute('href')])
}

describe('the menu', () => {
  it('puts the everyday pages first and the workings underneath in their own group', () => {
    openAt('/')
    expect(menu('Troubleshoot')).toEqual([
      ['Investigate', '/'],
      ['Inventory', '/inventory'],
      ['Cases', '/cases'],
      ['History', '/history'],
    ])
    expect(menu('Behind the scenes')).toEqual([
      ['Network map', '/graph'],
      ['Skills', '/skills'],
      ['AI tools', '/tools'],
      ['Audit log', '/audit'],
    ])
  })

  it('names the page you are on in the header', () => {
    openAt('/graph')
    expect(screen.getByRole('banner')).toHaveTextContent('Network map')
  })
})

describe('the Cases menu item', () => {
  it('shows how many cases wait for review', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        url === '/api/cases'
          ? Promise.resolve(
              new Response(
                JSON.stringify({ cases: [], counts: { pending: 2, approved: 5, rejected: 1 } }),
              ),
            )
          : new Promise(() => {}),
      ),
    )
    openAt('/')
    expect(await screen.findByLabelText('2 waiting for review')).toHaveTextContent('2')
  })
})

describe('the lab badge', () => {
  function healthSays(labSimulated: boolean) {
    const up = { ok: true, tools: 1 }
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        url === '/api/health'
          ? Promise.resolve(
              new Response(
                JSON.stringify({
                  executor: 'live',
                  lab_simulated: labSimulated,
                  llm_model: 'm',
                  llm_configured: true,
                  mcp_network: up,
                  mcp_topology: up,
                  graph: { ok: true, last_discovery: null },
                }),
              ),
            )
          : new Promise(() => {}),
      ),
    )
  }

  it('says the devices are simulated when AINOPS works on the simulated lab', async () => {
    healthSays(true)
    openAt('/')
    expect(await screen.findByText('Lab · simulated devices')).toBeInTheDocument()
    expect(screen.queryByText('Lab · live devices')).not.toBeInTheDocument()
  })

  it('says live devices on the real lab', async () => {
    healthSays(false)
    openAt('/')
    expect(await screen.findByText('Lab · live devices')).toBeInTheDocument()
    expect(screen.queryByText('Lab · simulated devices')).not.toBeInTheDocument()
  })
})

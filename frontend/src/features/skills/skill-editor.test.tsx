import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { configure, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SkillCatalog, SkillForm, ToolCatalog } from '@/api'
import { firstSentence, insertTool, moveStep } from './editor-rules'
import { SkillEditorPage } from './skill-editor'

const TOOLS: ToolCatalog = {
  servers: {
    network: {
      url: 'x',
      ok: true,
      tools: [
        {
          name: 'ping',
          description: 'Send 5 pings FROM the device. Use to test.',
          inputSchema: {},
        },
        { name: 'get_interfaces', description: 'Interfaces and their state.', inputSchema: {} },
      ],
    },
  },
}

const EXISTING: SkillCatalog = {
  skills: [
    {
      name: 'link-check',
      description: 'Use when one link looks down.',
      intro: '',
      steps: ['`ping` the other end.', '`get_interfaces` on both.'],
      tools: ['ping', 'get_interfaces'],
      author: 'Praveen',
      reviewed_by: 'Sudhir',
      path: 'link-check/SKILL.md',
      updated_by: '',
      updated_at: '',
      status: 'live',
      reviewed_at: '2026-10-08T10:00:00Z',
      usage: { count: 0, last_at: null, recent: [] },
      version: 'v1',
    },
  ],
  problems: [],
  tools_checked: true,
}

let saveAnswer: { status: number; body: unknown }
let toolsChecked: boolean
let writes: { method: string; url: string; body: unknown }[]

function checked(form: SkillForm) {
  const steps = form.steps.filter((s) => s.trim())
  const problems = [
    ...(form.name.trim() ? [] : ["name '' must be lowercase letters"]),
    ...(steps.some((s) => s.includes('`nope`')) ? ['`nope` is not a tool'] : []),
    ...(form.description.trim() ? [] : ['description is missing']),
  ]
  return {
    skill: problems.length
      ? null
      : {
          ...form,
          steps,
          tools: [],
          author: '',
          reviewed_by: '',
          path: `${form.name}/SKILL.md`,
          updated_by: '',
          updated_at: '',
        },
    problems,
    markdown: '',
    tools_checked: toolsChecked,
  }
}

beforeEach(() => {
  window.localStorage.clear()
  saveAnswer = { status: 201, body: { ...EXISTING.skills[0], version: 'v2' } }
  toolsChecked = true
  writes = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const respond = (status: number, body: unknown) =>
        Promise.resolve(new Response(JSON.stringify(body), { status }))
      const body = init?.body ? (JSON.parse(String(init.body)) as unknown) : undefined
      if (url === '/api/skills/check') return respond(200, checked(body as SkillForm))
      if (init?.method === 'POST' || init?.method === 'PUT') {
        writes.push({ method: init.method, url, body })
        return respond(saveAnswer.status, saveAnswer.body)
      }
      if (url === '/api/tools') return respond(200, TOOLS)
      if (url === '/api/skills') return respond(200, EXISTING)
      return respond(404, { detail: 'unknown' })
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

// Typing a whole skill is slow when the full suite runs in parallel on the lab laptop.
vi.setConfig({ testTimeout: 30_000 })
configure({ asyncUtilTimeout: 5_000 })

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}

function open(path: string) {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/skills/new" element={<SkillEditorPage />} />
          <Route path="/skills/:name/edit" element={<SkillEditorPage />} />
          <Route path="*" element={<p>elsewhere</p>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function writeNew(user: ReturnType<typeof userEvent.setup>, step = '`ping` the far end.') {
  await user.type(screen.getByLabelText('Name'), 'link-check')
  await user.type(screen.getByLabelText('When should AINOPS use it?'), 'Use when a link is down.')
  await user.type(screen.getByLabelText('Step 1'), step)
  await user.clear(screen.getByLabelText('Your name'))
  await user.type(screen.getByLabelText('Your name'), 'Praveen')
}

describe('writing a new skill', () => {
  it('saves only once the backend has checked it, then opens the saved skill', async () => {
    const user = userEvent.setup()
    open('/skills/new')
    const save = screen.getByRole('button', { name: 'Save skill' })
    expect(save).toBeDisabled()
    await writeNew(user)
    await waitFor(() => expect(save).toBeEnabled())
    await user.click(save)
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/skills/link-check'))
    expect(writes).toEqual([
      {
        method: 'POST',
        url: '/api/skills',
        body: {
          skill: {
            name: 'link-check',
            description: 'Use when a link is down.',
            intro: '',
            steps: ['`ping` the far end.'],
          },
          by: 'Praveen',
          version: null,
        },
      },
    ])
    expect(window.localStorage.getItem('ainops.reviewer')).toBe('Praveen')
  })

  it('an empty new form lists no problems yet', async () => {
    open('/skills/new')
    await new Promise((r) => setTimeout(r, 600))
    expect(screen.queryByRole('region', { name: 'To fix before saving' })).not.toBeInTheDocument()
  })

  it('lists what to fix and keeps Save off', async () => {
    const user = userEvent.setup()
    open('/skills/new')
    await writeNew(user, '`nope` the router.')
    await waitFor(() =>
      expect(screen.getByRole('region', { name: 'To fix before saving' })).toHaveTextContent(
        /^To fix before saving`nope` is not a tool$/,
      ),
    )
    expect(screen.getByRole('button', { name: 'Save skill' })).toBeDisabled()
  })

  it('needs a name before saving', async () => {
    const user = userEvent.setup()
    open('/skills/new')
    await writeNew(user)
    await user.clear(screen.getByLabelText('Your name'))
    await new Promise((r) => setTimeout(r, 500))
    expect(screen.getByRole('button', { name: 'Save skill' })).toBeDisabled()
  })

  it('cannot save while the tool names cannot be checked', async () => {
    toolsChecked = false
    const user = userEvent.setup()
    open('/skills/new')
    await writeNew(user)
    expect(await screen.findByRole('status')).toHaveTextContent('cannot be saved')
  })

  it('shows the skill as the page will, while it is written', async () => {
    const user = userEvent.setup()
    open('/skills/new')
    await user.type(screen.getByLabelText('Name'), 'ospf-flap')
    const preview = screen.getByRole('region', { name: 'Preview' })
    expect(within(preview).getByRole('heading', { level: 2 })).toHaveTextContent('OSPF flap')
    expect(screen.getByText(/Shown as “OSPF flap”/)).toBeInTheDocument()
  })

  it('inserts a tool where the cursor is', async () => {
    const user = userEvent.setup()
    open('/skills/new')
    const step = screen.getByLabelText('Step 1')
    await user.type(step, 'Run  on the router')
    await user.keyboard('{ArrowLeft>14/}') // the cursor between the two spaces
    const picker = await screen.findByRole('combobox', { name: 'Insert a tool into step 1' })
    await waitFor(() => expect(picker).toBeEnabled())
    expect(
      within(picker).getByRole('option', { name: /ping · Send 5 pings FROM the device\./ }),
    ).toBeInTheDocument()
    await user.selectOptions(picker, 'ping')
    expect(step).toHaveValue('Run `ping` on the router')
  })

  it('adds, moves and removes steps', async () => {
    const user = userEvent.setup()
    open('/skills/new')
    await user.type(screen.getByLabelText('Step 1'), 'first')
    await user.click(screen.getByRole('button', { name: 'Add step' }))
    await user.type(screen.getByLabelText('Step 2'), 'second')
    expect(screen.getByRole('button', { name: 'Move step 1 up' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Move step 2 up' }))
    expect(screen.getByLabelText('Step 1')).toHaveValue('second')
    expect(screen.getByLabelText('Step 2')).toHaveValue('first')
    await user.click(screen.getByRole('button', { name: 'Remove step 1' }))
    expect(screen.getByLabelText('Step 1')).toHaveValue('first')
    expect(screen.getByRole('button', { name: 'Remove step 1' })).toBeDisabled() // keep one
    for (let i = 0; i < 11; i++) await user.click(screen.getByRole('button', { name: 'Add step' }))
    expect(screen.getAllByLabelText(/^Step \d+$/)).toHaveLength(12)
    expect(screen.getByRole('button', { name: 'Add step' })).toBeDisabled()
  })
})

describe('editing a skill', () => {
  it('starts from the saved skill, keeps its name and sends the version it started from', async () => {
    saveAnswer = { status: 200, body: { ...EXISTING.skills[0], version: 'v2' } }
    const user = userEvent.setup()
    open('/skills/link-check/edit')
    const name = await screen.findByLabelText('Name')
    expect(name).toHaveValue('link-check')
    expect(name).toBeDisabled()
    expect(screen.getByLabelText('Step 2')).toHaveValue('`get_interfaces` on both.')
    expect(screen.getByText(/makes the skill a draft again/)).toBeInTheDocument()
    await user.type(screen.getByLabelText('Your name'), 'Deependra')
    await user.type(screen.getByLabelText('About (optional)'), 'Both ends.')
    const save = screen.getByRole('button', { name: 'Save changes' })
    await waitFor(() => expect(save).toBeEnabled())
    await user.click(save)
    await waitFor(() => expect(writes).toHaveLength(1))
    expect(writes[0]).toMatchObject({
      method: 'PUT',
      url: '/api/skills/link-check',
      body: { by: 'Deependra', version: 'v1', skill: { intro: 'Both ends.' } },
    })
  })

  it('says when someone else saved first, and offers the latest version', async () => {
    saveAnswer = { status: 409, body: { detail: "'link-check' was changed by someone else" } }
    const user = userEvent.setup()
    open('/skills/link-check/edit')
    await user.type(await screen.findByLabelText('Your name'), 'Deependra')
    await user.type(screen.getByLabelText('About (optional)'), 'x')
    const save = screen.getByRole('button', { name: 'Save changes' })
    await waitFor(() => expect(save).toBeEnabled())
    await user.click(save)
    expect(await screen.findByRole('alert')).toHaveTextContent('changed by someone else')
    expect(screen.getByRole('button', { name: 'Reload the latest version' })).toBeInTheDocument()
  })

  it('cannot save when nothing changed, and an untouched form shows no problems', async () => {
    const user = userEvent.setup()
    open('/skills/link-check/edit')
    await user.type(await screen.findByLabelText('Your name'), 'Deependra')
    await new Promise((r) => setTimeout(r, 600))
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
    expect(screen.queryByRole('region', { name: 'To fix before saving' })).not.toBeInTheDocument()
  })

  it('says so when there is no such skill', async () => {
    open('/skills/missing/edit')
    expect(await screen.findByRole('alert')).toHaveTextContent('no skill named “missing”')
  })
})

describe('form rules', () => {
  it('puts a tool at the cursor with spaces only where needed', () => {
    expect(insertTool('Run  on it', 4, 'ping')).toEqual({ text: 'Run `ping` on it', cursor: 10 })
    expect(insertTool('Run', null, 'ping')).toEqual({ text: 'Run `ping`', cursor: 10 })
    expect(insertTool('', 0, 'ping')).toEqual({ text: '`ping`', cursor: 6 })
    expect(insertTool('on it', 0, 'ping')).toEqual({ text: '`ping` on it', cursor: 7 })
    expect(insertTool('ab', 99, 'x')).toEqual({ text: 'ab `x`', cursor: 6 })
  })

  it('moves a step within the list only', () => {
    expect(moveStep(['a', 'b', 'c'], 1, -1)).toEqual(['b', 'a', 'c'])
    expect(moveStep(['a', 'b', 'c'], 1, 1)).toEqual(['a', 'c', 'b'])
    expect(moveStep(['a', 'b'], 0, -1)).toEqual(['a', 'b'])
    expect(moveStep(['a', 'b'], 1, 1)).toEqual(['a', 'b'])
  })

  it('keeps the first sentence of a tool description', () => {
    expect(firstSentence('Send 5 pings FROM the device. Use to test.')).toBe(
      'Send 5 pings FROM the device.',
    )
    expect(firstSentence('Interfaces: up or down')).toBe('Interfaces:')
    expect(firstSentence(undefined)).toBe('')
  })
})

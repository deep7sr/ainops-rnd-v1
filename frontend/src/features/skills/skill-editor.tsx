import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Loader2, Plus, TriangleAlert, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import {
  ApiError,
  api,
  type Skill,
  type SkillCatalog,
  type SkillForm,
  type ToolCatalog,
} from '@/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { rememberName, savedName } from '@/lib/your-name'
import { cn } from '@/lib/utils'
import { firstSentence, insertTool, MAX_DESCRIPTION, MAX_STEPS, moveStep } from './editor-rules'
import { skillTitle } from './labels'
import { SkillView } from './skill-view'

// Writing a skill on the page: a form on the left, the skill as the Skills page will show it on
// the right. The backend checks every change with the same rules the agent's loader uses, so
// Save is only possible for a skill AINOPS can use. Saving writes skills/<name>/SKILL.md.

const fieldLabel = 'block text-xs font-semibold text-foreground'
const hint = 'text-xs text-muted-foreground'

const EMPTY: SkillForm = { name: '', description: '', intro: '', steps: [''] }

/** The form's value, settled for `ms` (the check runs on the settled value). */
function useSettled<T>(value: T, ms = 400): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), ms)
    return () => window.clearTimeout(timer)
  }, [value, ms])
  return settled
}

function ToolPicker({
  tools,
  onPick,
  step,
}: {
  tools: ToolCatalog | undefined
  onPick: (tool: string) => void
  step: number
}) {
  const servers = Object.entries(tools?.servers ?? {}).filter(([, s]) => s.ok && s.tools.length)
  return (
    <select
      aria-label={`Insert a tool into step ${step}`}
      value=""
      disabled={servers.length === 0}
      onChange={(event) => {
        if (event.target.value) onPick(event.target.value)
      }}
      className="h-7 w-full min-w-0 rounded-md border bg-card px-2 text-xs text-muted-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-60 sm:w-60"
    >
      <option value="">{servers.length ? 'Insert a tool…' : 'Tools not available'}</option>
      {servers.map(([server, { tools: list }]) => (
        <optgroup key={server} label={server === 'network' ? 'Device checks' : 'Network map'}>
          {list.map((tool) => (
            <option key={tool.name} value={tool.name}>
              {tool.name} · {firstSentence(tool.description)}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  )
}

function StepField({
  index,
  count,
  value,
  tools,
  onChange,
  onMove,
  onRemove,
}: {
  index: number
  count: number
  value: string
  tools: ToolCatalog | undefined
  onChange: (text: string) => void
  onMove: (by: -1 | 1) => void
  onRemove: () => void
}) {
  const box = useRef<HTMLTextAreaElement>(null)
  const cursor = useRef<number | null>(null)
  const remember = () => {
    cursor.current = box.current?.selectionStart ?? null
  }
  const number = index + 1
  return (
    <li className="flex gap-3">
      <span className="mt-1.5 flex size-6 shrink-0 items-center justify-center rounded-full border bg-card text-xs font-semibold tabular-nums">
        {number}
      </span>
      <div className="min-w-0 flex-1 space-y-1.5">
        <Textarea
          ref={box}
          aria-label={`Step ${number}`}
          value={value}
          onChange={(event) => {
            onChange(event.target.value)
            cursor.current = event.target.selectionStart
          }}
          onSelect={remember}
          onKeyUp={remember}
          onClick={remember}
          placeholder={
            number === 1
              ? 'e.g. `get_interfaces` on the router: the interface must be up.'
              : 'What to check next, and what the result means'
          }
          className="min-h-16 text-sm"
          maxLength={2000}
        />
        <div className="flex flex-wrap items-center gap-1.5">
          <ToolPicker
            tools={tools}
            step={number}
            onPick={(tool) => {
              const next = insertTool(value, cursor.current, tool)
              onChange(next.text)
              cursor.current = next.cursor
              requestAnimationFrame(() => {
                box.current?.focus()
                box.current?.setSelectionRange(next.cursor, next.cursor)
              })
            }}
          />
          <span className="flex-1" />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={`Move step ${number} up`}
            disabled={index === 0}
            onClick={() => onMove(-1)}
          >
            <ArrowUp aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={`Move step ${number} down`}
            disabled={index === count - 1}
            onClick={() => onMove(1)}
          >
            <ArrowDown aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={`Remove step ${number}`}
            disabled={count === 1}
            onClick={onRemove}
          >
            <X aria-hidden="true" />
          </Button>
        </div>
      </div>
    </li>
  )
}

/** What the preview shows before the backend has checked the form. */
function previewOf(form: SkillForm, checked: Skill | null): Skill {
  if (checked) return checked
  return {
    name: form.name.trim().toLowerCase() || 'new-skill',
    description: form.description.trim() || 'Say when AINOPS should use this skill.',
    intro: form.intro.trim(),
    steps: form.steps.filter((s) => s.trim()).length
      ? form.steps.filter((s) => s.trim())
      : ['Add the first step.'],
    tools: [],
    author: '',
    reviewed_by: '',
    path: `${form.name.trim().toLowerCase() || 'new-skill'}/SKILL.md`,
    updated_by: '',
    updated_at: '',
    status: 'draft',
    reviewed_at: '',
  }
}

export function SkillEditor({
  start,
  version,
  tools,
}: {
  /** The skill being edited; a new skill starts empty. */
  start: SkillForm | null
  version: string | null
  tools: ToolCatalog | undefined
}) {
  const editing = start !== null
  const [initial] = useState<SkillForm>(start ?? EMPTY)
  const [form, setForm] = useState<SkillForm>(initial)
  const [by, setBy] = useState(savedName)
  const settled = useSettled(form)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const checked = useQuery({
    queryKey: ['skill-check', settled],
    queryFn: () => api.checkSkill(settled),
    placeholderData: keepPreviousData,
  })
  const upToDate = settled === form && !checked.isPlaceholderData && !checked.isFetching
  // A form nobody has typed in yet shows no problems: they would only say it is empty.
  const pristine = form === initial
  const problems = pristine ? [] : (checked.data?.problems ?? [])
  const canSave =
    !pristine &&
    upToDate &&
    checked.data?.skill != null && // null whenever there is a problem
    by.trim().length > 0

  const save = useMutation({
    mutationFn: () => {
      const request = { skill: form, by: by.trim(), version }
      return editing ? api.editSkill(form.name, request) : api.createSkill(request)
    },
    onSuccess: (saved) => {
      rememberName(by.trim())
      void queryClient.invalidateQueries({ queryKey: ['skills'] })
      void navigate(`/skills/${saved.name}`)
    },
  })
  const conflict = save.error instanceof ApiError && save.error.status === 409

  const set = (change: Partial<SkillForm>) => setForm((f) => ({ ...f, ...change }))
  const setStep = (index: number, text: string) =>
    setForm((f) => ({ ...f, steps: f.steps.map((s, i) => (i === index ? text : s)) }))

  const descriptionLength = form.description.replace(/\s+/g, ' ').trim().length

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <form
        aria-label={editing ? 'Edit skill' : 'New skill'}
        onSubmit={(event) => {
          event.preventDefault()
          if (canSave) save.mutate()
        }}
        className="space-y-5 rounded-lg border bg-card p-5 sm:p-6"
      >
        <div className="space-y-1.5">
          <label htmlFor="skill-name" className={fieldLabel}>
            Name
          </label>
          <Input
            id="skill-name"
            value={form.name}
            disabled={editing}
            onChange={(event) => set({ name: event.target.value })}
            placeholder="interface-flapping"
            className="font-mono"
            maxLength={64}
            autoComplete="off"
          />
          <p className={hint}>
            {editing
              ? 'A skill keeps its name. To rename it, make a new skill.'
              : 'Lowercase words joined by hyphens.'}
            {form.name.trim() && <> Shown as “{skillTitle(form.name.trim().toLowerCase())}”.</>}
          </p>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-baseline justify-between gap-2">
            <label htmlFor="skill-description" className={fieldLabel}>
              When should AINOPS use it?
            </label>
            <span
              className={cn(
                'text-xs tabular-nums',
                descriptionLength > MAX_DESCRIPTION
                  ? 'text-status-critical'
                  : 'text-muted-foreground',
              )}
            >
              {descriptionLength}/{MAX_DESCRIPTION}
            </span>
          </div>
          <Textarea
            id="skill-description"
            value={form.description}
            onChange={(event) => set({ description: event.target.value })}
            placeholder="Use when an interface goes up and down, or users report short drops on one link."
            className="min-h-16 text-sm"
            maxLength={1000}
          />
          <p className={hint}>
            Start with “Use when…”. AINOPS reads this sentence for every question to decide whether
            the skill fits, so be specific.
          </p>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="skill-intro" className={fieldLabel}>
            About <span className="font-normal text-muted-foreground">(optional)</span>
          </label>
          <Textarea
            id="skill-intro"
            value={form.intro}
            onChange={(event) => set({ intro: event.target.value })}
            placeholder="What healthy looks like, or the idea behind the steps."
            className="min-h-14 text-sm"
            maxLength={2000}
          />
        </div>

        <fieldset className="min-w-0 space-y-3">
          <legend className={fieldLabel}>Steps</legend>
          <p className={hint}>
            One check per step, in the order an engineer would do them. Name the tool to use (in
            `backticks`, or with “Insert a tool”). A line starting with “- ” is a sub-point.
          </p>
          <ol aria-label="Steps" className="space-y-4">
            {form.steps.map((step, index) => (
              <StepField
                key={index}
                index={index}
                count={form.steps.length}
                value={step}
                tools={tools}
                onChange={(text) => setStep(index, text)}
                onMove={(by) => set({ steps: moveStep(form.steps, index, by) })}
                onRemove={() => set({ steps: form.steps.filter((_, i) => i !== index) })}
              />
            ))}
          </ol>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={form.steps.length >= MAX_STEPS}
            onClick={() => set({ steps: [...form.steps, ''] })}
          >
            <Plus aria-hidden="true" /> Add step
          </Button>
          {form.steps.length >= MAX_STEPS && (
            <p className={hint}>
              At most {MAX_STEPS} steps: split a longer procedure in two skills.
            </p>
          )}
        </fieldset>

        <div className="space-y-1.5 border-t pt-4">
          <label htmlFor="skill-by" className={fieldLabel}>
            Your name
          </label>
          <Input
            id="skill-by"
            value={by}
            onChange={(event) => setBy(event.target.value)}
            maxLength={80}
            autoComplete="name"
            className="max-w-xs"
          />
          <p className={hint}>
            Kept with the skill and in the Audit log.
            {editing &&
              ' Saving a change makes the skill a draft again: AINOPS stops using it until it is reviewed and made live.'}
          </p>
        </div>

        {checked.data && !checked.data.tools_checked && (
          <p role="status" className="flex items-start gap-2 text-sm text-status-warning">
            <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            The MCP servers are not running, so the tool names cannot be checked and the skill
            cannot be saved. Start them, then save.
          </p>
        )}
        {problems.length > 0 && (
          <section
            aria-label="To fix before saving"
            className="rounded-md border border-status-warning-border bg-status-warning-bg px-3 py-2"
          >
            <p className="text-xs font-semibold text-status-warning">To fix before saving</p>
            <ul className="mt-1 ml-4 list-disc space-y-0.5 text-sm">
              {problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          </section>
        )}
        {save.isError && (
          <div role="alert" className="space-y-2 text-sm text-status-critical">
            <p>Not saved: {save.error.message}</p>
            {conflict && editing && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void queryClient.invalidateQueries({ queryKey: ['skills'] })}
              >
                Reload the latest version
              </Button>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={!canSave || save.isPending}>
            {save.isPending && (
              <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
            )}
            {editing ? 'Save changes' : 'Save skill'}
          </Button>
          <Button asChild variant="ghost">
            <Link to={editing ? `/skills/${form.name}` : '/skills'}>Cancel</Link>
          </Button>
          {!upToDate && <span className={hint}>Checking…</span>}
        </div>
      </form>

      <section aria-label="Preview" className="space-y-2 lg:sticky lg:top-4 lg:self-start">
        <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          Preview: how the Skills page will show it
        </p>
        <div className="rounded-lg border border-dashed bg-card p-5 sm:p-6">
          <SkillView skill={previewOf(form, upToDate ? (checked.data?.skill ?? null) : null)} />
        </div>
      </section>
    </div>
  )
}

function formOf(skill: Skill): SkillForm {
  return {
    name: skill.name,
    description: skill.description,
    intro: skill.intro,
    steps: skill.steps,
  }
}

/** /skills/new and /skills/<name>/edit */
export function SkillEditorPage() {
  const { name } = useParams()
  const catalog = useQuery({ queryKey: ['skills'], queryFn: api.skills, enabled: Boolean(name) })
  const tools = useQuery({ queryKey: ['tools'], queryFn: api.tools })
  const skill = useMemo(
    () => catalog.data?.skills.find((s) => s.name === name),
    [catalog.data, name],
  )
  return (
    <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
      <div className="space-y-1">
        <Link
          to={name ? `/skills/${name}` : '/skills'}
          className={cn(hint, 'hover:text-foreground')}
        >
          ← {name ? skillTitle(name) : 'Skills'}
        </Link>
        <h1 className="text-xl font-semibold">
          {name ? `Edit “${skillTitle(name)}”` : 'New skill'}
        </h1>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Write the checklist the way you would explain it to a new engineer. It is saved as a
          draft: try it on a question, have it reviewed, then make it live for AINOPS to use.
        </p>
      </div>
      {!name ? (
        <SkillEditor start={null} version={null} tools={tools.data} />
      ) : catalog.isPending ? (
        <Skeleton className="h-96 w-full" />
      ) : catalog.isError ? (
        <p role="alert" className="text-sm text-status-critical">
          Could not load the skill: {catalog.error.message}
        </p>
      ) : skill ? (
        <EditorFor key={skill.version ?? ''} skill={skill} tools={tools.data} />
      ) : (
        <p role="alert" className="text-sm text-muted-foreground">
          There is no skill named “{name}” that can be edited here. A skill that needs fixing is
          fixed in its file.
        </p>
      )}
    </div>
  )
}

/** Keyed by the version: when the latest version is reloaded, the form starts again from it. */
function EditorFor({
  skill,
  tools,
}: {
  skill: SkillCatalog['skills'][number]
  tools: ToolCatalog | undefined
}) {
  return <SkillEditor start={formOf(skill)} version={skill.version} tools={tools} />
}

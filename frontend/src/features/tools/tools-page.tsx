import { useMutation, useQuery } from '@tanstack/react-query'
import { CircleCheck, CircleX, Loader2, Network, Play, Router, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { api, type JsonSchema, type McpTool } from '@/api'
import { JsonView } from '@/components/json-view'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

const SERVER_INFO: Record<string, { label: string; icon: typeof Router; text: string }> = {
  network: {
    label: 'Network MCP server',
    icon: Router,
    text: 'Logs into the lab routers and firewalls. Read-only tools, commands from a reviewed list.',
  },
  topology: {
    label: 'Topology MCP server',
    icon: Network,
    text: 'Answers from the knowledge graph (Neo4j). Never touches a device.',
  },
}

function typeOf(schema: JsonSchema): string {
  if (schema.anyOf)
    return schema.anyOf
      .map(typeOf)
      .filter((t) => t !== 'null')
      .join(' | ')
  return Array.isArray(schema.type) ? schema.type.join(' | ') : (schema.type ?? 'any')
}

function TryIt({ server, tool }: { server: string; tool: McpTool }) {
  const properties = Object.entries(tool.inputSchema.properties ?? {})
  const [values, setValues] = useState<Record<string, string>>({})
  const call = useMutation({
    mutationFn: () => {
      const args: Record<string, unknown> = {}
      for (const [name, schema] of properties) {
        const raw = values[name]?.trim()
        if (!raw) continue
        args[name] = typeOf(schema).includes('integer') ? Number(raw) : raw
      }
      return api.callTool(server, tool.name, args)
    },
  })
  const summary = call.data?.structured?.summary

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault()
        call.mutate()
      }}
    >
      {properties.length === 0 && <p className="text-sm text-muted-foreground">No inputs.</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        {properties.map(([name, schema]) => (
          <div key={name} className="space-y-1">
            <Label htmlFor={`in-${tool.name}-${name}`}>
              {name}
              {tool.inputSchema.required?.includes(name) && (
                <span className="text-status-critical"> *</span>
              )}
            </Label>
            <Input
              id={`in-${tool.name}-${name}`}
              value={values[name] ?? ''}
              placeholder={
                schema.default !== undefined && schema.default !== null
                  ? String(schema.default)
                  : ''
              }
              onChange={(event) => setValues((v) => ({ ...v, [name]: event.target.value }))}
              className="font-mono text-sm"
            />
          </div>
        ))}
      </div>
      <Button type="submit" disabled={call.isPending}>
        {call.isPending ? (
          <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
        ) : (
          <Play aria-hidden="true" />
        )}
        Call the tool
      </Button>
      {call.isError && (
        <p role="alert" className="text-sm text-status-critical">
          {call.error.message}
        </p>
      )}
      {call.data && (
        <div className="space-y-2">
          <p
            className={cn(
              'flex items-start gap-1.5 text-sm',
              call.data.is_error ? 'text-status-critical' : 'text-foreground',
            )}
          >
            {call.data.is_error ? (
              <CircleX aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            ) : (
              <CircleCheck
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-status-healthy"
              />
            )}
            {call.data.is_error ? call.data.text : String(summary ?? 'done')}
          </p>
          {!call.data.is_error && <JsonView value={call.data.structured} className="max-h-96" />}
        </div>
      )}
    </form>
  )
}

function ToolDetail({ server, tool }: { server: string; tool: McpTool }) {
  const [showRaw, setShowRaw] = useState(false)
  const properties = Object.entries(tool.inputSchema.properties ?? {})
  const definition = {
    name: tool.name,
    description: tool.description,
    inputSchema: tool.inputSchema,
    annotations: tool.annotations,
  }
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">{tool.title ?? tool.name}</h2>
          <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">{tool.name}</code>
          {tool.annotations?.readOnlyHint && (
            <Badge variant="outline" className="gap-1 text-status-healthy">
              <ShieldCheck aria-hidden="true" className="size-3" /> read-only
            </Badge>
          )}
          {tool.annotations?.destructiveHint === false && (
            <Badge variant="outline">not destructive</Badge>
          )}
        </div>
        <p className="text-sm whitespace-pre-line text-muted-foreground">{tool.description}</p>
      </div>

      <div>
        <h3 className="text-xs font-semibold tracking-wider text-eyebrow uppercase">Inputs</h3>
        <table className="mt-2 w-full text-sm">
          <tbody className="divide-y">
            {properties.map(([name, schema]) => (
              <tr key={name}>
                <td className="py-1.5 pr-3 align-top font-mono text-xs">
                  {name}
                  {tool.inputSchema.required?.includes(name) && (
                    <span className="text-status-critical"> *</span>
                  )}
                </td>
                <td className="py-1.5 pr-3 align-top font-mono text-xs text-muted-foreground">
                  {typeOf(schema)}
                </td>
                <td className="py-1.5 align-top text-muted-foreground">{schema.description}</td>
              </tr>
            ))}
            {properties.length === 0 && (
              <tr>
                <td className="py-1.5 text-muted-foreground">No inputs.</td>
              </tr>
            )}
          </tbody>
        </table>
        <button
          type="button"
          onClick={() => setShowRaw((v) => !v)}
          className="mt-2 text-xs text-primary hover:underline"
        >
          {showRaw ? 'Hide' : 'Show'} the exact definition the LLM receives
        </button>
        {showRaw && <JsonView value={definition} className="mt-2" />}
      </div>

      <div className="rounded-lg border bg-muted/30 p-4">
        <h3 className="mb-3 text-xs font-semibold tracking-wider text-eyebrow uppercase">
          Try it (no AI involved)
        </h3>
        <TryIt key={`${server}/${tool.name}`} server={server} tool={tool} />
      </div>
    </div>
  )
}

export function ToolsPage() {
  const catalog = useQuery({ queryKey: ['tools'], queryFn: api.tools })
  const [selected, setSelected] = useState<{ server: string; tool: string } | null>(null)
  const servers = Object.entries(catalog.data?.servers ?? {})
  const current =
    selected ??
    (servers[0]?.[1].tools[0] ? { server: servers[0][0], tool: servers[0][1].tools[0].name } : null)
  const tool = current
    ? catalog.data?.servers[current.server]?.tools.find((t) => t.name === current.tool)
    : undefined

  return (
    <div className="mx-auto max-w-[1400px] space-y-5 px-6 py-6">
      <div>
        <h1 className="text-xl font-semibold">AI tools</h1>
        <p className="text-sm text-muted-foreground">
          Everything the agent can do, served by the MCP servers. Each tool is a name, a description
          and typed inputs: the LLM picks tools by reading these definitions. The device commands
          stay inside the servers.
        </p>
      </div>
      {catalog.isPending ? (
        <Skeleton className="h-96 w-full" />
      ) : catalog.isError ? (
        <p role="alert" className="text-sm text-status-critical">
          Could not load the tools: {catalog.error.message}
        </p>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
          <nav aria-label="MCP servers and tools" className="space-y-4">
            {servers.map(([name, server]) => {
              const info = SERVER_INFO[name] ?? { label: name, icon: Router, text: '' }
              const Icon = info.icon
              return (
                <section key={name} className="rounded-lg border bg-card">
                  <header className="border-b px-4 py-3">
                    <p className="flex items-center gap-2 font-semibold">
                      <Icon aria-hidden="true" className="size-4 text-primary" /> {info.label}
                      <span
                        className={cn(
                          'ml-auto size-2 rounded-full',
                          server.ok ? 'bg-status-healthy' : 'bg-status-critical',
                        )}
                        aria-label={server.ok ? 'running' : 'not reachable'}
                      />
                    </p>
                    <p className="mt-0.5 font-mono text-xs text-muted-foreground">{server.url}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{info.text}</p>
                  </header>
                  <ul className="p-1.5">
                    {server.tools.map((t) => {
                      const active = current?.server === name && current.tool === t.name
                      return (
                        <li key={t.name}>
                          <button
                            type="button"
                            onClick={() => setSelected({ server: name, tool: t.name })}
                            aria-current={active}
                            className={cn(
                              'flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-sm hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none',
                              active && 'bg-accent font-medium',
                            )}
                          >
                            <span>{t.title ?? t.name}</span>
                            <code className="font-mono text-[11px] text-muted-foreground">
                              {t.name}
                            </code>
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                </section>
              )
            })}
          </nav>
          <div className="min-w-0 rounded-lg border bg-card p-5">
            {tool && current ? (
              <ToolDetail server={current.server} tool={tool} />
            ) : (
              <p className="text-sm text-muted-foreground">No tools available.</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleCheck, CircleX, Loader2, RefreshCw, Trash2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { api, type InventoryRow } from '@/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { CaseStatusBadge } from '@/features/cases/case-view'
import { cn } from '@/lib/utils'
import { rememberName, savedName } from '@/lib/your-name'
import { platformName, statusSentence } from './labels'
import { DeviceStatusBadge } from './status-badge'

// One device: how AINOPS reaches it, its status, a live read-only check on demand, and what the
// knowledge graph, the cases and past investigations know about it.

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="eyebrow">{title}</h3>
      {children}
    </section>
  )
}

/** Asks the device itself, read-only (show version), through the network MCP server. */
function CheckNow({ device }: { device: string }) {
  const check = useMutation({
    mutationFn: () => api.callTool('network', 'get_device_facts', { device }),
  })
  const summary = (check.data?.structured as { summary?: string } | null | undefined)?.summary
  return (
    <div className="space-y-2">
      <Button variant="outline" size="sm" onClick={() => check.mutate()} disabled={check.isPending}>
        {check.isPending ? (
          <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
        ) : (
          <RefreshCw aria-hidden="true" />
        )}
        Check now
      </Button>
      <p className="text-xs text-muted-foreground">
        Asks the device for its facts (show version), read-only, through the network MCP server. It
        is written to the audit log and never changes the device.
      </p>
      {check.isError && (
        <p role="alert" className="text-sm text-status-critical">
          Could not check: {check.error.message}
        </p>
      )}
      {check.data &&
        (check.data.is_error ? (
          <p role="alert" className="flex items-start gap-1.5 text-sm text-status-critical">
            <CircleX aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            Not reached now: {check.data.text}
          </p>
        ) : (
          <p className="flex items-start gap-1.5 text-sm">
            <CircleCheck
              aria-hidden="true"
              className="mt-0.5 size-4 shrink-0 text-status-healthy"
            />
            Reached now: {summary || 'the device answered'}
          </p>
        ))}
    </div>
  )
}

/** Remove a device that was added on this page (the hand-written ones stay in their file). */
function Remove({ row, onRemoved }: { row: InventoryRow; onRemoved: () => void }) {
  const [asking, setAsking] = useState(false)
  const [name, setName] = useState(savedName)
  const queryClient = useQueryClient()
  const remove = useMutation({
    mutationFn: () => api.removeDevice(row.name, name.trim()),
    onSuccess: () => {
      rememberName(name.trim())
      void queryClient.invalidateQueries({ queryKey: ['inventory'] })
      onRemoved()
    },
  })
  if (!asking) {
    return (
      <Button variant="outline" size="sm" onClick={() => setAsking(true)}>
        <Trash2 aria-hidden="true" /> Remove from AINOPS
      </Button>
    )
  }
  return (
    <div className="space-y-2 rounded-md border border-status-critical-border p-3">
      <p className="text-sm">
        Remove <span className="font-medium">{row.name}</span>? AINOPS stops logging in to it, and
        it leaves the network map at the next discovery. Its cases and past investigations stay.
      </p>
      <label htmlFor="removed-by" className="text-xs font-semibold">
        Your name
      </label>
      <Input
        id="removed-by"
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={80}
      />
      <div className="flex gap-2">
        <Button
          variant="destructive"
          size="sm"
          disabled={!name.trim() || remove.isPending}
          onClick={() => remove.mutate()}
        >
          Remove
        </Button>
        <Button variant="outline" size="sm" onClick={() => setAsking(false)}>
          Cancel
        </Button>
      </div>
      {remove.isError && (
        <p role="alert" className="text-sm text-status-critical">
          Not removed: {remove.error.message}
        </p>
      )}
    </div>
  )
}

export function DeviceSheet({ name, onClose }: { name: string | null; onClose: () => void }) {
  const detail = useQuery({
    queryKey: ['inventory', name],
    queryFn: () => api.inventoryDevice(name as string),
    enabled: name !== null,
  })
  const data = detail.data
  const row = data?.row

  return (
    <Sheet open={name !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{row?.name ?? name}</SheetTitle>
          <SheetDescription>
            {row
              ? `${row.description || row.role} · ${row.site} ${row.site_name} · ${platformName(row.platform)}`
              : ' '}
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-6">
          {detail.isPending && <Skeleton className="h-40 w-full" />}
          {detail.isError && (
            <p role="alert" className="text-sm text-status-critical">
              {detail.error.message}
            </p>
          )}
          {row && data && (
            <>
              <Section title="Status">
                <DeviceStatusBadge status={row.status} />
                <p className="text-sm">{statusSentence(row.status)}</p>
                {row.status.state === 'not_discovered' && (
                  <p className="text-sm">
                    <Link to="/graph" className="text-primary underline-offset-4 hover:underline">
                      Run discovery on the Network map
                    </Link>{' '}
                    to learn its interfaces and links.
                  </p>
                )}
                <CheckNow device={row.name} />
              </Section>

              <Section title="How AINOPS reaches it">
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
                  <dt className="text-muted-foreground">Connection</dt>
                  <dd>{row.connection}</dd>
                  <dt className="text-muted-foreground">Login profile</dt>
                  <dd>
                    {row.credential_ref ? (
                      <code className="font-mono text-xs">{row.credential_ref}</code>
                    ) : (
                      'none (the console needs no login)'
                    )}
                  </dd>
                  {row.aliases.length > 0 && (
                    <>
                      <dt className="text-muted-foreground">Also called</dt>
                      <dd>{row.aliases.join(', ')}</dd>
                    </>
                  )}
                </dl>
                <p className="text-xs text-muted-foreground">
                  Passwords stay in the server's .env file; AINOPS never shows them.
                </p>
              </Section>

              <Section title="Where it comes from">
                {row.added ? (
                  <>
                    <p className="text-sm">
                      Added on this page by {row.added.by} ·{' '}
                      {new Date(row.added.at).toLocaleString()}
                    </p>
                    <Remove row={row} onRemoved={onClose} />
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    The hand-written inventory file (lab/inventory.yaml): changed there, not here.
                  </p>
                )}
              </Section>

              <Section title="Interfaces (last discovery)">
                {data.interfaces.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Not known yet.</p>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted-foreground">
                        <th className="py-1 font-medium">Interface</th>
                        <th className="py-1 font-medium">Status</th>
                        <th className="py-1 font-medium">Address</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.interfaces.map((i) => (
                        <tr key={i.name} className="border-t">
                          <td className="py-1 font-mono text-xs">{i.name}</td>
                          <td
                            className={cn(
                              'py-1',
                              i.status !== 'up' && i.ipv4.length > 0 && 'text-status-warning',
                            )}
                          >
                            {i.status}
                          </td>
                          <td className="py-1 font-mono text-xs">{i.ipv4.join(', ') || '–'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </Section>

              {data.links.length > 0 && (
                <Section title="Connected to">
                  <ul className="space-y-1 text-sm">
                    {data.links.map((link) => {
                      const mine = link.a === row.name
                      return (
                        <li key={link.key}>
                          <span className="font-mono text-xs">
                            {mine ? link.a_interface : link.b_interface}
                          </span>{' '}
                          →{' '}
                          <Link
                            to={`/inventory/${encodeURIComponent(mine ? link.b : link.a)}`}
                            className="text-primary underline-offset-4 hover:underline"
                          >
                            {mine ? link.b : link.a}
                          </Link>{' '}
                          <span className="font-mono text-xs">
                            {mine ? link.b_interface : link.a_interface}
                          </span>
                          {link.subnet && (
                            <span className="text-xs text-muted-foreground"> ({link.subnet})</span>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                </Section>
              )}

              {data.ospf_peers.length > 0 && (
                <Section title="Normal OSPF neighbours">
                  <ul className="space-y-1 text-sm">
                    {data.ospf_peers.map((peer) => (
                      <li key={`${peer.peer}-${peer.interface}`}>
                        {peer.peer} on <span className="font-mono text-xs">{peer.interface}</span>{' '}
                        <span className="text-xs text-muted-foreground">({peer.address})</span>
                      </li>
                    ))}
                  </ul>
                  <p className="text-xs text-muted-foreground">
                    Seen FULL at discovery: one missing later is reported as a problem.
                  </p>
                </Section>
              )}

              <Section title="Cases">
                {data.cases === null ? (
                  <p className="text-sm text-muted-foreground">Could not read the cases.</p>
                ) : data.cases.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No case involves this device.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {data.cases.map((item) => (
                      <li key={item.id} className="space-y-0.5">
                        <CaseStatusBadge status={item.status} />{' '}
                        <Link
                          to={`/cases/${item.id}`}
                          className="text-primary underline-offset-4 hover:underline"
                        >
                          {item.root_cause ?? item.question}
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>

              <Section title="Investigations that checked it">
                {data.investigations.length === 0 ? (
                  <p className="text-sm text-muted-foreground">None yet.</p>
                ) : (
                  <ul className="space-y-1.5 text-sm">
                    {data.investigations.map((run) => (
                      <li key={run.id}>
                        <Link
                          to={`/investigations/${run.id}`}
                          className="text-primary underline-offset-4 hover:underline"
                        >
                          {run.title}
                        </Link>
                        <span className="block text-xs text-muted-foreground">
                          {new Date(run.started_at).toLocaleString()} ·{' '}
                          {run.outcome?.replaceAll('_', ' ') ?? 'unfinished'} · {run.checks} check
                          {run.checks === 1 ? '' : 's'} here
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

import { useQuery } from '@tanstack/react-query'
import { Search, Server } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { api, type DeviceState, type InventoryRow } from '@/api'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { AddDeviceDialog } from './add-device-dialog'
import { DeviceSheet } from './device-sheet'
import { platformName } from './labels'
import { DeviceStatusBadge } from './status-badge'

// Every device AINOPS knows: where it is, how it is reached, and what the last discovery found.
// Built to stay usable with many devices: search, filters, and grouping by site. Status comes from
// the last discovery; "Check now" in a device's panel asks the device itself.

const STATES: { state: DeviceState | 'all'; label: string }[] = [
  { state: 'all', label: 'All' },
  { state: 'reached', label: 'Reached' },
  { state: 'not_reached', label: 'Not reached' },
  { state: 'not_discovered', label: 'Not discovered yet' },
]

function matches(row: InventoryRow, text: string) {
  const wanted = text.trim().toLowerCase()
  if (!wanted) return true
  return [row.name, ...row.aliases, row.role, row.description, row.platform]
    .join(' ')
    .toLowerCase()
    .includes(wanted)
}

function Row({ row }: { row: InventoryRow }) {
  const navigate = useNavigate()
  const { interfaces, cases } = row
  return (
    <tr
      className="cursor-pointer border-t hover:bg-accent"
      onClick={() => void navigate(`/inventory/${encodeURIComponent(row.name)}`)}
    >
      <td className="px-4 py-2.5">
        <Link
          to={`/inventory/${encodeURIComponent(row.name)}`}
          onClick={(event) => event.stopPropagation()}
          className="font-medium underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-none"
        >
          {row.name}
        </Link>
        {row.aliases.length > 0 && (
          <span className="ml-2 text-xs text-muted-foreground">{row.aliases.join(', ')}</span>
        )}
        {row.added && (
          <span className="ml-2 rounded border px-1 py-px text-[10px] text-muted-foreground">
            added here
          </span>
        )}
        {row.description && (
          <span className="block text-xs text-muted-foreground">{row.description}</span>
        )}
      </td>
      <td className="px-4 py-2.5 text-sm">{row.role}</td>
      <td className="hidden px-4 py-2.5 text-sm md:table-cell">{platformName(row.platform)}</td>
      <td className="px-4 py-2.5">
        <DeviceStatusBadge status={row.status} />
      </td>
      <td className="hidden px-4 py-2.5 text-sm tabular-nums sm:table-cell">
        {row.status.state === 'not_discovered' ? (
          <span className="text-muted-foreground">–</span>
        ) : (
          <>
            {interfaces.total}
            {interfaces.addressed_down > 0 && (
              <span className="ml-1.5 text-status-warning">· {interfaces.addressed_down} down</span>
            )}
          </>
        )}
      </td>
      <td className="hidden px-4 py-2.5 text-sm lg:table-cell">
        {cases === null ? (
          <span className="text-muted-foreground">?</span>
        ) : cases.total === 0 ? (
          <span className="text-muted-foreground">–</span>
        ) : (
          <>
            {cases.total}
            {cases.pending > 0 && (
              <span className="ml-1.5 text-status-warning">· {cases.pending} pending</span>
            )}
          </>
        )}
      </td>
    </tr>
  )
}

export function InventoryPage() {
  const { name } = useParams()
  const navigate = useNavigate()
  const list = useQuery({ queryKey: ['inventory'], queryFn: api.inventory })
  const [text, setText] = useState('')
  const [site, setSite] = useState('all')
  const [state, setState] = useState<DeviceState | 'all'>('all')

  const rows = useMemo(() => list.data?.devices ?? [], [list.data])
  const counts = useMemo(() => {
    const out: Record<string, number> = { all: rows.length }
    for (const row of rows) out[row.status.state] = (out[row.status.state] ?? 0) + 1
    return out
  }, [rows])
  const shown = rows.filter(
    (row) =>
      matches(row, text) &&
      (site === 'all' || row.site === site) &&
      (state === 'all' || row.status.state === state),
  )
  const bySite = Object.entries(list.data?.sites ?? {})
    .map(([code, label]) => ({ code, label, rows: shown.filter((r) => r.site === code) }))
    .filter((group) => group.rows.length > 0)
  const discovery = list.data?.discovery

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <Server aria-hidden="true" className="size-5" /> Inventory
          </h1>
          <p className="text-sm text-muted-foreground">
            Every device AINOPS can reach. Status is from the last discovery
            {discovery ? ` (${new Date(discovery.at).toLocaleString()})` : ''}; open a device to
            check it now. Run discovery again from the{' '}
            <Link to="/graph" className="text-primary underline-offset-4 hover:underline">
              Network map
            </Link>
            .
          </p>
        </div>
        <AddDeviceDialog />
      </div>

      {list.data?.graph_error && (
        <p role="alert" className="rounded-md border px-4 py-2 text-sm text-status-warning">
          The status is unknown: {list.data.graph_error}. The devices are listed from the inventory.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full sm:w-72">
          <Search
            aria-hidden="true"
            className="absolute top-2.5 left-2.5 size-4 text-muted-foreground"
          />
          <Input
            aria-label="Search devices"
            placeholder="Search name, alias, role…"
            value={text}
            onChange={(event) => setText(event.target.value)}
            className="pl-8"
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Site</span>
          <select
            value={site}
            onChange={(event) => setSite(event.target.value)}
            className="h-9 rounded-md border bg-background px-2 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            <option value="all">All sites</option>
            {Object.entries(list.data?.sites ?? {}).map(([code, label]) => (
              <option key={code} value={code}>
                {code} · {label}
              </option>
            ))}
          </select>
        </label>
        <div role="group" aria-label="Status" className="flex flex-wrap gap-1.5">
          {STATES.map((option) => (
            <button
              key={option.state}
              type="button"
              aria-pressed={state === option.state}
              onClick={() => setState(option.state)}
              className={cn(
                'rounded-full border px-3 py-1 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none',
                state === option.state
                  ? 'border-primary bg-secondary font-medium'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {option.label}
              <span className="ml-1.5 tabular-nums">{counts[option.state] ?? 0}</span>
            </button>
          ))}
        </div>
      </div>

      {list.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : list.isError ? (
        <p role="alert" className="text-sm text-status-critical">
          Could not load the inventory: {list.error.message}
        </p>
      ) : bySite.length === 0 ? (
        <p className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
          No device matches these filters.
        </p>
      ) : (
        <div className="space-y-5">
          {bySite.map((group) => (
            <section key={group.code} aria-label={`${group.code} devices`}>
              <h2 className="mb-1.5 eyebrow">
                {group.code} · {group.label}
                <span className="ml-2 font-normal tracking-normal normal-case">
                  {group.rows.length} device{group.rows.length === 1 ? '' : 's'}
                </span>
              </h2>
              <div className="overflow-x-auto rounded-lg border bg-card">
                <table className="w-full text-left">
                  <thead>
                    <tr className="text-xs text-muted-foreground">
                      <th className="px-4 py-2 font-medium">Device</th>
                      <th className="px-4 py-2 font-medium">Role</th>
                      <th className="hidden px-4 py-2 font-medium md:table-cell">Vendor / OS</th>
                      <th className="px-4 py-2 font-medium">Status</th>
                      <th className="hidden px-4 py-2 font-medium sm:table-cell">Interfaces</th>
                      <th className="hidden px-4 py-2 font-medium lg:table-cell">Cases</th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.rows.map((row) => (
                      <Row key={row.name} row={row} />
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
      )}

      <DeviceSheet name={name ?? null} onClose={() => void navigate('/inventory')} />
    </div>
  )
}

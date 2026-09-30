import { useQuery } from '@tanstack/react-query'
import { api } from '@/api'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

export function AuditPage() {
  const audit = useQuery({ queryKey: ['audit'], queryFn: api.audit, refetchInterval: 5000 })

  return (
    <div className="mx-auto max-w-[1400px] space-y-5 px-6 py-6">
      <div>
        <h1 className="text-xl font-semibold">Audit log</h1>
        <p className="text-sm text-muted-foreground">
          Every call to the network MCP server, by the agent, discovery or a person: the tool, the
          device, the exact command and the outcome. Device output is never stored here.
        </p>
      </div>
      {audit.isPending ? (
        <Skeleton className="h-96 w-full" />
      ) : audit.isError ? (
        <p role="alert" className="text-sm text-status-critical">
          Could not load the audit log: {audit.error.message}
        </p>
      ) : audit.data.length === 0 ? (
        <p className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">
          No tool calls yet.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                {['Time', 'Tool', 'Device', 'Command sent', 'Outcome', 'Data', 'Duration'].map(
                  (h) => (
                    <th key={h} className="px-3 py-2 font-medium">
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="divide-y">
              {audit.data.map((entry, index) => (
                <tr key={`${entry.at}-${index}`} className="align-top">
                  <td className="px-3 py-2 text-xs whitespace-nowrap text-muted-foreground tabular-nums">
                    {new Date(entry.at).toLocaleTimeString()}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{entry.tool}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{entry.device}</td>
                  <td className="px-3 py-2 font-mono text-xs">{entry.command ?? '—'}</td>
                  <td className="px-3 py-2">
                    <span
                      className={cn(
                        'font-medium',
                        entry.outcome === 'ok'
                          ? 'text-status-healthy'
                          : entry.outcome === 'refused'
                            ? 'text-status-critical'
                            : 'text-status-warning',
                      )}
                    >
                      {entry.outcome}
                    </span>
                    <p className="text-xs text-muted-foreground">{entry.summary ?? entry.reason}</p>
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground uppercase">
                    {entry.source}
                  </td>
                  <td className="px-3 py-2 text-xs whitespace-nowrap text-muted-foreground tabular-nums">
                    {entry.duration_ms} ms
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

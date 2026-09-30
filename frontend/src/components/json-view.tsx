import { cn } from '@/lib/utils'

/** Pretty-printed JSON in a scrollable box (tool results, tool definitions). */
export function JsonView({ value, className }: { value: unknown; className?: string }) {
  return (
    <pre
      className={cn(
        'max-h-72 overflow-auto rounded-md border bg-muted/60 p-3 font-mono text-[11.5px] leading-relaxed',
        className,
      )}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

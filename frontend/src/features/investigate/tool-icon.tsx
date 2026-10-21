import { cn } from '@/lib/utils'
import { FALLBACK_TOOL_ICON, TOOL_ICON } from './tool-icons'

/** The icon of an agent tool (decorative: the tool's name or sentence is always next to it). */
export function ToolIcon({ tool, className }: { tool: string; className?: string }) {
  const Icon = TOOL_ICON[tool] ?? FALLBACK_TOOL_ICON
  return (
    <Icon aria-hidden="true" data-tool-icon={tool} className={cn('size-4 shrink-0', className)} />
  )
}

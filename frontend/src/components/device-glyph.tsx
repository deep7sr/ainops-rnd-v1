// What a device is, drawn the way network diagrams draw it: a round router, a firewall as a brick
// wall, a core switch as a box, the ISP as a globe. One SVG per kind, the same in the map, Inventory,
// the device panel and the timeline. The role decides the kind (lab/*.yaml `role`); a role AINOPS
// does not know yet gets a plain device box, never a wrong picture.

import type { CSSProperties, ReactNode } from 'react'
import { glyphKind, type GlyphKind } from '@/lib/device-kind'
import { cn } from '@/lib/utils'

// A light fill inside the outline, so the shape reads as solid at small sizes.
const tint = (opacity: number) => ({ fill: 'currentColor', fillOpacity: opacity })

const DRAWINGS: Record<GlyphKind, ReactNode> = {
  // A router puck with the two crossing arrows.
  router: (
    <>
      <path d="M4 12v8c0 2.8 5.4 5 12 5s12-2.2 12-5v-8" {...tint(0.16)} />
      <ellipse cx="16" cy="12" rx="12" ry="5" {...tint(0.08)} />
      <path d="M8.5 10.5h7m-2.2-2 2.2 2-2.2 2M23.5 13.5h-7m2.2-2-2.2 2 2.2 2" />
    </>
  ),
  firewall: (
    <>
      <rect x="4" y="6" width="24" height="20" rx="2" {...tint(0.16)} />
      <path d="M4 12.7h24M4 19.3h24M12 6v6.7M20 6v6.7M8 12.7v6.6M16 12.7v6.6M24 12.7v6.6M12 19.3V26M20 19.3V26" />
    </>
  ),
  // A layer-3 switch: a box seen from above, with two arrows.
  core: (
    <>
      <path d="M3 12l5-5h21l-5 5z" {...tint(0.08)} />
      <path d="M24 12l5-5v12l-5 5z" {...tint(0.24)} />
      <rect x="3" y="12" width="21" height="12" {...tint(0.16)} />
      <path d="M7 16h11m-2.2-2 2.2 2-2.2 2M20 20.2H9m2.2-2-2.2 2 2.2 2" />
    </>
  ),
  isp: (
    <>
      <circle cx="16" cy="16" r="11.5" {...tint(0.16)} />
      <ellipse cx="16" cy="16" rx="5" ry="11.5" />
      <path d="M5 12h22M5 20h22" />
    </>
  ),
  switch: (
    <>
      <rect x="4" y="19" width="24" height="7" rx="1.5" {...tint(0.16)} />
      <rect x="4" y="12.5" width="24" height="7" rx="1.5" {...tint(0.12)} />
      <rect x="4" y="6" width="24" height="7" rx="1.5" {...tint(0.08)} />
      <path d="M8 9.5h2M8 16h2M8 22.5h2" />
    </>
  ),
  host: (
    <>
      <rect x="11" y="4" width="17" height="12" rx="1.5" {...tint(0.08)} />
      {/* The front screen hides the back one. */}
      <rect x="4" y="10" width="17" height="12" rx="1.5" style={{ fill: 'var(--card)' }} />
      <rect x="4" y="10" width="17" height="12" rx="1.5" {...tint(0.16)} />
      <path d="M9 27h7M12.5 22v5" />
    </>
  ),
  device: (
    <>
      <rect x="4" y="9" width="24" height="14" rx="2" {...tint(0.12)} />
      <path d="M9 16h.01M13 16h.01M17 16h.01M21 16h2" />
    </>
  ),
}

/**
 * The picture for a device role. Decorative by default (the name is always written next to it);
 * pass `title` where the picture stands alone.
 */
export function DeviceGlyph({
  deviceRole,
  className,
  style,
  title,
  x,
  y,
  size,
}: {
  /** The role from the inventory, e.g. "wan-router". */
  deviceRole: string
  className?: string
  style?: CSSProperties
  title?: string
  /** Inside another SVG (the map): where to draw it, in that SVG's units. */
  x?: number
  y?: number
  size?: number
}) {
  const kind = glyphKind(deviceRole)
  return (
    <svg
      viewBox="0 0 32 32"
      x={x}
      y={y}
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      data-glyph={kind}
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      className={cn('shrink-0', className)}
      style={style}
    >
      {title && <title>{title}</title>}
      {DRAWINGS[kind]}
    </svg>
  )
}

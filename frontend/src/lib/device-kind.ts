// Which picture a device gets, from its role in the inventory (lab/*.yaml `role`). Drawn by
// src/components/device-glyph.tsx.

export type GlyphKind = 'isp' | 'router' | 'core' | 'firewall' | 'switch' | 'host' | 'device'

/** The kind of picture for a role from the inventory, e.g. "wan-router" -> router. */
export function glyphKind(role: string): GlyphKind {
  const r = role.toLowerCase()
  if (r.startsWith('isp')) return 'isp'
  if (r.includes('firewall') || r === 'fw') return 'firewall'
  if (r.startsWith('core') || r.includes('distribution')) return 'core'
  if (r.includes('router')) return 'router'
  if (r.includes('switch') || r.startsWith('access')) return 'switch'
  if (['host', 'server', 'servers', 'lan', 'pc', 'users'].includes(r)) return 'host'
  return 'device'
}

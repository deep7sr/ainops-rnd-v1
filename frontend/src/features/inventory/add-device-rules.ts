import type { NewDevice } from '@/api'

// What the "Add device" form checks before sending. The server checks everything again
// (backend inventory_edit.py: names used once, one device per console port, known login
// profiles) and its answer is the one that counts.

const NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$/
const SITE = /^[A-Z0-9]{2,10}$/
const ROLE = /^[a-z0-9][a-z0-9-]{0,30}$/

/** "a, b ,, c" -> ["a", "b", "c"] */
export function splitAliases(text: string): string[] {
  return text
    .split(',')
    .map((a) => a.trim())
    .filter(Boolean)
}

/** The first thing to fix before the device can be added, or null when it can be sent. */
export function problemWith(device: NewDevice, knownSites: string[]): string | null {
  if (!NAME.test(device.name)) return 'Name: letters, digits, dot, dash or underscore.'
  const bad = device.aliases.find((a) => !NAME.test(a))
  if (bad) return `Alias "${bad}": letters, digits, dot, dash or underscore.`
  if (device.aliases.length > 5) return 'At most 5 aliases.'
  if (!SITE.test(device.site)) return 'Site code: 2 to 10 capital letters or digits, e.g. BLR.'
  if (!knownSites.includes(device.site) && !device.site_name?.trim())
    return `${device.site} is a new site: give its name too.`
  if (!ROLE.test(device.role)) return 'Role: small letters, digits and dashes, e.g. wan-router.'
  if (!Number.isInteger(device.port) || device.port < 1 || device.port > 65535)
    return 'Console port: a number from 1 to 65535.'
  if (!device.added_by.trim()) return 'Type your name: every change says who made it.'
  return null
}

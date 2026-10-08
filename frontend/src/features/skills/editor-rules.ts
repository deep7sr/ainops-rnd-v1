// Small rules of the skill form, kept apart so they are easy to test.

export const MAX_STEPS = 12
export const MAX_DESCRIPTION = 300

/** Put `tool` (in backticks) where the cursor is, with a space on each side when needed. */
export function insertTool(
  text: string,
  cursor: number | null,
  tool: string,
): { text: string; cursor: number } {
  const at = cursor === null ? text.length : Math.min(Math.max(cursor, 0), text.length)
  const before = text.slice(0, at)
  const after = text.slice(at)
  const left = before === '' || /\s$/.test(before) ? '' : ' '
  const right = after === '' || /^\s/.test(after) ? '' : ' '
  const inserted = `${left}\`${tool}\`${right}`
  return { text: before + inserted + after, cursor: before.length + inserted.length }
}

/** Swap step `index` with the one before (-1) or after (+1). */
export function moveStep(steps: string[], index: number, by: -1 | 1): string[] {
  const target = index + by
  if (target < 0 || target >= steps.length) return steps
  const next = [...steps]
  ;[next[index], next[target]] = [next[target], next[index]]
  return next
}

/** "Reads the routing table. Use it to..." -> "Reads the routing table." */
export function firstSentence(text: string | undefined): string {
  const flat = (text ?? '').replace(/\s+/g, ' ').trim()
  const end = flat.search(/[.:](\s|$)/)
  return end === -1 ? flat : flat.slice(0, end + 1)
}

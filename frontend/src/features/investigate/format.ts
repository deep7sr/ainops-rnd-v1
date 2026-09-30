/** 850 -> "850 ms", 12400 -> "12.4 s". */
export function formatMs(ms: number | null): string {
  if (ms === null) return ''
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

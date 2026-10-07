/** The first line of a step, without backticks: short enough for the "Now" line. */
export function stepHeadline(text: string): string {
  return (text.split('\n')[0] ?? '').replaceAll('`', '')
}

// An investigation that ends with an error shows the server's message, which is often the AI
// service's raw reply (the live run of 2026-10-22 showed a whole 429 JSON with the account's id).
// This says it in plain words; the raw text stays one click away, with account ids masked.

export interface ErrorText {
  /** What happened, in plain words. */
  said: string
  /** The message as the server sent it (account ids masked); null when `said` is that already. */
  detail: string | null
}

/** "21m42.048s" -> "about 22 minutes"; "35.2s" -> "about a minute". */
function waitText(match: RegExpExecArray | null): string | null {
  if (!match) return null
  const minutes = Number(match[1] ?? 0) + Number(match[2]) / 60
  const rounded = Math.max(1, Math.round(minutes))
  return rounded === 1 ? 'about a minute' : `about ${rounded} minutes`
}

const mask = (message: string) => message.replace(/\borg_[A-Za-z0-9]+/g, 'org_…')

export function errorText(message: string): ErrorText {
  const wait = waitText(/try again in (?:(\d+)m)?([\d.]+)s/i.exec(message))
  const later = wait ? ` Try again in ${wait}.` : ' Try again later.'
  let said: string | null = null
  if (/rate.?limit|\b429\b/i.test(message)) {
    said = /per day|\bTPD\b/i.test(message)
      ? `The AI service has used up its daily limit, so AINOPS could not finish.${later}`
      : `The AI service is busy (too many requests), so AINOPS could not finish.${later}`
  } else if (/\b413\b|too large|context.?length/i.test(message)) {
    said = 'The investigation grew too long for the AI service, so AINOPS could not finish.'
  } else if (/\b401\b|authenticat|api.?key/i.test(message)) {
    said = 'The AI service did not accept the API key, so AINOPS could not finish.'
  } else if (/APIConnectionError|APITimeoutError|connection error|timed out/i.test(message)) {
    said = 'AINOPS could not reach the AI service, so it could not finish.'
  }
  return said ? { said, detail: mask(message) } : { said: mask(message), detail: null }
}

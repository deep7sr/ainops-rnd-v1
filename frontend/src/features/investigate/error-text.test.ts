import { describe, expect, it } from 'vitest'
import { deriveInvestigation } from './derive'
import { errorText } from './error-text'

describe('an error in plain words', () => {
  it('the daily limit of the AI service, with the wait', () => {
    // The live run of 2026-10-22 (inv-88c9b4bc); the account id is made up here.
    const raw =
      "OpenAIRateLimitError: Error code: 429 - {'error': {'message': 'Rate limit reached for model " +
      '`openai/gpt-oss-120b` in organization `org_01abcdefghij` service tier `on_demand` on tokens ' +
      "per day (TPD): Limit 200000, Used 195809, Requested 7205. Please try again in 21m42.048s.'}}"
    const text = errorText(raw)
    expect(text.said).toBe(
      'The AI service has used up its daily limit, so AINOPS could not finish. Try again in about 22 minutes.',
    )
    expect(text.detail).toContain('Rate limit reached')
    expect(text.detail).not.toContain('org_01abcdefghij')
  })

  it('a short rate limit, a request too large, a refused key, no connection', () => {
    expect(errorText('Error code: 429 - Please try again in 35.2s').said).toMatch(
      /busy .* Try again in about a minute\.$/,
    )
    expect(errorText('Error code: 413 - Request too large').said).toMatch(/too long/)
    expect(errorText('AuthenticationError: Error code: 401').said).toMatch(/API key/)
    expect(errorText('APIConnectionError: Connection error.').said).toMatch(/could not reach/)
  })

  it('anything else is shown as it is', () => {
    expect(errorText('The graph is empty')).toEqual({ said: 'The graph is empty', detail: null })
  })
})

it('the investigation says it in plain words, the raw message one click away', () => {
  const view = deriveInvestigation(
    [
      { type: 'started', question: 'Why?', tools: [], at_ms: 0 },
      { type: 'error', message: 'Error code: 429 - tokens per day (TPD). Try again in 1m3s.' },
    ],
    [],
  )
  expect(view.error).toBe(
    'The AI service has used up its daily limit, so AINOPS could not finish. Try again in about a minute.',
  )
  expect(view.now).toMatchObject({ kind: 'stopped', detail: expect.stringContaining('429') })
})

import type { CaseReview, ReviewRequest } from '@/api'

// The review rules the form helps with before saving. The server checks them again
// (backend cases.py review_case) and its answer is the one that counts.

type Action = CaseReview['action']

/** What is still missing before the review can be saved (null when it can be). */
export function missing(action: Action | null, form: ReviewRequest): string | null {
  if (!action) return 'Choose approve, correct or reject.'
  if (action === 'reject' && !form.reason?.trim()) return 'Say why the case is rejected.'
  if (action === 'correct' && !form.root_cause?.trim()) return 'Write the real root cause.'
  if (!form.reviewer.trim()) return 'Type your name: every review says who made it.'
  return null
}

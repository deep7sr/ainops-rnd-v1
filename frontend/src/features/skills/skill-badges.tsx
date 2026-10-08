import type { SkillStatus } from '@/api'
import { Badge } from '@/components/ui/badge'

/** For skill events from before skills had a status: whether someone reviewed it. */
export function ReviewBadge({ reviewedBy }: { reviewedBy: string }) {
  return reviewedBy ? (
    <Badge variant="outline" className="border-status-healthy-border text-status-healthy">
      Reviewed by {reviewedBy}
    </Badge>
  ) : (
    <Badge variant="outline" className="border-status-warning-border text-status-warning">
      Draft · not reviewed
    </Badge>
  )
}

const STATUS_LABEL: Record<SkillStatus, string> = {
  live: 'Live',
  draft: 'Draft',
  off: 'Off',
}

const STATUS_STYLE: Record<SkillStatus, string> = {
  live: 'border-status-healthy-border bg-status-healthy-bg text-status-healthy',
  draft: 'border-status-warning-border bg-status-warning-bg text-status-warning',
  off: 'border-status-unknown-border bg-status-unknown-bg text-status-unknown',
}

/** Live: AINOPS uses it. Draft: not yet (it can be tried). Off: not used. */
export function SkillStatusBadge({ status }: { status: SkillStatus }) {
  return (
    <Badge variant="outline" className={STATUS_STYLE[status]}>
      {STATUS_LABEL[status]}
    </Badge>
  )
}

export function NeedsFixingBadge() {
  return (
    <Badge variant="outline" className="border-status-critical-border text-status-critical">
      Needs fixing
    </Badge>
  )
}

/** A skill as an investigation used it: live, or a draft (or off skill) being tried. Runs from
 * before skills had a status only say whether it was reviewed. */
export function SkillBadge({ status, reviewedBy }: { status: string; reviewedBy: string }) {
  if (status === 'live') return <SkillStatusBadge status="live" />
  if (status === 'draft' || status === 'off')
    return (
      <Badge variant="outline" className={STATUS_STYLE[status]}>
        {STATUS_LABEL[status]} · being tried
      </Badge>
    )
  return <ReviewBadge reviewedBy={reviewedBy} />
}

import { Badge } from '@/components/ui/badge'

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

export function NeedsFixingBadge() {
  return (
    <Badge variant="outline" className="border-status-critical-border text-status-critical">
      Needs fixing
    </Badge>
  )
}

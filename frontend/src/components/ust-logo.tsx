import { cn } from '@/lib/utils'

// The UST logo, an exact vector copy of the official file ust_logo_iteration_1_ll_rgb_pos.pdf
// (brand.ust.com, supplied by the user 2026-09-28): the PDF's path, cropped to its artwork box.
// It takes the text colour (`currentColor`): soft black in the light theme, white in the dark theme,
// matching the brand's positive and reversed versions. Do not change the shape or proportions.
const LOGO_PATH =
  'M111.337 18.193H135.173V42.029H111.337ZM150 102.401L96.510 102.401L96.510 117.014L114.804 117.014L114.804 163.772L131.706 163.772L131.706 117.014L150 117.014ZM33.840 126.961L28.511 125.667C22.569 124.201 19.855 122.489 19.855 119.556C19.855 117.343 22.694 114.968 28.511 114.968C33.899 114.968 38.227 117.304 41.778 120.502L52.213 112.061C47.803 104.686 38.212 100.611 28.598 100.611C12.347 100.611 3.065 109.496 3.065 119.990C3.065 128.098 8.852 136.523 23.793 140.232L29.385 141.612C34.889 142.992 36.904 144.022 36.904 146.696C36.904 150.030 32.493 151.884 26.938 151.884C20.520 151.884 15.739 149.295 11.513 145.012L1.078 153.452C5.631 161.712 17.443 165.726 27.026 165.726C44.150 165.726 54.393 157.734 54.393 146.262C54.393 137.550 48.869 130.584 33.840 126.961M38.474 0L55.305 0L55.305 36.291C55.305 53.164 45.206 63.326 27.783 63.326C9.669 63.326 -0 52.732 -0 36.291L-0 0L16.832 0L16.832 36.371C16.832 43.617 20.968 47.743 27.696 47.743C34.424 47.743 38.474 43.617 38.474 36.371Z'

export function UstLogo({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 150 165.727"
      role="img"
      aria-label="UST"
      fill="currentColor"
      className={cn('h-8 w-auto shrink-0', className)}
    >
      <path d={LOGO_PATH} />
    </svg>
  )
}

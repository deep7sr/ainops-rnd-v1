// Checks the design tokens in src/index.css (ARCHITECTURE 17.1: WCAG 2.1 AA contrast).
//
// The test reads the CSS source itself, so it checks exactly what the browser gets. If a colour change
// breaks contrast, this test names the pair, the theme and the ratio.

import { parse, wcagContrast, type Rgb } from 'culori'
import { describe, expect, test } from 'vitest'
import { DURATION, EASE_IN_OUT, EASE_OUT } from '@/lib/motion'
import css from '../index.css?raw'

type Theme = 'light' | 'dark'

// Variables that are the same in both themes and therefore only defined once, in :root.
const THEME_INDEPENDENT = new Set([
  '--radius',
  '--motion-fast',
  '--motion-base',
  '--motion-slow',
  '--motion-ease-out',
  '--motion-ease-in-out',
])

// WCAG 2.1 AA: 4.5:1 for normal text (1.4.3), 3:1 for UI parts such as focus rings (1.4.11).
const TEXT_MIN = 4.5
const UI_MIN = 3

const SURFACES = ['background', 'card', 'popover', 'muted']

// [text colour, background colour] pairs that appear in the UI.
const TEXT_PAIRS: [string, string][] = [
  ...SURFACES.map((s): [string, string] => ['foreground', s]),
  ...SURFACES.map((s): [string, string] => ['muted-foreground', s]),
  ['card-foreground', 'card'],
  ['popover-foreground', 'popover'],
  ['primary-foreground', 'primary'],
  ['secondary-foreground', 'secondary'],
  ['accent-foreground', 'accent'],
  ['foreground', 'accent'],
  // Links and link-style buttons use the primary colour as text.
  ['primary', 'background'],
  ['primary', 'card'],
  ['destructive', 'background'],
  ['destructive', 'card'],
  ['sidebar-foreground', 'sidebar'],
  ['sidebar-foreground', 'sidebar-accent'],
  ['sidebar-primary-foreground', 'sidebar-primary'],
  ['sidebar-accent-foreground', 'sidebar-accent'],
  ['eyebrow', 'background'],
  ['eyebrow', 'card'],
  ['eyebrow', 'sidebar'],
  ['lab-foreground', 'lab'],
  // Device names on the cards of the suspect board.
  ['foreground', 'status-healthy-bg'],
  ['foreground', 'status-warning-bg'],
  ['foreground', 'status-critical-bg'],
  // The phase the agent is in now (agent HUD): the page's background colour on violet.
  ['background', 'provenance-ai'],
  // Status and provenance text sits on its own tinted background (badges) and directly on surfaces
  // (for example a coloured word in a table cell).
  ...['healthy', 'warning', 'critical', 'unknown'].flatMap((s) => [
    [`status-${s}`, `status-${s}-bg`] as [string, string],
    [`status-${s}`, 'background'] as [string, string],
    [`status-${s}`, 'card'] as [string, string],
  ]),
  ...['rule', 'ai'].flatMap((p) => [
    [`provenance-${p}`, `provenance-${p}-bg`] as [string, string],
    [`provenance-${p}`, 'background'] as [string, string],
    [`provenance-${p}`, 'card'] as [string, string],
  ]),
]

// Non-text UI parts: the focus ring must be visible on every surface.
const UI_PAIRS: [string, string][] = [
  ['ring', 'background'],
  ['ring', 'card'],
  ['sidebar-ring', 'sidebar'],
  ['primary', 'background'],
]

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '')
}

/** Returns the `--name: value` declarations of the first top-level block with this selector. */
function readBlock(source: string, selector: string): Map<string, string> {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = new RegExp(`^${escaped}\\s*\\{([\\s\\S]*?)^\\}`, 'm').exec(stripComments(source))
  if (!match) throw new Error(`no "${selector}" block in index.css`)
  const vars = new Map<string, string>()
  for (const [, name, value] of match[1].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    vars.set(name, value.trim())
  }
  return vars
}

const light = readBlock(css, ':root')
const darkOnly = readBlock(css, '.dark')
// In the dark theme, `.dark` overrides :root, so anything not overridden keeps its :root value.
const dark = new Map([...light, ...darkOnly])

function color(theme: Theme, token: string): string {
  const value = (theme === 'light' ? light : dark).get(`--${token}`)
  if (value === undefined) throw new Error(`token --${token} is not defined for the ${theme} theme`)
  return value
}

function rgb(value: string): Rgb {
  const parsed = parse(value)
  if (parsed?.mode !== 'rgb') throw new Error(`"${value}" is not an rgb/hex colour`)
  return parsed
}

/** The colour you see where a see-through colour lies on an opaque one. */
function over(top: string, under: string): Rgb {
  const t = rgb(top)
  const u = rgb(under)
  const a = t.alpha ?? 1
  const mix = (x: number, y: number) => a * x + (1 - a) * y
  return { mode: 'rgb', r: mix(t.r, u.r), g: mix(t.g, u.g), b: mix(t.b, u.b) }
}

// Glass cards are see-through, so their text is checked on the glass over every surface it may sit on.
const GLASS_TEXT = ['foreground', 'muted-foreground', 'primary', 'eyebrow']
const UNDER_GLASS = ['background', 'muted', 'card', 'secondary']

describe('design tokens', () => {
  test('every theme-dependent token is defined in both themes', () => {
    const lightNames = [...light.keys()].filter((n) => !THEME_INDEPENDENT.has(n)).sort()
    const darkNames = [...darkOnly.keys()].sort()
    expect(darkNames).toEqual(lightNames)
  })

  test('every Tailwind colour points at a defined token', () => {
    const themeBlock = /^@theme inline\s*\{([\s\S]*?)^\}/m.exec(stripComments(css))?.[1] ?? ''
    const used = [...themeBlock.matchAll(/--color-[\w-]+\s*:\s*var\((--[\w-]+)\)/g)].map(
      (m) => m[1],
    )
    expect(used.length).toBeGreaterThan(40)
    expect(used.filter((name) => !light.has(name))).toEqual([])
  })

  test('the brand colours are the UST palette', () => {
    expect(color('light', 'primary')).toBe('#006e74') // dark teal
    expect(color('light', 'foreground')).toBe('#231f20') // soft black
    expect(color('dark', 'chart-1')).toBe('#0097ac') // light teal (primary is a lighter tint of it)
    expect(color('dark', 'background')).toBe('#231f20') // soft black
  })

  for (const theme of ['light', 'dark'] as const) {
    describe(`${theme} theme contrast`, () => {
      test.each(TEXT_PAIRS)(`text %s on %s is at least ${TEXT_MIN}:1`, (fg, bg) => {
        const ratio = wcagContrast(color(theme, fg), color(theme, bg))
        expect(ratio, `${fg} on ${bg} (${theme}) is ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(
          TEXT_MIN,
        )
      })

      test.each(UI_PAIRS)(`UI part %s on %s is at least ${UI_MIN}:1`, (fg, bg) => {
        const ratio = wcagContrast(color(theme, fg), color(theme, bg))
        expect(ratio, `${fg} on ${bg} (${theme}) is ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(
          UI_MIN,
        )
      })

      const glassPairs = GLASS_TEXT.flatMap((fg) => UNDER_GLASS.map((bg) => [fg, bg]))
      test.each(glassPairs)(`text %s on glass over %s is at least ${TEXT_MIN}:1`, (fg, bg) => {
        const glass = over(color(theme, 'glass'), color(theme, bg))
        const ratio = wcagContrast(color(theme, fg), glass)
        expect(
          ratio,
          `${fg} on glass over ${bg} (${theme}) is ${ratio.toFixed(2)}:1`,
        ).toBeGreaterThanOrEqual(TEXT_MIN)
      })
    })
  }

  test('the CSS motion timings are the ones src/lib/motion.ts uses', () => {
    const ms = (s: number) => `${Math.round(s * 1000)}ms`
    expect(color('light', 'motion-fast')).toBe(ms(DURATION.fast))
    expect(color('light', 'motion-base')).toBe(ms(DURATION.base))
    expect(color('light', 'motion-slow')).toBe(ms(DURATION.slow))
    expect(color('light', 'motion-ease-out')).toBe(`cubic-bezier(${EASE_OUT.join(', ')})`)
    expect(color('light', 'motion-ease-in-out')).toBe(`cubic-bezier(${EASE_IN_OUT.join(', ')})`)
  })
})

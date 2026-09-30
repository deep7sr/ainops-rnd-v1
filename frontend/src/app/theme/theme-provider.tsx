import { useEffect, useState, type ReactNode } from 'react'
import {
  DARK_MEDIA_QUERY,
  DEFAULT_THEME,
  THEME_STORAGE_KEY,
  ThemeContext,
  type ResolvedTheme,
  type ThemeChoice,
} from './theme-context'

function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === 'light' || value === 'dark' || value === 'system'
}

function readSavedChoice(): ThemeChoice {
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY)
    return isThemeChoice(saved) ? saved : DEFAULT_THEME
  } catch {
    return DEFAULT_THEME // storage blocked by browser settings
  }
}

/**
 * Holds the theme choice, remembers it in the browser and puts the `dark` class on <html>
 * (the colours themselves are the design tokens in src/index.css).
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(readSavedChoice)
  const [systemDark, setSystemDark] = useState(() => window.matchMedia(DARK_MEDIA_QUERY).matches)

  // Follow changes of the Windows setting while the page is open.
  useEffect(() => {
    const media = window.matchMedia(DARK_MEDIA_QUERY)
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  const resolved: ResolvedTheme = choice === 'system' ? (systemDark ? 'dark' : 'light') : choice

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', resolved === 'dark')
    root.style.colorScheme = resolved
  }, [resolved])

  const setChoice = (next: ThemeChoice) => {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // Not remembered, but still applied for this visit.
    }
    setChoiceState(next)
  }

  return <ThemeContext value={{ choice, resolved, setChoice }}>{children}</ThemeContext>
}

import { createContext, useContext } from 'react'

/** What the user picked. "system" follows the Windows light/dark setting. */
export type ThemeChoice = 'light' | 'dark' | 'system'
/** What is actually shown. */
export type ResolvedTheme = 'light' | 'dark'

// public/theme-init.js uses the same key, values and default.
export const THEME_STORAGE_KEY = 'ainops-theme'
export const DEFAULT_THEME: ThemeChoice = 'light'
export const DARK_MEDIA_QUERY = '(prefers-color-scheme: dark)'

export interface ThemeState {
  choice: ThemeChoice
  resolved: ResolvedTheme
  setChoice: (choice: ThemeChoice) => void
}

export const ThemeContext = createContext<ThemeState | null>(null)

/** Current theme and a setter. Only works inside <ThemeProvider>. */
export function useTheme(): ThemeState {
  const state = useContext(ThemeContext)
  if (state === null) throw new Error('useTheme() must be used inside <ThemeProvider>')
  return state
}

// ESLint: finds bugs and bad patterns. Formatting is Prettier's job (eslint-config-prettier turns
// off the rules that would fight it).
import js from '@eslint/js'
import prettier from 'eslint-config-prettier'
import jsxA11y from 'eslint-plugin-jsx-a11y'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default defineConfig([
  // Generated API types (npm run api:generate): not hand-written code
  globalIgnores(['dist', 'coverage', 'src/api/schema.d.ts']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
      jsxA11y.flatConfigs.recommended, // accessibility (ARCHITECTURE 17.1: WCAG 2.1 AA)
    ],
    languageOptions: { globals: globals.browser },
  },
  {
    // shadcn/ui files export a component and its style variants together; that is fine there.
    files: ['src/components/ui/**'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
  {
    files: ['public/**/*.js'],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.browser, sourceType: 'script' },
  },
  prettier,
])

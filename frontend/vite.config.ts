import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Dev proxy (M1.11): the browser only talks to Vite (http://localhost:5173), and Vite forwards
// everything under /api to the backend. To the browser, page and API are one website, so the session
// cookie (Path=/api, SameSite=Strict) and the backend's Origin check work exactly as in production,
// where one server hosts both.
// 127.0.0.1, not "localhost": Node may resolve localhost to the IPv6 address ::1, where `ainops api`
// does not listen, and every request would fail with "connection refused".
const API_TARGET = process.env.AINOPS_API_URL ?? 'http://127.0.0.1:8000'
const apiProxy = { '/api': { target: API_TARGET } }

// One config for the dev server, the production build and the tests (Vitest reads the `test` part).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') },
  },
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy }, // `npm run preview` serves the production build the same way
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
    // Vitest skips CSS by default; the design-token test reads src/index.css as text.
    css: { include: [/index\.css/] },
  },
})

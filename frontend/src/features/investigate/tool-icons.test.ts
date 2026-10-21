/// <reference types="node" />  // these tests read repo files from disk
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { describeCall } from './describe'
import { FALLBACK_TOOL_ICON, TOOL_ICON } from './tool-icons'

// The tools the two MCP servers offer the agent, read from their source (every `@tool(...)`).
const BACKEND = path.resolve(import.meta.dirname, '../../../../backend/src/ainops')
const servers = ['network', 'topology'].map((server) =>
  readFileSync(path.join(BACKEND, server, 'server.py'), 'utf-8'),
)
const TOOLS = servers.flatMap((source) =>
  [...source.matchAll(/^@tool\([^\n]*\)\nasync def (\w+)/gm)].map((m) => m[1]),
)

describe('tool icons', () => {
  it('reads all 18 tools of the two MCP servers', () => {
    expect(TOOLS).toHaveLength(18)
  })

  it('every tool the agent can call has its own icon and sentence', () => {
    for (const tool of TOOLS) {
      expect(TOOL_ICON[tool], tool).toBeDefined()
      expect(describeCall(tool, {}), tool).not.toBe(`Running ${tool}`)
    }
  })

  it('no two tools share an icon', () => {
    const icons = Object.values(TOOL_ICON)
    expect(new Set(icons).size).toBe(icons.length)
  })

  it('the icon for a tool added later is not one a real tool uses', () => {
    expect(Object.values(TOOL_ICON)).not.toContain(FALLBACK_TOOL_ICON)
  })
})

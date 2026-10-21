/// <reference types="node" />  // these tests read repo files from disk
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { glyphKind } from '@/lib/device-kind'
import { DeviceGlyph } from './device-glyph'

// The roles in the lab inventories (the real EVE-NG lab and the simulator), read from the files.
const REPO = path.resolve(import.meta.dirname, '../../..')
const inventories = ['lab/inventory.yaml', 'backend/src/labsim/lab.yaml'].map((file) =>
  readFileSync(path.join(REPO, file), 'utf-8'),
)
const ROLES = new Set(
  inventories.flatMap((text) => [...text.matchAll(/^\s*role:\s*([\w-]+)/gm)].map((m) => m[1])),
)

describe('device pictures', () => {
  it('reads the roles of both lab inventories', () => {
    expect([...ROLES].sort()).toEqual(['core', 'firewall', 'isp-router', 'wan-router'])
  })

  it('every role in the inventories gets its own picture, not the plain box', () => {
    for (const role of ROLES) expect(glyphKind(role), role).not.toBe('device')
  })

  it('draws each lab role as network diagrams do', () => {
    expect(glyphKind('isp-router')).toBe('isp')
    expect(glyphKind('wan-router')).toBe('router')
    expect(glyphKind('core')).toBe('core')
    expect(glyphKind('firewall')).toBe('firewall')
  })

  it('a role AINOPS does not know gets the plain box, never a wrong picture', () => {
    expect(glyphKind('load-balancer')).toBe('device')
    expect(glyphKind('')).toBe('device')
  })

  it('is hidden from screen readers unless it has a title', () => {
    const { container, rerender } = render(<DeviceGlyph deviceRole="firewall" />)
    const svg = container.querySelector('svg')
    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(svg).toHaveAttribute('data-glyph', 'firewall')

    rerender(<DeviceGlyph deviceRole="firewall" title="Firewall" />)
    expect(container.querySelector('svg')).toHaveAccessibleName('Firewall')
  })
})

/*
 * Copyright 2026 Apache HugeGraph Authors
 * 
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 * 
 *     http://www.apache.org/licenses/LICENSE-2.0
 * 
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
/** Contract for the values that only a browser can measure.
 *
 * The tone-theming test next door pins the *structure* of the palette. This one
 * pins the numbers behind it, because every one of them was found by measuring
 * a real page and would otherwise regress silently:
 *
 *  - light `--text-muted` on `--surface-sunken`: 4.01:1 (muted text sits on table
 *    headers and toolbar strips, not only on white);
 *  - light `--sidebar-muted`: 2.99:1 on the white sidebar — the dark value was
 *    raised for this and the light one was not;
 *  - light `--tone-{success,warning,info}-fg` measured 4.33 / 3.92 / 4.65 against
 *    their own tint over `--surface-sunken`;
 *  - `--color-brand-600` used as a *text* colour: 2.43:1 in dark mode;
 *  - `prefers-reduced-motion` had no guard, so `ontogeny-shimmer` looped forever.
 *
 * Verified end to end with `tools/headless_check.py` (both themes, 14 routes).
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

function block(selector: string): string {
  const at = css.indexOf(`${selector} {`)
  expect(at, `index.css must define ${selector}`).toBeGreaterThan(-1)
  return css.slice(at, css.indexOf('\n}', at))
}

const LIGHT = block(':root')
const DARK = block('[data-theme="dark"]')

/* ------------------------------------------------------------- contrast --- */

function srgb(c: number): number {
  const s = c / 255
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
}

function lum(hex: string): number {
  const h = hex.replace('#', '')
  const [r, g, b] = [0, 2, 4].map((i) => Number.parseInt(h.slice(i, i + 2), 16))
  return 0.2126 * srgb(r) + 0.7152 * srgb(g) + 0.0722 * srgb(b)
}

function ratio(fg: string, bg: string): number {
  const a = lum(fg)
  const b = lum(bg)
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

/** `rgba(...)` over an opaque hex — a tone chip's real background. */
function composite(rgba: string, bg: string): string {
  const parts = rgba.match(/[\d.]+/g)!.map(Number)
  const [r, g, b, a] = [parts[0], parts[1], parts[2], parts[3] ?? 1]
  const base = [0, 2, 4].map((i) => Number.parseInt(bg.replace('#', '').slice(i, i + 2), 16))
  const out = [r, g, b].map((v, i) => Math.round(v * a + base[i] * (1 - a)))
  return `#${out.map((v) => v.toString(16).padStart(2, '0')).join('')}`
}

function token(source: string, name: string): string {
  const m = source.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))
  expect(m, `--${name} must be a literal hex in this block`).toBeTruthy()
  return m![1]
}

const TONES = ['neutral', 'brand', 'success', 'warning', 'danger', 'info', 'violet'] as const

describe('measured contrast', () => {
  it('keeps light muted text readable on every surface it sits on', () => {
    const muted = token(LIGHT, 'text-muted')
    for (const surface of ['surface-card', 'surface-app', 'surface-sunken']) {
      expect(ratio(muted, token(LIGHT, surface)), `--text-muted on --${surface}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('keeps the light sidebar labels readable on the white sidebar', () => {
    // the dark value was raised for this failure; light had it too (2.99:1)
    expect(ratio(token(LIGHT, 'sidebar-muted'), token(LIGHT, 'sidebar-bg'))).toBeGreaterThanOrEqual(4.5)
  })

  it('keeps the dark sidebar labels readable', () => {
    // --sidebar-muted is an rgba() there, so compare against the darkest step
    const m = DARK.match(/--sidebar-muted:\s*rgba\(([\d.,\s]+)\)/)
    expect(m, 'dark --sidebar-muted must be a literal rgba').toBeTruthy()
    const over = composite(`rgba(${m![1]})`, token(DARK, 'sidebar-bg'))
    expect(ratio(over, token(DARK, 'sidebar-bg'))).toBeGreaterThanOrEqual(4.5)
  })

  it('keeps every tone chip readable on its own tint over the darkest light surface', () => {
    // the worst case: a chip inside a sunken row/header, which is where they land
    const sunken = token(LIGHT, 'surface-sunken')
    for (const tone of TONES) {
      const bg = LIGHT.match(new RegExp(`--tone-${tone}-bg:\\s*(rgba?\\([^)]+\\))`))?.[1]
      const fg = LIGHT.match(new RegExp(`--tone-${tone}-fg:\\s*(?:var\\(--brand-fg\\)|(#[0-9a-fA-F]{6}))`))?.[1]
        ?? token(LIGHT, 'brand-fg')
      const effective = bg ? composite(bg, sunken) : sunken
      expect(ratio(fg, effective), `tone ${tone}: ${fg} on ${effective}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('keeps every tone chip readable in dark mode', () => {
    const card = token(DARK, 'surface-card')
    for (const tone of TONES) {
      const bg = DARK.match(new RegExp(`--tone-${tone}-bg:\\s*(rgba?\\([^)]+\\))`))?.[1]
      const fg = DARK.match(new RegExp(`--tone-${tone}-fg:\\s*(?:var\\(--brand-fg\\)|(#[0-9a-fA-F]{6}))`))?.[1]
        ?? token(DARK, 'brand-fg')
      const effective = bg ? composite(bg, card) : card
      expect(ratio(fg, effective), `tone ${tone}: ${fg} on ${effective}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('uses a brand foreground token, not the brand background step, for text', () => {
    // #1c40e6 as text measured 2.43:1 in dark mode
    expect(ratio(token(DARK, 'brand-fg'), token(DARK, 'surface-card'))).toBeGreaterThanOrEqual(4.5)
    expect(ratio(token(LIGHT, 'brand-fg'), token(LIGHT, 'surface-sunken'))).toBeGreaterThanOrEqual(4.5)
  })
})

describe('reduced motion', () => {
  it('guards the animations that would otherwise keep moving', () => {
    const at = css.indexOf('@media (prefers-reduced-motion: reduce)')
    expect(at, 'index.css must guard prefers-reduced-motion').toBeGreaterThan(-1)
    const guard = css.slice(at)
    // the infinite shimmer and the per-page fade have to be named: shortening a
    // 1.4s infinite loop is not the same as stopping it
    expect(guard).toContain('.ontogeny-skeleton')
    expect(guard).toContain('.ontogeny-animate-in')
    expect(guard).toContain('.ontogeny-drawer')
    expect(guard).toMatch(/animation-iteration-count:\s*1\s*!important/)
  })
})

describe('elevation', () => {
  it('defines every shadow token in both themes', () => {
    // a light-mode drop shadow reads as a glow on a dark page, so dark gets its
    // own values. `--shadow-card`/`-float` live in @theme (the Tailwind token
    // block) while the rest are declared per theme, so light = @theme + :root.
    const themeBlock = css.slice(css.indexOf('@theme {'), css.indexOf(':root {'))
    const light = themeBlock + LIGHT
    for (const name of ['shadow-card', 'shadow-float', 'shadow-node', 'shadow-node-active', 'shadow-edge', 'shadow-drawer']) {
      expect(light, `light theme needs --${name}`).toContain(`--${name}:`)
      expect(DARK, `dark theme needs --${name}`).toContain(`--${name}:`)
    }
  })

  it('gives dark mode its own elevation values rather than inheriting light ones', () => {
    const lift = (name: string) => DARK.match(new RegExp(`--${name}:\\s*([^;]+);`))?.[1] ?? ''
    // every dark shadow must be re-declared; the light rgba(16,24,40,…) values
    // read as a pale halo on a near-black page
    expect(lift('shadow-node')).toMatch(/rgba\(0,\s*0,\s*0/)
    expect(lift('shadow-drawer')).toMatch(/rgba\(0,\s*0,\s*0/)
    expect(lift('shadow-node-active')).toMatch(/rgba\(0,\s*0,\s*0/)
  })
})

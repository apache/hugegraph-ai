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
/** Theming contract for the semantic tone palette.
 *
 * Regression: `BADGE_TONES`/`ALERT_TONES` hard-coded light-mode foregrounds
 * (`#047857`, `#b45309`, `#b91c1c`, `#0369a1`, `#6d28d9`, `brand-600`) on
 * translucent tints, and `index.css` only had dark overrides for `.ontogeny-code`
 * and `.ontogeny-link`. Result: every page failed WCAG AA in dark mode (measured
 * 244 failing text nodes, worst 2.43:1).
 *
 * jsdom cannot compute contrast, so this pins the *structure* that makes dark
 * mode possible: every tone must resolve through a `--tone-*` custom property,
 * and every such property must be defined in BOTH theme blocks. The real
 * contrast verification is a browser-side audit (WCAG AA, per theme block).
 */
import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { Badge, TONES, toneSurface } from './ui'

// read the sheet from disk: a `?raw` import would be pre-processed by the
// Tailwind plugin and no longer contain the declarations we assert on
// vitest's root is the `web/` package dir (jsdom has no file:// import.meta.url)
const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8')

/** Body of a top-level rule, e.g. `ruleBody(':root')`. */
function ruleBody(selector: string): string {
  const at = css.indexOf(`${selector} {`)
  expect(at, `index.css must define ${selector}`).toBeGreaterThan(-1)
  const end = css.indexOf('\n}', at)
  return css.slice(at, end)
}

const TONE_NAMES = ['neutral', 'brand', 'success', 'warning', 'danger', 'info', 'violet']

describe('tone palette theming', () => {
  it('routes every tone through --tone-* custom properties', () => {
    for (const name of TONE_NAMES) {
      const tone = TONES[name]
      expect(tone, `tone ${name} missing`).toBeTruthy()
      expect(tone.fg, `${name}.fg must be a token, not a hex`).toMatch(/^var\(--tone-/)
      expect(tone.bg, `${name}.bg must be a token`).toMatch(/^var\(--tone-/)
      expect(tone.ring, `${name}.ring must be a token`).toMatch(/^var\(--tone-/)
      // no raw colour anywhere in the tone table
      expect(JSON.stringify(tone)).not.toMatch(/#[0-9a-fA-F]{3,6}\b|rgba?\(/)
    }
  })

  it('defines a foreground for every tone in both themes', () => {
    const light = ruleBody(':root')
    const dark = ruleBody('[data-theme="dark"]')
    for (const name of TONE_NAMES) {
      expect(light, `:root needs --tone-${name}-fg`).toContain(`--tone-${name}-fg:`)
      expect(dark, `dark theme needs --tone-${name}-fg (this is what regressed)`).toContain(`--tone-${name}-fg:`)
    }
  })

  it('dark tone foregrounds are lighter than their light counterparts', () => {
    // a crude but real invariant: the dark step must be brighter, otherwise it
    // cannot contrast against a dark surface
    const lum = (hex: string) => {
      const n = Number.parseInt(hex.replace('#', ''), 16)
      return 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)
    }
    const pick = (body: string, name: string) =>
      body.match(new RegExp(`--tone-${name}-fg:\\s*(#[0-9a-fA-F]{6})`))?.[1]
    const light = ruleBody(':root')
    const dark = ruleBody('[data-theme="dark"]')
    for (const name of TONE_NAMES) {
      const l = pick(light, name)
      const d = pick(dark, name)
      if (!l || !d) continue // indirect (var) values are covered by the test above
      expect(lum(d), `${name}: dark ${d} must be lighter than light ${l}`).toBeGreaterThan(lum(l))
    }
  })

  it('Badge and toneSurface both consume the shared table', () => {
    expect(toneSurface('success').color).toBe(TONES.success.fg)
    // rendering a badge must not inline a colour
    const { container } = render(<Badge tone="success">ok</Badge>)
    const el = container.querySelector('span')!
    expect(el.getAttribute('style') ?? '').not.toMatch(/#[0-9a-fA-F]{6}/)
    expect(el.getAttribute('style') ?? '').toContain('--tone-success-fg')
  })
})

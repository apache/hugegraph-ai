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
/**
 * Text metrics for the graph canvas.
 *
 * The ontology nodes size themselves to their label: a box that is always 172px
 * wide leaves `bom` swimming in whitespace and clips
 * `production-order · 生产工单`. G6 needs each node's size *before* it lays the
 * graph out, and the drawing happens in a canvas, so the measurement has to
 * come from a canvas too — this module keeps one detached 2D context, measures
 * with the same font the node draws with, and memoises the answer.
 *
 * The estimate fallback matters for tests and for any environment without a 2D
 * context (jsdom returns null from `getContext('2d')`): without it the adapter
 * would divide by zero or return NaN sizes and the layout would collapse. It
 * classifies each code point as full-width (CJK, kana, hangul, full-width
 * forms) or narrow, which is within a few percent of the real advance for the
 * two scripts this UI uses.
 */

const FONT_FAMILY =
  '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif'

/** One shared context; measuring allocates nothing after the first call. */
let ctx: CanvasRenderingContext2D | null | undefined

function context(): CanvasRenderingContext2D | null {
  if (ctx !== undefined) return ctx
  try {
    ctx = document.createElement('canvas').getContext('2d')
  } catch {
    ctx = null
  }
  return ctx
}

/** CJK / kana / hangul / full-width punctuation advance ≈ one em. */
function isWide(cp: number): boolean {
  return (
    (cp >= 0x1100 && cp <= 0x115f) ||   // hangul jamo
    (cp >= 0x2e80 && cp <= 0x303e) ||   // CJK radicals, kangxi, CJK punctuation
    (cp >= 0x3041 && cp <= 0x33ff) ||   // kana, CJK compat
    (cp >= 0x3400 && cp <= 0x4dbf) ||   // CJK ext A
    (cp >= 0x4e00 && cp <= 0x9fff) ||   // CJK unified
    (cp >= 0xa000 && cp <= 0xa4cf) ||   // yi
    (cp >= 0xac00 && cp <= 0xd7a3) ||   // hangul syllables
    (cp >= 0xf900 && cp <= 0xfaff) ||   // CJK compat ideographs
    (cp >= 0xfe30 && cp <= 0xfe6f) ||   // CJK compat forms
    (cp >= 0xff00 && cp <= 0xff60) ||   // full-width forms
    (cp >= 0xffe0 && cp <= 0xffe6) ||
    (cp >= 0x20000 && cp <= 0x3fffd)    // CJK ext B+
  )
}

function estimate(text: string, fontSize: number): number {
  let units = 0
  for (const ch of text) {
    const cp = ch.codePointAt(0) ?? 0
    // bold sans averages a little over half an em for narrow glyphs
    units += isWide(cp) ? 1 : 0.56
  }
  return units * fontSize
}

const cache = new Map<string, number>()

/** Rendered width of `text` in the UI's sans stack at `fontSize` px (bold). */
export function measureTextWidth(text: string, fontSize: number, bold = true): number {
  const key = `${fontSize}|${bold ? 'b' : 'n'}|${text}`
  const hit = cache.get(key)
  if (hit !== undefined) return hit
  let width: number
  const c = context()
  if (c) {
    c.font = `${bold ? '700 ' : ''}${fontSize}px ${FONT_FAMILY}`
    width = c.measureText(text).width
    // A context that cannot measure (some headless environments report 0 for
    // everything) falls back to the estimate rather than sizing every node to 0.
    if (!(width > 0)) width = estimate(text, fontSize)
  } else {
    width = estimate(text, fontSize)
  }
  cache.set(key, width)
  return width
}

/** How a label of `text` fits a box `maxWidth` wide, at `fontSize` px.
 *
 * Wraps on the spaces the label already has (model names are kebab-case, so
 * every hyphen is a legal break point) and, when a single token is still too
 * long, on characters — otherwise `equipment-maintenance-orders` would simply
 * overflow. Returns the line count and the width the box actually needs, which
 * is what lets a node hug a short name and grow for a long one. `rows` are the
 * wrapped strings themselves: the card element draws THEM row by row instead of
 * letting the canvas re-wrap (two wrap algorithms tipping a borderline width
 * differently is what used to bend cards out of shape). */
export function fitText(
  text: string,
  maxWidth: number,
  fontSize: number,
  maxLines = 3,
): { lines: number; width: number; longest: number; rows: string[] } {
  const full = measureTextWidth(text, fontSize)
  if (full <= maxWidth) return { lines: 1, width: full, longest: full, rows: [text] }

  const lines: string[] = []
  let current = ''
  const push = () => { if (current) { lines.push(current); current = '' } }

  for (const token of text.split(/(?<=[\s-])/)) {
    const candidate = current + token
    if (measureTextWidth(candidate.trim(), fontSize) <= maxWidth) {
      current = candidate
      continue
    }
    push()
    // the token alone still does not fit: break it by character
    if (measureTextWidth(token.trim(), fontSize) > maxWidth) {
      let chunk = ''
      for (const ch of token) {
        if (measureTextWidth(chunk + ch, fontSize) > maxWidth && chunk) {
          lines.push(chunk)
          chunk = ch
        } else {
          chunk += ch
        }
      }
      current = chunk
    } else {
      current = token
    }
  }
  push()

  const kept = lines.slice(0, maxLines)
  const longest = kept.reduce((n, l) => Math.max(n, measureTextWidth(l, fontSize)), 0)
  return { lines: Math.min(lines.length, maxLines), width: longest, longest, rows: kept }
}

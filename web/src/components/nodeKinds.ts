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
 * The ontology canvas's visual language: one icon and one colour per model
 * kind, shared by the graph and its legend.
 *
 * A drawing of fifteen cards in one colour and one shape is a diagram you have
 * to read; a drawing where an object type, an action and a function are visibly
 * *different things* is one you can scan. The colour carries the kind and the
 * icon makes it readable at a glance — including at small zoom levels, where the
 * label has already given up.
 *
 * The three icons are the product's own (实体 / 动作 / 函数): filled glyphs on a
 * 1024 viewBox. They are *filled*, not stroked, and they carry no plate or chip
 * behind them — a glyph in the node's own colour reads as part of the card,
 * while a tinted square behind it reads as a widget. The fill is baked into the
 * data URI per colour, because the canvas paints them as images.
 *
 * No network, no icon font, no sprite sheet: each icon is a self-contained
 * string, cached per (kind, theme, colour).
 */

/** Model kinds the canvas draws as nodes.
 *
 * Policies and projections are *not* here on purpose: a policy is a property of
 * an action and a projection a property of a set of object types, so they are
 * shown on those nodes (detail panel, action sublabel) rather than as more
 * boxes competing for attention. */
export type NodeKind = 'object' | 'action' | 'function'

/** Kind → colour. Deliberately distinct hues: the object type is the subject of
 *  the drawing, everything else is a satellite of it. */
export const KIND_COLOR: Record<NodeKind, string> = {
  object: '#2e5bff',
  action: '#7c3aed',
  function: '#0891b2',
}

/** Colours for the two kinds that appear on nodes rather than as nodes. */
export const ATTACHED_COLOR = {
  policy: '#d97706',
  projection: '#0d9488',
} as const

/** Kind → the icon's path, from the product's own icon set (实体/动作/函数). */
const KIND_PATHS: Record<NodeKind, string> = {
  // 实体.svg: the isometric box — the noun of the model
  object: 'M959.9 563.6c1.5-34.4-30.9-46.9-30.9-46.9L749.8 440s0.4-133.3 0-169.2c-0.5-36.1-32.4-48.6-32.4-48.6S575.6 165 533.5 143.9c-22-11-44.8 0-44.8 0S355.3 203.7 314 220.6c-37.7 15.4-37.1 48.6-37.1 48.6v169.7S159.4 490.4 110 510.1c-47.3 18.8-46 58.3-46 58.3s0.4 135.4 0 170.7c-0.4 38.1 33.5 50.1 33.5 50.1s114 58.1 168.5 83.3c40.3 18.6 66.4 0.6 66.4 0.6l179-89.2s141.6 67.5 174.9 88.8c38.7 24.6 64.9 4.2 64.9 4.2s157.7-81 182.4-92.4c26.3-12.2 26.3-42.3 26.3-42.3s-1.5-144.2 0-178.6zm-658.3 67.3L137.7 558l163.8-72.8 166.9 72.1-166.8 73.6zm183.8 108l-157.6 79.8V676.2l157.6-68.9v131.6zm25.9-391.6L334 270.6l177.3-79.4 184.4 79.4-184.4 76.7zm28.3 47.1l156.1-68.9v115.9l-156.1 70.4V394.4zm186.2 236.5L562.7 558l156.1-72.8 170 72.8-163 72.9zm180 112.8l-154.6 75.2V676.2l154.6-68.9v136.4z',
  // 动作.svg: the raised hand — a verb that changes state
  action: 'M833.566118 853.323294a26.352941 26.352941 0 0 1-26.352942 26.352941H420.743529a26.352941 26.352941 0 0 1-26.352941-26.352941v-95.171765l-18.733176-20.48-121.976471-133.933176-47.134117-52.796235-6.204236-7.439059c-39.213176-50.718118-5.300706-103.092706 71.981177-103.092706 34.093176 0 57.976471 14.546824 92.039529 47.736471l6.505412 6.445176 13.251765 13.312 6.475294 6.234353 3.975529 3.674353 0.030118-129.957647-0.150588-184.470588a79.088941 79.088941 0 0 1 158.057411-5.029647l0.150589 4.999529-0.030118 118.061176 203.776 31.352471 7.830588 1.505882c36.713412 8.734118 66.770824 40.237176 69.210353 89.630118l0.150588 6.535529zM473.479529 176.941176a26.383059 26.383059 0 0 0-26.142117 23.100236l-0.210824 3.312941 0.120471 327.499294-0.150588 29.093647-0.301177 3.614118-0.963765 4.005647-0.421647 0.963765-8.884706 12.167529-15.811764 3.493647v1.776941c-17.317647 0-32.617412-6.384941-48.549647-18.311529l-5.360941-4.216471-5.421177-4.577882-3.373176-3.011765-7.077647-6.686118-22.528-22.467764c-24.937412-24.365176-39.845647-33.581176-56.079059-33.581177h-4.939294l-4.517647 0.120471-7.830589 0.451765c-19.817412 1.626353-21.413647 6.927059-13.161411 17.438117l1.776941 2.168471 4.818823 5.601882 37.737412 42.224941 146.100706 160.436706h348.551529v-271.119059c0-24.395294-10.541176-38.339765-24.425411-43.52l-3.011765-0.993882-3.343059-0.752941-6.294588-1.054118-221.455059-33.972706a26.352941 26.352941 0 0 1-22.226824-22.859294l-0.180705-3.19247V203.354353a26.443294 26.443294 0 0 0-26.443295-26.413177z',
  // 函数.svg: the canvas with f(x) — code that computes
  function: 'M575.5 430.86l67.87 67.88 67.9-67.88c12.5-12.5 32.76-12.5 45.25 0 12.5 12.5 12.5 32.76 0 45.25l-67.9 67.87 67.9 67.9c12.5 12.5 12.5 32.76 0 45.25-12.5 12.5-32.76 12.5-45.25 0l-67.9-67.9-67.87 67.9c-12.5 12.5-32.76 12.5-45.25 0-12.5-12.5-12.5-32.76 0-45.25l67.88-67.9-67.88-67.87c-12.5-12.5-12.5-32.76 0-45.25 12.49-12.49 32.76-12.49 45.25 0zM469.65 171.42l9.24 0.58a95.928 95.928 0 0 1 50.39 21.28l6.89 6.25 11.21 11.21c12.5 12.5 12.5 32.76 0 45.26s-32.76 12.5-45.25 0l-11.21-11.21a32.037 32.037 0 0 0-19.09-9.18c-15.61-1.74-29.85 8.07-34.19 22.61l-1.15 5.66-11.08 99.53H448c17.67 0 32 14.33 32 32s-14.33 32-32 32h-29.7l-20.98 188.91a95.839 95.839 0 0 1-9.55 32.33c-22.32 44.63-74.71 64.28-120.33 46.67l-8.47-3.74-17.28-8.64c-15.81-7.9-22.21-27.13-14.31-42.93 7.9-15.81 27.13-22.21 42.93-14.31l17.28 8.64c15.81 7.9 35.03 1.5 42.93-14.31l2.07-5.25 1.11-5.53 20.2-181.84H320c-17.67 0-32-14.33-32-32s14.33-32 32-32h41.02l11.85-106.59c5.52-49.6 47.89-86.16 96.78-85.4zM896 128H128v640h768V128z m32-64c17.67 0 32 14.33 32 32v704c0 17.67-14.33 32-32 32H96c-17.67 0-32-14.33-32-32V96c0-17.67 14.33-32 32-32h832zM800 896c17.67 0 32 14.33 32 32s-14.33 32-32 32H224c-17.67 0-32-14.33-32-32s14.33-32 32-32h576z',
}

/** Mix a hex colour toward white. On the dark theme the cards are tinted
 *  surfaces of the same hue, so a glyph in the raw kind colour reads as
 *  purple-on-purple; lifting it keeps the icon legible without leaving the
 *  kind's colour family. */
function lighten(hex: string, amount: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return hex
  const n = parseInt(m[1], 16)
  const mix = (c: number) => Math.round(c + (255 - c) * amount)
  const r = mix((n >> 16) & 255)
  const g = mix((n >> 8) & 255)
  const b = mix(n & 255)
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`
}

const svgCache = new Map<string, string>()

/** One kind's icon as an inline SVG data URI, FILLED with `color`.
 *
 * The icon takes the node's own colour, so a card and its glyph are one object:
 * the caller passes whatever colour the node is drawn in (the kind colour by
 * default) and gets the same hue back inside the SVG.
 *
 * Cached per (kind, colour): the same node kind is asked for on every render and
 * every theme switch, and re-encoding a 1.5 kB path each time is pure waste. */
export function kindIconSrc(kind: NodeKind, color?: string, dark = false): string {
  const base = color ?? KIND_COLOR[kind] ?? KIND_COLOR.object
  const fill = dark ? lighten(base, 0.34) : base
  const key = `${kind}:${fill}:${dark ? 'd' : 'l'}`
  const hit = svgCache.get(key)
  if (hit) return hit
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="24" height="24">` +
    `<path fill="${fill}" d="${KIND_PATHS[kind] ?? KIND_PATHS.object}"/></svg>`
  // encodeURIComponent rather than base64: readable in devtools, and `#` is the
  // one character a data URI cannot carry raw
  const src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  svgCache.set(key, src)
  return src
}

/** The kind's colour, with a fallback for a node that carries no kind (an
 *  instance graph node, which is coloured by its object type instead). */
export function kindColor(kind?: NodeKind, fallback?: string): string {
  if (kind && KIND_COLOR[kind]) return KIND_COLOR[kind]
  return fallback ?? KIND_COLOR.object
}

/** Legend order: the subject first, then its satellites. */
export const KIND_ORDER: NodeKind[] = ['object', 'action', 'function']

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
/** The colour theme, shared by every consumer.
 *
 * This used to be a bare `useState` inside the hook, which gave each caller its
 * OWN copy: the sidebar's toggle flipped its own state and wrote the DOM
 * attribute, while FlowGraph — which caches computed CSS colours when it builds
 * the G6 canvas — kept rendering with the palette it started with. Switching to
 * dark left light cards on a dark sheet until a reload.
 *
 * A module-level store (read through `useSyncExternalStore`) makes the theme one
 * value for the whole page: the toggle writes it, every consumer re-renders,
 * and the canvas rebuilds with the new palette.
 */
import { useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'
const KEY = 'ontogeny.theme'

export function detectTheme(): Theme {
  const saved = localStorage.getItem(KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

let current: Theme | null = null
const listeners = new Set<() => void>()

function get(): Theme {
  if (current === null) {
    current = detectTheme()
    // applied here rather than in an effect: the attribute must be on the
    // document before the first consumer reads computed colours, or the first
    // canvas paints with the previous palette
    document.documentElement.dataset.theme = current
  }
  return current
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function set(theme: Theme): void {
  current = theme
  document.documentElement.dataset.theme = theme
  localStorage.setItem(KEY, theme)
  for (const listener of listeners) listener()
}

export function useTheme(): [Theme, () => void] {
  const theme = useSyncExternalStore(subscribe, get, get)
  return [theme, () => set(theme === 'dark' ? 'light' : 'dark')]
}

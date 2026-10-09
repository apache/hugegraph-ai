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
/** Focus management for overlay surfaces.
 *
 * There was no skip link and the node drawer moved nothing: opening it left
 * focus on `<body>` (so the first Tab went back to the sidebar), Tab escaped
 * into the page behind it, and closing it dropped focus on `<body>` instead of
 * returning it to the node that was clicked. The drawer looked like a dialog
 * (`role="dialog"`) but did not behave like one.
 */
import { useEffect, useRef, useState, type RefObject } from 'react'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function focusable(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE))
    .filter((el) => el.offsetParent !== null || el === document.activeElement)
}

/**
 * Full dialog focus contract, on while `active`:
 *  1. move focus inside (first focusable, else the container itself);
 *  2. keep Tab/Shift+Tab inside;
 *  3. on close, return focus to whatever had it before.
 *
 * Returns the ref to attach to the overlay element.
 */
export function useFocusTrap<T extends HTMLElement>(active: boolean): RefObject<T | null> {
  const ref = useRef<T>(null)
  const restoreTo = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!active) return
    const container = ref.current
    if (!container) return

    restoreTo.current = document.activeElement as HTMLElement | null

    // focus the panel itself rather than the first control: a screen reader then
    // announces the dialog's accessible name before any of its buttons
    if (!container.contains(document.activeElement)) {
      container.setAttribute('tabindex', '-1')
      container.focus()
    }

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const items = focusable(container)
      if (items.length === 0) {
        e.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const inside = container.contains(document.activeElement)
      if (!inside) {
        e.preventDefault()
        ;(e.shiftKey ? last : first).focus()
        return
      }
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }

    container.addEventListener('keydown', onKey)
    return () => {
      container.removeEventListener('keydown', onKey)
      // return focus to the trigger; fall back to the document so a keyboard
      // user never lands on <body> with no visible focus
      const target = restoreTo.current
      if (target && document.contains(target)) target.focus()
    }
  }, [active])

  return ref
}

/** Reactive `matchMedia`. The shell needs to know the viewport *class* (narrow /
 *  mobile) to decide between "collapsed rail" and "off-canvas drawer" — the same
 *  decision CSS alone cannot make, because the default depends on it too. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false)

  useEffect(() => {
    const mql = window.matchMedia(query)
    setMatches(mql.matches)
    const onChange = (e: MediaQueryListEvent) => setMatches(e.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])

  return matches
}

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
import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

// FlowGraph renders with AntV G6 (canvas/WebGL); jsdom has no canvas — mock
// the engine with a deterministic fake that records config and handlers.
//
// The mock also carries the pieces FlowGraph imports for its custom card
// element (`Rect`, `register`) and the `@antv/g` shapes that element draws, as
// plain classes: jsdom cannot build a real G display object, and the tests only
// assert on the *config* the canvas is handed.
vi.mock('@antv/g6', () => {
  class Rect {}
  class FakeGraph {
    cfg: any
    handlers: Record<string, Function[]> = {}
    constructor(cfg: any) {
      this.cfg = cfg
      ;(globalThis as any).__ooG6 = this
      ;((globalThis as any).__ooG6Created ||= []).push(this)
    }
    setData() {}
    setElementState() {}
    render() { return Promise.resolve(true) }
    destroy() {}
    on(type: string, handler: Function) {
      ;(this.handlers[type] ||= []).push(handler)
    }
    off() {}
    emitNodeClick(id: string) {
      ;(this.handlers['node:click'] || []).forEach((h) => h({ target: { id } }))
    }
    emitEdgeClick(id: string) {
      ;(this.handlers['edge:click'] || []).forEach((h) => h({ target: { id } }))
    }
    /** Pretend a drag settled at (x, y): the graph is the source of the new
     *  position, which is what the canvas reads back in `node:dragend`. */
    emitNodeDragEnd(id: string, x: number, y: number) {
      const node = (this.cfg?.data?.nodes || []).find((n: { id: string }) => n.id === id)
      if (node) node.style = { ...(node.style || {}), x, y }
      ;(this.handlers['node:dragend'] || []).forEach((h) => h({ target: { id } }))
    }
    getNodeData(id: string) {
      return (this.cfg?.data?.nodes || []).find((n: { id: string }) => n.id === id)
    }
  }
  const register = () => {}
  // The HTML node (EntityCardNode extends it): its own DOM work is exercised in
  // the browser, but the class must exist for the element to be constructible
  // in a test.
  class HTML {
    options: any
    constructor(options: any) { this.options = options }
    getDomElement(): HTMLElement | undefined { return undefined }
  }
  return { Graph: FakeGraph, Rect, HTML, register, default: { Graph: FakeGraph } }
})

vi.mock('@antv/g', () => {
  class Shape {}
  return {
    Image: class extends Shape {}, Rect: class extends Shape {}, Text: class extends Shape {},
    HTML: class extends Shape {},
  }
})

// jsdom has no matchMedia (and no layout, so it cannot infer one). The shell
// asks for two viewport classes; default to "wide" and let a test override via
// `setViewportWidth`.
export const VIEWPORT_QUERIES: MediaQueryList[] = []
export function setViewportWidth(width: number) {
  for (const mql of VIEWPORT_QUERIES) {
    const max = Number(/max-width:\s*(\d+)px/.exec(mql.media)?.[1] ?? Infinity)
    const min = Number(/min-width:\s*(\d+)px/.exec(mql.media)?.[1] ?? 0)
    // the stub keeps `matches` writable in practice (jsdom defines it read-only)
    const mutable = mql as unknown as { matches: boolean; dispatchEvent: (e: Event) => boolean }
    mutable.matches = width <= max && width >= min
    mutable.dispatchEvent({ type: 'change', matches: mutable.matches } as MediaQueryListEvent)
  }
}

if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => {
      const mql = {
        media: query,
        matches: true,
        onchange: null,
        addEventListener: (_: string, cb: EventListener) => { (mql as never as { _cbs: EventListener[] })._cbs.push(cb) },
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: (e: Event) => {
          for (const cb of (mql as never as { _cbs: EventListener[] })._cbs) cb(e)
          return true
        },
        _cbs: [] as EventListener[],
      }
      VIEWPORT_QUERIES.push(mql as unknown as MediaQueryList)
      const max = Number(/max-width:\s*(\d+)px/.exec(query)?.[1] ?? Infinity)
      mql.matches = 1600 <= max
      return mql as unknown as MediaQueryList
    },
  })
}

// React Flow (used by FlowGraph) needs browser APIs jsdom lacks.
class ResizeObserverStub {
  constructor(cb: ResizeObserverCallback) { this.cb = cb }
  cb: ResizeObserverCallback
  observe(el: Element) {
    // report a stable size so React Flow marks nodes as measured
    // (without this, RF disables dragging and skips edge rendering)
    const rect = { width: 168, height: 46, top: 0, left: 0, right: 168, bottom: 46,
      x: 0, y: 0, toJSON: () => ({}) } as DOMRectReadOnly
    setTimeout(() => this.cb(
      [{ target: el, contentRect: rect, borderBoxSize: [], contentBoxSize: [], devicePixelContentBoxSize: [] } as ResizeObserverEntry],
      this as unknown as ResizeObserver), 0)
  }
  unobserve() {}
  disconnect() {}
}
if (!('ResizeObserver' in globalThis)) {
  ;(globalThis as Record<string, unknown>).ResizeObserver = ResizeObserverStub
}
// jsdom reports every rect as 0x0; React Flow needs handle bounds to render
// edges and enable dragging, so give zero rects a usable default.
const gbr = Element.prototype.getBoundingClientRect
Element.prototype.getBoundingClientRect = function () {
  const rect = gbr.call(this)
  if (rect.width === 0 && rect.height === 0 && rect.x === 0 && rect.y === 0) {
    return new DOMRect(84, 23, 168, 46)
  }
  return rect
}
// React Flow's updateNodeInternals reads offsetWidth/offsetHeight to decide
// whether a node is measurable; jsdom reports 0 for both, which leaves nodes
// permanently "unmeasured" and edges unrendered.
Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
  configurable: true, get() { return 168 },
})
Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
  configurable: true, get() { return 46 },
})
if (!('DOMMatrixReadOnly' in globalThis)) {
  class DOMMatrixReadOnlyStub {
    m22 = 1
    constructor(_transform?: string) {}
  }
  ;(globalThis as Record<string, unknown>).DOMMatrixReadOnly = DOMMatrixReadOnlyStub
}
if (!HTMLElement.prototype.scrollTo) {
  HTMLElement.prototype.scrollTo = () => {}
}
// SVG measurement APIs jsdom lacks (React Flow edge labels call getBBox)
if (!('getBBox' in SVGElement.prototype)) {
  (SVGElement.prototype as unknown as Record<string, unknown>).getBBox = function () {
    return { x: 0, y: 0, width: 120, height: 16,
      toJSON: () => ({}) } as unknown as SVGRect
  }
}
if (!('getComputedTextLength' in SVGElement.prototype)) {
  (SVGElement.prototype as unknown as Record<string, unknown>).getComputedTextLength =
    function () { return 80 }
}
if (!('requestAnimationFrame' in globalThis)) {
  ;(globalThis as Record<string, unknown>).requestAnimationFrame = (cb: FrameRequestCallback) =>
    setTimeout(() => cb(performance.now()), 0)
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  localStorage.clear()
})

/** The switchable-domain answer every page implicitly needs.
 *
 * A deployment serves ONE active ontology, and the editing session loads the
 * package of whichever domain the server calls active. So a page under test
 * that does not mention domains still asks for this: without it the canvas has
 * no domain to load and stays empty. Declared last, so a test that wants to
 * pin a different active domain just supplies its own route. */
export const DOMAINS = {
  domains: [{
    name: 'manufacturing-system', display: '离散制造运营系统', description: '',
    path: '/tmp/pkg', objects: 2, links: 1, actions: 1, active: true,
  }],
  active: 'manufacturing-system',
}

/** Route-based fetch mock for component tests: (path, init) => body | status */
type MockRoute = {
  match: RegExp | string | ((url: string) => boolean)
  status?: number
  body: any | ((url: string, init?: RequestInit) => unknown)
}

export function mockFetch(routes: MockRoute[]) {
  const calls: Array<{ url: string; init?: RequestInit }> = []
  const all: MockRoute[] = [
    ...routes,
    { match: (url: string) => /\/admin\/domains$/.test(url), body: DOMAINS },
  ]
  const fn = vi.fn(async (input: any, init?: RequestInit) => {
    const url = String(input)
    calls.push({ url, init })
    const route = all.find((r) => (typeof r.match === 'string' ? url.includes(r.match) : typeof r.match === 'function' ? r.match(url) : r.match.test(url)))
    if (!route) {
      return new Response(JSON.stringify({ code: 'NOT_FOUND', message: `no mock for ${url}` }), { status: 404 })
    }
    const body = typeof route.body === 'function' ? route.body(url, init) : route.body
    return new Response(JSON.stringify(body), {
      status: route.status ?? 200,
      headers: { 'content-type': 'application/json' },
    })
  })
  globalThis.fetch = fn as unknown as typeof fetch
  // `routes` is live: mutating it retargets subsequent calls (a demo run whose
  // world changes after promotion needs exactly that)
  return { calls, fn, routes }
}

/** Ontology snapshot fixture shared by component/integration tests. */
export const META = {
  package: 'manufacturing-system',
  content_hash: 'deadbeefcafe1234',
  roles: ['technician', 'supervisor'],
  objects: {
    'sales-order': {
      display: '销售订单',
      primaryKey: ['so_id'],
      properties: {
        so_id: { type: 'string', required: true, marking: null, display: '订单号', description: null, owner: null, derived: null },
        customer_id: { type: 'string', required: true, marking: null, display: '客户编号', description: null, owner: null, derived: null },
        status: {
          type: 'enum[DRAFT, CONFIRMED]', required: false, marking: null,
          display: '状态', description: '订单在业务流中的位置', owner: 'ontology', derived: null,
        },
        days_to_due: {
          type: 'decimal(8,2)', required: false, marking: null, display: '距交付(天)', description: null,
          owner: null, derived: { kind: 'expr', expr: '(due_date - now()) / 86400000', entry: null, triggers: [] },
        },
      },
      links: ['sales-order-customer'],
      actions: ['confirm-sales-order'],
    },
    customer: {
      display: '客户',
      primaryKey: ['customer_id'],
      properties: {
        customer_id: { type: 'string', required: true, marking: null, display: '客户编号', description: null, owner: null, derived: null },
        region: {
          type: 'string', required: false, marking: 'commercial',
          display: '区域', description: '行级授权属性', owner: 'ontology', derived: null,
        },
      },
      links: ['sales-order-customer'],
      actions: [],
    },
  },
  actions: {
    'confirm-sales-order': {
      display: '确认销售订单',
      target: 'sales-order',
      parameters: {
        confirmed_note: { type: 'string', required: false },
        priority: { type: 'enum[LOW, HIGH]', required: false },
      },
    },
  },
  functions: { 'material-availability': { entry: 'availability.py:material_availability', parameters: { product_id: { type: 'string', required: true } } } },
  projections: {},
}

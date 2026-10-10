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
/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // AntV G6 (+dagre) is only needed on graph views: split it out of the entry
  // chunk so first paint never waits on it (loaded on demand by the canvas).
  // Every route is lazy too (see App.tsx), so each page is its own chunk.
  build: {
    // (rolldown option; vitest's defineConfig typing lags behind, hence the cast.
    // `advancedChunks` was the deprecated spelling, renamed to `codeSplitting`.)
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [{ name: 'g6', test: /node_modules[\\/]+(@antv|@dagrejs)/ }],
        },
      },
    },
  } as any,
  server: {
    port: 5173,
    proxy: {
      // dev proxy: frontend on :5173, backend (ontogeny serve) on :8000
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})

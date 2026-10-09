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
import { spawn, type ChildProcess } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import path from 'node:path'

/** Spawns the real Python backend (tests/e2e_server.py), waits for readiness,
 *  and exposes its port via web/.e2e-port; kills it on teardown. */
export default async function globalSetup(): Promise<() => Promise<void>> {
  const repo = path.resolve(__dirname, '..', '..')
  const marker = path.join(repo, 'web', '.e2e-port')
  const child: ChildProcess = spawn('.venv/bin/python', ['tests/e2e_server.py'], {
    cwd: repo,
    env: { ...process.env, PYTHONPATH: path.join(repo, 'server') },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  let stderr = ''
  child.stderr!.on('data', (d) => (stderr += String(d)))

  const port = await new Promise<number>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`backend not ready in 60s\n${stderr}`)), 60_000)
    let buf = ''
    child.stdout!.on('data', (d) => {
      buf += String(d)
      const m = /READY (\d+)/.exec(buf)
      if (m) {
        clearTimeout(timer)
        resolve(Number(m[1]))
      }
    })
    child.on('exit', (code) => {
      clearTimeout(timer)
      reject(new Error(`backend exited early (${code})\n${stderr}`))
    })
  })

  const base = `http://127.0.0.1:${port}`
  const deadline = Date.now() + 90_000
  let ok = false
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${base}/api/v1/meta/ontology`)
      if (r.ok) {
        ok = true
        break
      }
    } catch {
      /* retry */
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  if (!ok) throw new Error(`backend on :${port} never became healthy\n${stderr}`)

  writeFileSync(marker, String(port))

  return async () => {
    child.kill('SIGTERM')
    await new Promise((r) => setTimeout(r, 300))
  }
}

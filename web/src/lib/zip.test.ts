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
import { describe, expect, it } from 'vitest'
import { buildZip, crc32, folderEntries, type ZipEntry } from './zip'

const enc = new TextEncoder()

/** Minimal STORE-zip reader: EOCD -> central directory -> (name, crc, offset,
 *  size). Enough to prove the writer's structure round-trips; full format
 *  correctness is cross-checked against Python's zipfile in CI scripts. */
function readStoreZip(bytes: Uint8Array): Array<{ name: string; data: Uint8Array }> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  // find EOCD by scanning back from the end (no comment is written)
  let eocd = -1
  for (let i = bytes.length - 22; i >= 0; i--) {
    if (view.getUint32(i, true) === 0x06054b50) { eocd = i; break }
  }
  if (eocd < 0) throw new Error('no EOCD')
  const count = view.getUint16(eocd + 10, true)
  const cdOffset = view.getUint32(eocd + 16, true)

  const out: Array<{ name: string; data: Uint8Array }> = []
  let at = cdOffset
  for (let n = 0; n < count; n++) {
    if (view.getUint32(at, true) !== 0x02014b50) throw new Error('bad central header')
    const crc = view.getUint32(at + 16, true)
    const size = view.getUint32(at + 24, true)
    const nameLen = view.getUint16(at + 28, true)
    const localOff = view.getUint32(at + 42, true)
    const name = new TextDecoder().decode(bytes.subarray(at + 46, at + 46 + nameLen))
    // local header: name starts at +30, data right after
    if (view.getUint32(localOff, true) !== 0x04034b50) throw new Error('bad local header')
    const data = bytes.subarray(localOff + 30 + nameLen, localOff + 30 + nameLen + size)
    if (crc32(data) !== crc) throw new Error(`crc mismatch for ${name}`)
    out.push({ name, data })
    at += 46 + nameLen
  }
  return out
}

describe('crc32', () => {
  it('matches known check values', () => {
    expect(crc32(enc.encode('hello'))).toBe(0x3610a686)
    expect(crc32(enc.encode(''))).toBe(0x00000000)
    expect(crc32(enc.encode('The quick brown fox jumps over the lazy dog'))).toBe(0x414fa339)
  })
})

describe('buildZip', () => {
  it('round-trips entries through a structural reader with CRCs', async () => {
    const entries: ZipEntry[] = [
      { path: 'ontology.yaml', data: enc.encode('apiVersion: ontogeny/v1\nkind: Ontology\n') },
      { path: 'objects/product.yaml', data: enc.encode('# product\n') },
      { path: 'functions/lib.py', data: enc.encode('def run():\n    return {"ok": True}\n') },
    ]
    const blob = buildZip(entries)
    const bytes = new Uint8Array(await blob.arrayBuffer())
    // the two zip magic signatures
    expect(bytes[0]).toBe(0x50) // 'P'
    expect(bytes[1]).toBe(0x4b) // 'K'

    const read = readStoreZip(bytes)
    expect(read.map(e => e.name)).toEqual(entries.map(e => e.path))
    read.forEach((e, i) => {
      expect(new TextDecoder().decode(e.data)).toBe(new TextDecoder().decode(entries[i].data))
    })
  })

  it('handles empty entry lists (valid empty zip)', async () => {
    const bytes = new Uint8Array(await buildZip([]).arrayBuffer())
    expect(readStoreZip(bytes)).toEqual([])
  })
})

describe('folderEntries', () => {
  const mk = (path: string, content: string) => {
    const f = new File([content], path.split('/').pop() as string)
    Object.defineProperty(f, 'webkitRelativePath', { value: path })
    return f
  }

  it('strips the root folder and drops junk files', async () => {
    const files = [
      mk('my-domain/ontology.yaml', 'apiVersion: ontogeny/v1\n'),
      mk('my-domain/objects/a.yaml', '# a\n'),
      mk('my-domain/functions/__pycache__/a.pyc', 'junk'),
      mk('my-domain/.DS_Store', 'junk'),
      mk('my-domain/.git/config', 'junk'),
      mk('my-domain/functions/f.py', 'def f(): pass\n'),
    ]
    const { entries, root, skipped } = await folderEntries(files)
    expect(root).toBe('my-domain')
    expect(entries.map(e => e.path)).toEqual([
      'functions/f.py', 'objects/a.yaml', 'ontology.yaml',
    ])
    expect(skipped.sort()).toEqual(['.DS_Store', '.git/config', 'functions/__pycache__/a.pyc'])
    expect(new TextDecoder().decode(entries[2].data)).toBe('apiVersion: ontogeny/v1\n')
  })

  it('returns nothing for an empty selection', async () => {
    const { entries, root } = await folderEntries([])
    expect(entries).toEqual([])
    expect(root).toBe('')
  })
})

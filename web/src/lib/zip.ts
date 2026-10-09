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
/** A minimal ZIP writer (STORE method — no compression).
 *
 * Used by the domain-import dialog to turn a picked FOLDER into the zip the
 * server's `/admin/domains/import` expects. Browsers cannot upload a
 * directory as one body, but a folder picker yields every file with its
 * relative path, and a stored (uncompressed) zip is just those bytes plus
 * fixed little-endian headers — so the package is assembled client-side with
 * zero dependencies. The server already bounds entry count and extracted
 * size, so the writer only has to be correct, not clever.
 */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256)
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    table[n] = c >>> 0
  }
  return table
})()

export function crc32(data: Uint8Array): number {
  let c = 0xffffffff
  for (let i = 0; i < data.length; i++) c = CRC_TABLE[(c ^ data[i]) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

export interface ZipEntry {
  path: string
  data: Uint8Array
}

/** DOS date/time for a fixed epoch (2026-01-01 00:00): the archive's content
 *  is what matters, and a stable timestamp keeps builds reproducible. */
const DOS_TIME = 0
const DOS_DATE = ((2026 - 1980) << 9) | (1 << 5) | 1


export function buildZip(entries: ZipEntry[]): Blob {
  const enc = new TextEncoder()
  const parts: Array<{ head: Uint8Array; name: Uint8Array; data: Uint8Array; offset: number }> = []
  const central: Uint8Array[] = []
  let offset = 0

  for (const e of entries) {
    if (e.path.includes('\\')) throw new Error(`zip paths use /: ${e.path}`)
    const name = enc.encode(e.path)
    const crc = crc32(e.data)

    const local = new Uint8Array(30 + name.length)
    const lv = new DataView(local.buffer)
    lv.setUint32(0, 0x04034b50, true)      // local file header signature
    lv.setUint16(4, 20, true)              // version needed
    lv.setUint16(6, 0x0800, true)          // flags: UTF-8 names
    lv.setUint16(8, 0, true)               // method: STORE
    lv.setUint16(10, DOS_TIME, true)
    lv.setUint16(12, DOS_DATE, true)
    lv.setUint32(14, crc, true)
    lv.setUint32(18, e.data.length, true)  // compressed size (== stored)
    lv.setUint32(22, e.data.length, true)  // uncompressed size
    lv.setUint16(26, name.length, true)
    lv.setUint16(28, 0, true)              // extra length
    local.set(name, 30)

    const cd = new Uint8Array(46 + name.length)
    const cv = new DataView(cd.buffer)
    cv.setUint32(0, 0x02014b50, true)      // central directory signature
    cv.setUint16(4, 20, true)              // version made by
    cv.setUint16(6, 20, true)              // version needed
    cv.setUint16(8, 0x0800, true)          // flags: UTF-8
    cv.setUint16(10, 0, true)              // method: STORE
    cv.setUint16(12, DOS_TIME, true)
    cv.setUint16(14, DOS_DATE, true)
    cv.setUint32(16, crc, true)
    cv.setUint32(20, e.data.length, true)
    cv.setUint32(24, e.data.length, true)
    cv.setUint16(28, name.length, true)
    cv.setUint16(30, 0, true)              // extra
    cv.setUint16(32, 0, true)              // comment
    cv.setUint16(34, 0, true)              // disk number
    cv.setUint16(36, 0, true)              // internal attrs
    cv.setUint32(38, 0, true)              // external attrs
    cv.setUint32(42, offset, true)         // local header offset
    cd.set(name, 46)

    parts.push({ head: local, name, data: e.data, offset })
    central.push(cd)
    offset += local.length + e.data.length
  }

  const centralSize = central.reduce((n, c) => n + c.length, 0)
  const eocd = new Uint8Array(22)
  const ev = new DataView(eocd.buffer)
  ev.setUint32(0, 0x06054b50, true)        // end-of-central-directory signature
  ev.setUint16(8, entries.length, true)    // entries on this disk
  ev.setUint16(10, entries.length, true)   // total entries
  ev.setUint32(12, centralSize, true)
  ev.setUint32(16, offset, true)           // central directory offset

  const total = offset + centralSize + 22
  const out = new Uint8Array(total)
  let at = 0
  for (const p of parts) {
    out.set(p.head, at); at += p.head.length
    out.set(p.data, at); at += p.data.length
  }
  for (const c of central) { out.set(c, at); at += c.length }
  out.set(eocd, at)
  return new Blob([out], { type: 'application/zip' })
}

/** Entries of a picked folder, ready for buildZip: strips the browser-added
 *  top-level directory name (the package folder itself) and drops the files
 *  no ontology package ever wants (.DS_Store, bytecode caches, VCS dirs). */
export async function folderEntries(
  files: FileList | File[],
): Promise<{ entries: ZipEntry[]; root: string; skipped: string[] }> {
  const list = Array.from(files as Array<File & { webkitRelativePath?: string }>)
  if (!list.length) return { entries: [], root: '', skipped: [] }
  const root = (list[0].webkitRelativePath || list[0].name).split('/')[0] ?? ''

  const JUNK = new Set(['.DS_Store', 'Thumbs.db'])
  const JUNK_DIRS = new Set(['__pycache__', '.git', 'node_modules', '.idea', '.vscode'])
  const entries: ZipEntry[] = []
  const skipped: string[] = []
  for (const f of list) {
    const rel = f.webkitRelativePath || f.name
    const inside = root && rel.startsWith(root + '/') ? rel.slice(root.length + 1) : rel
    if (!inside || inside.endsWith('/')) continue
    const segs = inside.split('/')
    const junk = segs.some(s => JUNK_DIRS.has(s) || JUNK.has(s) || s.endsWith('.pyc') || s.endsWith('.pyo'))
    if (junk) { skipped.push(inside); continue }
    entries.push({ path: inside, data: new Uint8Array(await f.arrayBuffer()) })
  }
  entries.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0))
  return { entries, root, skipped }
}

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
 * Lightweight i18n: no runtime dependency, typed keys, persisted choice,
 * `document.documentElement.lang` kept in sync.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { zh } from './zh'
import { en } from './en'

const LANGUAGES = ['zh', 'en'] as const
export type Language = (typeof LANGUAGES)[number]

type Dict = Record<string, string>
export const DICTS: Record<Language, Dict> = { zh, en }

const STORAGE_KEY = 'ontogeny.lang'

function detectLanguage(): Language {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'zh' || saved === 'en') return saved
  // first-time visitors default to EN; an explicit 中文 pick (or a saved
  // choice) wins over browser locale
  return 'en'
}

function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template
  // both `{key}` and the newer `{{key}}` spellings are accepted so catalog
  // entries can migrate one line at a time
  return template.replace(/\{\{(\w+)\}\}|\{(\w+)\}/g, (whole, k1, k2) => {
    const key = k1 ?? k2
    return params[key] === undefined ? whole : String(params[key])
  })
}

interface I18nValue {
  lang: Language
  setLang: (lang: Language) => void
  t: (key: string, params?: Record<string, string | number>) => string
  /** Count-aware lookup for a message that carries a number.
   *
   * English needs `1 props` to read `1 prop`, and no amount of interpolation
   * fixes that — so a counted message is stored as `<key>.one` / `<key>.other`
   * and picked here. Chinese has no plural form, so both entries hold the same
   * text there. */
  plural: (key: string, count: number, params?: Record<string, string | number>) => string
  /** Pick the localized value of a {zh, en} pair (tour content, DSL displays). */
  pick: <T>(pair: { zh: T; en: T } | undefined) => T | undefined
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children, initial }: { children: ReactNode; initial?: Language }) {
  const [lang, setLangState] = useState<Language>(() => initial ?? detectLanguage())

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, lang)
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
  }, [lang])

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => {
      const dict = DICTS[lang]
      const text = dict[key] ?? DICTS.en[key] ?? key
      return interpolate(text, params)
    },
    [lang],
  )

  const plural = useCallback(
    (key: string, count: number, params?: Record<string, string | number>) => {
      const dict = DICTS[lang]
      const suffix = count === 1 ? 'one' : 'other'
      const full = `${key}.${suffix}`
      const text = dict[full] ?? DICTS.en[full] ?? `${count} ${key}`
      return interpolate(text, { ...params, count })
    },
    [lang],
  )

  const pick = useCallback(
    <T,>(pair: { zh: T; en: T } | undefined): T | undefined => (pair ? pair[lang] ?? pair.en : undefined),
    [lang],
  )

  const value = useMemo<I18nValue>(
    () => ({ lang, setLang: setLangState, t, plural, pick }),
    [lang, t, plural, pick],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used inside I18nProvider')
  return ctx
}

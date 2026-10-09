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
 * EvalReport — the eval verdicts of one proposal, rendered so a red report
 * explains itself.
 *
 * The old view listed bare suite names with a badge keyed off the report
 * OBJECT (always truthy), so every suite read "pass" even when the report
 * said otherwise — and nothing said what a suite is or which assertion
 * failed. This component:
 *
 * - reads `passed` off each suite REPORT (the real verdict; boolean entries
 *   from very old reports are honoured as-is),
 * - shows each suite's declared display name + description next to its
 *   kebab-case name (older reports without the metadata degrade to the name),
 * - lists the failed CASES with their reason (query assertion / action
 *   replay / agent probe), so "存在失败" names its evidence.
 */
import { useI18n } from '../i18n'
import { Badge } from './ui'

interface EvalCase {
  kind?: string
  name?: string
  action?: string
  ok?: boolean
  error?: string | null
  missing_columns?: string[]
  outcome_matches?: number
  replays?: number
}

interface SuiteReport {
  passed: boolean
  display?: string | null
  description?: string | null
  cases: EvalCase[]
}

/** Legacy reports store either a bare boolean or the runner's dict. */
function asSuiteReport(raw: unknown): SuiteReport {
  if (typeof raw === 'boolean') return { passed: raw, cases: [] }
  if (raw && typeof raw === 'object') {
    const r = raw as Record<string, unknown>
    return {
      passed: r.passed === true,
      display: (r.display as string | null) ?? null,
      description: (r.description as string | null) ?? null,
      cases: Array.isArray(r.cases) ? (r.cases as EvalCase[]) : [],
    }
  }
  return { passed: false, cases: [] }
}

/** One failed case, in human terms: which assertion, what it saw. */
function caseWhy(c: EvalCase): string | null {
  if (c.error) return c.error
  if (c.missing_columns?.length) return `missing columns: ${c.missing_columns.join(', ')}`
  if (typeof c.outcome_matches === 'number' && typeof c.replays === 'number') {
    return `${c.outcome_matches}/${c.replays} replays matched the candidate rules`
  }
  return null
}

export function EvalReport({ suites, passed }: { suites: Record<string, unknown>; passed?: boolean }) {
  const { t } = useI18n()
  const names = Object.keys(suites)

  const kindLabel = (c: EvalCase): string => {
    if (c.kind === 'replay') return t('proposal.case.replay')
    if (c.kind === 'agent') return t('proposal.case.agent')
    return t('proposal.case.query')
  }

  return (
    <div>
      {/* the overall verdict: what the report MEANS is written next to it, so
          "存在失败" reads as "promotion is blocked", not as an error code */}
      {typeof passed === 'boolean' ? (
        <div className="mb-2 flex items-center gap-2">
          {passed ? (
            <Badge tone="success"><span aria-hidden="true">✓ </span>{t('proposal.evalGreen')}</Badge>
          ) : (
            <Badge tone="danger">{t('proposal.evalRed')}</Badge>
          )}
          <span className="text-[11.5px] muted">{passed ? t('proposal.evalGreenHint') : t('proposal.evalRedHint')}</span>
        </div>
      ) : null}
      <ul className="flex flex-col gap-1.5">
        {names.map((name) => {
          const rep = asSuiteReport(suites[name])
          const failed = rep.cases.filter((c) => c.ok === false)
          return (
            <li
              key={name}
              className="rounded-lg px-3 py-2"
              style={{ background: 'var(--surface-sunken)' }}
              data-testid={`eval-suite-${name}`}
            >
              <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                <span className="min-w-0">
                  <span className="text-[12.5px] font-medium">{rep.display ?? name}</span>
                  <span className="ml-2 font-mono text-[11px] muted">{name}</span>
                </span>
                <Badge tone={rep.passed ? 'success' : 'danger'}>
                  {rep.passed ? t('proposal.suitePass') : t('proposal.suiteFail')}
                </Badge>
              </div>
              {rep.description ? (
                <p className="mt-1 text-[11.5px] leading-relaxed muted">{rep.description}</p>
              ) : null}
              {!rep.passed && failed.length ? (
                <div className="mt-1.5">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.06em]" style={{ color: 'var(--tone-danger-fg)' }}>
                    {t('proposal.failedCases')}
                  </div>
                  <ul className="mt-1 flex flex-col gap-1">
                    {failed.map((c, i) => (
                      <li key={i} className="text-[11.5px] leading-relaxed" style={{ color: 'var(--tone-danger-fg)' }}>
                        {kindLabel(c)}
                        {c.name ? <span className="font-mono"> · {c.name}</span> : null}
                        {c.action ? <span className="font-mono"> · {c.action}</span> : null}
                        {caseWhy(c) ? <span className="secondary-text"> — {caseWhy(c)}</span> : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </li>
          )
        })}
      </ul>
      <p className="mt-2 text-[11.5px] muted">{t('proposal.evalHint')}</p>
    </div>
  )
}

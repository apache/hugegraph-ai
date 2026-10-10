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
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { Button, Page, Badge, Card, EmptyState, KeyValue, Skeleton } from '../components/ui'
import { ErrorBanner } from '../components/ErrorBanner'
import { ObjectsDialog } from '../components/ObjectsDialog'
import { IconArrowLeft, IconChevron, IconNetwork, IconShield, IconSpark, IconTable } from '../components/icons'

export function TypeDetail() {
  const { type = '' } = useParams()
  const { t } = useI18n()
  const meta = useMeta()
  const [browse, setBrowse] = useState(false)

  if (meta.isLoading) return <Skeleton rows={6} />
  if (meta.error) return <ErrorBanner error={meta.error} />
  const obj = meta.data!.objects[type]
  if (!obj) return <ErrorBanner error={{ code: 'NOT_FOUND', message: `unknown object type: ${type}` }} />

  return (
    <Page>
      <h1 className="sr-only">{type}</h1>

      <div className="grid items-start gap-5 lg:grid-cols-[1.6fr_1fr]">
        {/* breadcrumb, type name and the data jump all live on the properties
            panel: it is the page's one primary surface */}
        <Card
          title={
            <span className="flex items-center gap-2">
              <Link className="ontogeny-link inline-flex items-center gap-1 text-[12.5px] muted" to="/ontology">
                <IconArrowLeft width={13} height={13} />
                {t('nav.ontology')}
              </Link>
              <span className="muted">/</span>
              <span className="font-mono">{type}</span>
            </span>
          }
          description={obj.display}
          padded={false}
          actions={
            <Button
              size="sm"
              variant="primary"
              data-testid="type-browse"
              onClick={() => setBrowse(true)}
              icon={<IconTable width={13} height={13} />}
            >
              {t('type.browse')}
            </Button>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th scope="col" className="ontogeny-th">{t('common.field')}</th>
                  <th scope="col" className="ontogeny-th">type</th>
                  <th scope="col" className="ontogeny-th">{t('type.required')}</th>
                  <th scope="col" className="ontogeny-th" title={t('type.ownerHint')}>{t('type.owner')}</th>
                  <th scope="col" className="ontogeny-th">{t('type.marking')}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(obj.properties).map(([prop, def]) => (
                  <tr key={prop} className="transition-colors hover:bg-[var(--surface-hover)]">
                    <td className="ontogeny-td">
                      {def.display ? <span className="block text-[12.5px] font-medium">{def.display}</span> : null}
                      <span className={`font-mono text-[12px] ${def.display ? 'muted text-[11px]' : ''}`}>{prop}</span>
                      {obj.primaryKey.includes(prop) ? (
                        <span className="ml-2 align-middle"><Badge tone="warning">PK</Badge></span>
                      ) : null}
                      {def.derived ? (
                        <span className="ml-2 align-middle" title={def.derived.expr ?? def.derived.entry ?? undefined}>
                          <Badge tone="violet">{t('type.derived')}</Badge>
                        </span>
                      ) : null}
                      {def.description ? (
                        <span className="mt-0.5 block text-[11px] muted">{def.description}</span>
                      ) : null}
                    </td>
                    <td className="ontogeny-td font-mono text-[11.5px] secondary-text">{def.type}</td>
                    <td className="ontogeny-td">{def.required ? <Badge tone="danger">{t('type.required')}</Badge> : <span className="muted">—</span>}</td>
                    <td className="ontogeny-td">
                      {/* the model states who owns each field; this column used
                          to be hard-coded to "source" for every property, so it
                          said nothing at all */}
                      {def.owner ? (
                        <Badge tone={def.owner === 'ontology' ? 'brand' : 'neutral'}>
                          {t(`type.owner.${def.owner}`)}
                        </Badge>
                      ) : <span className="muted">—</span>}
                    </td>
                    <td className="ontogeny-td">
                      {def.marking ? <Badge tone="warning" mono><IconShield width={11} height={11} />{def.marking}</Badge> : <span className="muted">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card padded={false} bodyClassName="[&>section+section]:border-t [&>section+section]:border-[var(--border-subtle)]">
          <section className="p-5">
            <h3 className="mb-3 text-[13px] font-semibold tracking-wide">{t('type.actions')}</h3>
            {obj.actions.length === 0 ? (
              <EmptyState compact icon={<IconSpark width={16} height={16} />} title={t('common.none')} description={t('type.noActions')} />
            ) : (
              <ul className="flex flex-col gap-2">
                {obj.actions.map((a) => (
                  <li key={a}>
                    <Link to={`/actions/${a}`} className="flex items-center justify-between gap-2 rounded-lg px-3 py-2 transition-colors hover:bg-[var(--surface-hover)]" style={{ background: 'var(--surface-sunken)' }}>
                      <span className="font-mono text-[12.5px]">{a}</span>
                      <IconChevron width={14} height={14} className="muted" />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="p-5">
            <h3 className="mb-3 text-[13px] font-semibold tracking-wide">{t('type.links')}</h3>
            {obj.links.length === 0 ? (
              <EmptyState compact icon={<IconNetwork width={16} height={16} />} title={t('common.none')} description={t('type.noLinks')} />
            ) : (
              <div className="flex flex-wrap gap-2">
                {obj.links.map((l) => <Badge key={l} tone="info" mono>{l}</Badge>)}
              </div>
            )}
          </section>

          <section className="p-5">
            <h3 className="mb-3 text-[13px] font-semibold tracking-wide">{t('type.primaryKey')}</h3>
            <KeyValue items={obj.primaryKey.map((k) => ({ key: k, value: obj.properties[k]?.type ?? '—', mono: true }))} />
          </section>
        </Card>
      </div>
      <ObjectsDialog type={browse ? type : null} onClose={() => setBrowse(false)} />
    </Page>
  )
}

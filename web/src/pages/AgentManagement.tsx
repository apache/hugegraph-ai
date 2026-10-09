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
 * Agent 会话管理 — one nav entry, three governance views.
 *
 * The console is a conversation; the *management* of agent runs is a separate
 * surface with its own tab bar:
 *
 * - 会话      every run, its frozen identity/budget, and its step trace;
 * - 待审批写入 the human gate for writes (approver must hold the action's permit);
 * - 插件      the catalogue: frozen principal, tool allow-list, approval posture.
 *
 * The active tab is URL-driven (`?tab=approvals`), so a blocked session, an
 * alert or the demo can deep-link straight to the right view.
 */
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { keys } from '../api/queries'
import { useI18n } from '../i18n'
import { Badge, Button, Card, Page, Tabs } from '../components/ui'
import { IconClock, IconCog, IconPlus, IconShield } from '../components/icons'
import { ApprovalsPanel, PluginsPanel, SessionsPanel } from './agent/panels'

type Tab = 'sessions' | 'approvals' | 'plugins'

const TABS: Tab[] = ['sessions', 'approvals', 'plugins']

export function AgentManagement() {
  const { t } = useI18n()
  const [params, setParams] = useSearchParams()
  const raw = params.get('tab') as Tab | null
  const tab: Tab = raw && TABS.includes(raw) ? raw : 'sessions'
  const setTab = (next: Tab) => {
    const p = new URLSearchParams(params)
    if (next === 'sessions') p.delete('tab') // the entry tab keeps a clean URL
    else p.set('tab', next)
    setParams(p)
  }

  const pending = useQuery({
    queryKey: keys.agentApprovals('pending'),
    queryFn: () => apiClient.agentApprovals('pending'),
    refetchInterval: 15000,
  })
  const pendingCount = pending.data?.approvals?.length ?? 0
  const plugins = useQuery({ queryKey: ['agent-plugins'], queryFn: apiClient.agentPlugins })
  const sessions = useQuery({
    queryKey: keys.agentSessions(''),
    queryFn: () => apiClient.agentSessions(),
    refetchInterval: 8000,
  })
  const sessionRows = sessions.data?.sessions ?? []
  const openCount = sessionRows.filter((s) => s.status === 'open').length
  const blockedCount = sessionRows.filter((s) => s.status === 'blocked_on_approval').length
  const finishedCount = sessionRows.filter((s) => s.status === 'finished').length

  return (
    <Page>
      <h1 className="sr-only">{t('agent.manage.title')}</h1>

      {/* ONE surface: the tab strip rides the card's toolbar row (hairline
          below, like every control row), the active panel fills the body —
          tabs and content read as a single module, not two stacked boxes.
          The header's right side carries the page's live governance numbers:
          create action, totals, and the pending-write alert. */}
      <Card
        padded={false}
        toolbar={
          <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-3 gap-y-2">
            <Tabs<Tab>
              tabs={[
                {
                  id: 'sessions', label: t('agent.sessions'), icon: <IconClock width={14} height={14} />,
                  count: sessions.data?.sessions.length || undefined, hint: t('agent.sessionsSubtitle'),
                },
                {
                  id: 'approvals',
                  label: t('agent.approvals'),
                  icon: <IconShield width={14} height={14} />,
                  count: pendingCount || undefined,
                  hint: t('agent.approvalsSubtitle'),
                },
                {
                  id: 'plugins', label: t('agent.plugins'), icon: <IconCog width={14} height={14} />,
                  count: plugins.data?.plugins.length || undefined, hint: t('agent.pluginsSubtitle'),
                },
              ]}
              value={tab}
              onChange={setTab}
            />
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {pendingCount ? <Badge tone="warning">{t('agent.queue.pending')}</Badge> : null}
              {/* creation belongs to the sessions tab — the button opens the
                  dialog through that panel, so hide it elsewhere */}
              {tab === 'sessions' ? (
                <Button
                  size="sm"
                  variant="primary"
                  data-testid="create-session"
                  onClick={() => window.dispatchEvent(new CustomEvent('ontogeny:agent-sessions-create'))}
                  icon={<IconPlus width={14} height={14} />}
                >
                  {t('agent.create')}
                </Button>
              ) : null}
              <Badge tone="neutral" mono>{sessionRows.length} {t('agent.stat.sessions')}</Badge>
              {openCount ? <Badge tone="success" mono>{t('agent.summary.open')} {openCount}</Badge> : null}
              {blockedCount ? <Badge tone="warning" mono>{t('agent.summary.blocked')} {blockedCount}</Badge> : null}
              {finishedCount ? <Badge tone="info" mono>{t('agent.summary.finished')} {finishedCount}</Badge> : null}
            </div>
          </div>
        }
        bodyClassName="p-4 sm:p-5"
      >
        {tab === 'sessions' ? <SessionsPanel /> : null}
        {tab === 'approvals' ? <ApprovalsPanel /> : null}
        {tab === 'plugins' ? <PluginsPanel /> : null}
      </Card>
    </Page>
  )
}

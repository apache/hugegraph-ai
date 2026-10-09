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
import { lazy, Suspense } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { I18nProvider } from './i18n'
import { AuthProvider, useAuth } from './api/auth'
import { Login } from './pages/Login'
import { OntologyDraftProvider } from './pages/ontology/draft'
import { Skeleton } from './components/ui'
import { Dashboard } from './pages/Dashboard'

/** Everything except the dashboard is loaded on navigation.
 *
 * The entry chunk carried every page including the two canvas engines, so first
 * paint waited on code most sessions never run. The dashboard is the landing
 * route, so it stays in the entry; the shell and its navigation are already
 * there for the same reason. */
const OntologyExplorer = lazy(() => import('./pages/OntologyExplorer').then((m) => ({ default: m.OntologyExplorer })))
const TypeDetail = lazy(() => import('./pages/TypeDetail').then((m) => ({ default: m.TypeDetail })))
const ObjectsBrowser = lazy(() => import('./pages/ObjectsBrowser').then((m) => ({ default: m.ObjectsBrowser })))
const ObjectDetail = lazy(() => import('./pages/ObjectDetail').then((m) => ({ default: m.ObjectDetail })))
const ActionRunner = lazy(() => import('./pages/ActionRunner').then((m) => ({ default: m.ActionRunner })))
const FunctionTester = lazy(() => import('./pages/FunctionTester').then((m) => ({ default: m.FunctionTester })))
const GraphExplorer = lazy(() => import('./pages/GraphExplorer').then((m) => ({ default: m.GraphExplorer })))
const Knowledge = lazy(() => import('./pages/Knowledge').then((m) => ({ default: m.Knowledge })))
const Action = lazy(() => import('./pages/Action').then((m) => ({ default: m.Action })))
const AgentManagement = lazy(() => import('./pages/AgentManagement').then((m) => ({ default: m.AgentManagement })))
const EvolveConsole = lazy(() => import('./pages/EvolveConsole').then((m) => ({ default: m.EvolveConsole })))
const ProposalDetail = lazy(() => import('./pages/ProposalDetail').then((m) => ({ default: m.ProposalDetail })))
const Audit = lazy(() => import('./pages/Audit').then((m) => ({ default: m.Audit })))
const Admin = lazy(() => import('./pages/Admin').then((m) => ({ default: m.Admin })))
const Access = lazy(() => import('./pages/Access').then((m) => ({ default: m.Access })))

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 } },
})

/** Route-level fallback: a page-shaped skeleton, so a slow chunk looks like the
 *  page loading rather than a blank shell. */
function RouteFallback() {
  return (
    <div className="p-1">
      <Skeleton rows={8} />
    </div>
  )
}

/** The gate. Renders the shell only for a signed-in account.
 *
 * `loading` is its own state: the answer comes from the server, so rendering the
 * login form while the first `/auth/me` is in flight would flash it at every
 * reload for users who are already signed in. */
function RequireAuth() {
  const { principal, loading } = useAuth()
  if (loading) {
    return (
      <div className="grid min-h-full place-items-center" style={{ background: 'var(--surface-app)' }}>
        <Skeleton rows={4} className="w-[320px]" />
      </div>
    )
  }
  if (!principal) return <Login />
  return <Router />
}

export function Router() {
  return (
    <AppShell>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          {/* the guided tour merged into the demo page; keep old bookmarks working */}
          <Route path="/ontology" element={<OntologyExplorer />} />
          <Route path="/ontology/:type" element={<TypeDetail />} />
          {/* the semantic and kinetic halves of the ontology, each editable;
              /data (the old single preview) still resolves to the semantic one */}
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/action" element={<Action />} />
          {/* /data was the old single "everything at once" page; the model now
              lives on /knowledge and /action, and a type's rows open in a dialog
              from wherever the type is shown. Old links land on Knowledge. */}
          <Route path="/data" element={<Navigate to="/knowledge" replace />} />
          <Route path="/objects" element={<Navigate to="/knowledge" replace />} />
          <Route path="/objects/:type" element={<ObjectsBrowser />} />
          <Route path="/objects/:type/:id" element={<ObjectDetail />} />
          <Route path="/actions/:name" element={<ActionRunner />} />
          <Route path="/functions/:name" element={<FunctionTester />} />
          <Route path="/graph" element={<GraphExplorer />} />
          {/* the agent conversation is a floating dock now (bottom-right, ⌘J from
              any page); only run management is still a route. Old /agent links
              land on the dashboard, one dock click away. */}
          <Route path="/agent" element={<Navigate to="/" replace />} />
          {/* sessions / pending writes / plugins are one surface with a tab bar;
              the per-view URLs stay valid so old links and alerts keep working */}
          <Route path="/agent/manage" element={<AgentManagement />} />
          <Route path="/agent/sessions" element={<Navigate to="/agent/manage" replace />} />
          <Route path="/agent/approvals" element={<Navigate to="/agent/manage?tab=approvals" replace />} />
          <Route path="/agent/plugins" element={<Navigate to="/agent/manage?tab=plugins" replace />} />
          <Route path="/evolve" element={<EvolveConsole />} />
          <Route path="/evolve/:id" element={<ProposalDetail />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/access" element={<Access />} />
          {/* extensions merged into the operations console; keep old bookmarks working */}
          <Route path="/extensions" element={<Navigate to="/admin?tab=capabilities" replace />} />
          {/* the assistant is a mode of the agent console now, and the console
              is the floating dock: both old bookmarks land on the dashboard */}
          <Route path="/assistant" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AppShell>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        {/* the session gate sits above everything: nothing inside the app is
            fetched or rendered until an account is signed in */}
        <BrowserRouter>
          <AuthProvider>
            {/* one editing session above the router: Knowledge and Action share
                a draft, so a rename on one page is visible on the other */}
            <OntologyDraftProvider>
              <RequireAuth />
            </OntologyDraftProvider>
          </AuthProvider>
        </BrowserRouter>
      </I18nProvider>
    </QueryClientProvider>
  )
}

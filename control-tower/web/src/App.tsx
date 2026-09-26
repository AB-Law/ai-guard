import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './lib/auth'
import { ActiveProcessProvider } from './lib/processConfig'
import { ProtectedRoute } from './components/ProtectedRoute'
import { AppShell } from './components/layout/AppShell'
import { LoginPage } from './pages/LoginPage'
import { OverviewPage } from './pages/OverviewPage'
import { ApplicationsPage } from './pages/ApplicationsPage'
import { ProcessWizardPage } from './pages/ProcessWizardPage'
import { ApprovalsPage } from './pages/ApprovalsPage'
import { CaseDetailPage } from './pages/CaseDetailPage'
import { LogsPage } from './pages/LogsPage'
import { AuditIntegrityPage } from './pages/AuditIntegrityPage'
import { ConfigPage } from './pages/ConfigPage'
import { DevelopersPage } from './pages/DevelopersPage'
import { OpsMetricsPage } from './pages/OpsMetricsPage'

const queryClient = new QueryClient()

/** Route table only — tests wrap this in MemoryRouter; production uses BrowserRouter. */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/developers" element={<AppShell><DevelopersPage /></AppShell>} />
      <Route path="/" element={<ProtectedRoute><OverviewPage /></ProtectedRoute>} />
      <Route path="/applications" element={<ProtectedRoute><ApplicationsPage /></ProtectedRoute>} />
      <Route path="/processes/new" element={<ProtectedRoute><ProcessWizardPage /></ProtectedRoute>} />
      <Route path="/approvals" element={<ProtectedRoute><ApprovalsPage /></ProtectedRoute>} />
      <Route path="/cases/:caseId" element={<ProtectedRoute><CaseDetailPage /></ProtectedRoute>} />
      <Route path="/logs" element={<ProtectedRoute><LogsPage /></ProtectedRoute>} />
      <Route path="/audit" element={<ProtectedRoute><AuditIntegrityPage /></ProtectedRoute>} />
      <Route path="/metrics" element={<ProtectedRoute><OpsMetricsPage /></ProtectedRoute>} />
      <Route path="/config" element={<ProtectedRoute><ConfigPage /></ProtectedRoute>} />
    </Routes>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ActiveProcessProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </ActiveProcessProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}

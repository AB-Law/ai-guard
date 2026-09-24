import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './lib/auth'
import { ActiveProcessProvider } from './lib/processConfig'
import { ProtectedRoute } from './components/ProtectedRoute'
import { LoginPage } from './pages/LoginPage'
import { OverviewPage } from './pages/OverviewPage'
import { ApplicationsPage } from './pages/ApplicationsPage'
import { ApprovalsPage } from './pages/ApprovalsPage'
import { CaseDetailPage } from './pages/CaseDetailPage'
import { LogsPage } from './pages/LogsPage'
import { AuditIntegrityPage } from './pages/AuditIntegrityPage'
import { ConfigPage } from './pages/ConfigPage'

const queryClient = new QueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ActiveProcessProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/" element={<ProtectedRoute><OverviewPage /></ProtectedRoute>} />
              <Route path="/applications" element={<ProtectedRoute><ApplicationsPage /></ProtectedRoute>} />
              <Route path="/approvals" element={<ProtectedRoute><ApprovalsPage /></ProtectedRoute>} />
              <Route path="/cases/:caseId" element={<ProtectedRoute><CaseDetailPage /></ProtectedRoute>} />
              <Route path="/logs" element={<ProtectedRoute><LogsPage /></ProtectedRoute>} />
              <Route path="/audit" element={<ProtectedRoute><AuditIntegrityPage /></ProtectedRoute>} />
              <Route path="/config" element={<ProtectedRoute><ConfigPage /></ProtectedRoute>} />
            </Routes>
          </BrowserRouter>
        </ActiveProcessProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}

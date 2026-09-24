import type { ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { useApprovalsList } from '../../lib/queries'

export function AppShell({ children }: { children: ReactNode }) {
  const { data: approvals } = useApprovalsList()
  const pendingApprovals = approvals?.length ?? 0

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg text-text-primary">
      <Sidebar pendingApprovals={pendingApprovals} />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">{children}</div>
    </div>
  )
}

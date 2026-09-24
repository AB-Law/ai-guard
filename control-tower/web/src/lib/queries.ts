// TanStack Query hooks over lib/api.ts — polling intervals mirror the Streamlit
// dashboard's 2s auto-refresh for live traffic (see dashboard/app.py).

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as api from './api'

export function useCases() {
  return useQuery({
    queryKey: ['cases'],
    queryFn: api.listCases,
    refetchInterval: 4000,
  })
}

export function useTrafficRecent(params: api.TrafficRecentParams = {}) {
  return useQuery({
    queryKey: ['traffic-recent', params],
    queryFn: () => api.trafficRecent(params),
    refetchInterval: 2000,
  })
}

export function useCase(caseId: string | undefined) {
  return useQuery({
    queryKey: ['case', caseId],
    queryFn: () => api.getCase(caseId as string),
    enabled: !!caseId,
  })
}

export function useCaseAudit(caseId: string | undefined) {
  return useQuery({
    queryKey: ['case-audit', caseId],
    queryFn: () => api.getCaseAudit(caseId as string),
    enabled: !!caseId,
  })
}

export function useVerifyAudit() {
  return useQuery({
    queryKey: ['audit-verify'],
    queryFn: api.verifyAudit,
  })
}

export function useApprovalsList() {
  return useQuery({
    queryKey: ['approvals'],
    queryFn: api.listApprovals,
    refetchInterval: 4000,
  })
}

export function useApprove() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ callId, action, actor }: { callId: string; action: 'approve' | 'reject'; actor: string }) =>
      api.approve(callId, action, actor),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['cases'] })
      client.invalidateQueries({ queryKey: ['traffic-recent'] })
      client.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}

export function useAuditEntries(params: api.AuditEntriesParams = {}, opts: { live?: boolean } = {}) {
  return useQuery({
    queryKey: ['audit-entries', params],
    queryFn: () => api.auditEntries(params),
    refetchInterval: opts.live === false ? false : 5000,
  })
}

export function useDemoTamper() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (enable: boolean) => api.demoTamper(enable),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['audit-verify'] })
      client.invalidateQueries({ queryKey: ['audit-entries'] })
    },
  })
}

export function useConfigs() {
  return useQuery({
    queryKey: ['configs'],
    queryFn: api.listConfigs,
    staleTime: 60_000,
  })
}

export function useApplications() {
  return useQuery({
    queryKey: ['applications'],
    queryFn: api.listApplications,
    refetchInterval: 10_000,
  })
}

export function useCreateApplication() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.createApplication,
    onSuccess: () => client.invalidateQueries({ queryKey: ['applications'] }),
  })
}

export function useRevokeApplication() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.revokeApplication,
    onSuccess: () => client.invalidateQueries({ queryKey: ['applications'] }),
  })
}

export function useSeedDemo() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.seedDemo,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ['cases'] })
      client.invalidateQueries({ queryKey: ['traffic-recent'] })
      client.invalidateQueries({ queryKey: ['approvals'] })
    },
  })
}

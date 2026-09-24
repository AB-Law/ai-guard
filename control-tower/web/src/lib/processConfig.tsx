// Active-process selection is UI-only — the backend has no notion of a single
// "active" process (any /cases request can name any process independently).
// This context just remembers which one the dashboard is currently showing,
// backed by the real configs from GET /configs (configs/*.yaml on disk).

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { useConfigs } from './queries'
import type { ProcessConfig } from './types'

const STORAGE_KEY = 'aegis.activeProcessId'

interface ActiveProcessContextValue {
  active: ProcessConfig | undefined
  processes: ProcessConfig[]
  isLoading: boolean
  setActiveId: (id: string) => void
}

const ActiveProcessContext = createContext<ActiveProcessContextValue | null>(null)

export function ActiveProcessProvider({ children }: { children: ReactNode }) {
  const { data: configsResponse, isLoading } = useConfigs()
  const processes = configsResponse?.processes ?? []
  const [activeId, setActiveId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY)
    } catch {
      return null
    }
  })

  // Once configs load, fall back to the first one if nothing (valid) is selected yet.
  useEffect(() => {
    if (processes.length === 0) return
    if (activeId && processes.some((p) => p.id === activeId)) return
    setActiveId(processes[0].id)
  }, [processes, activeId])

  function updateActiveId(id: string) {
    setActiveId(id)
    try {
      localStorage.setItem(STORAGE_KEY, id)
    } catch {
      // per-viewer convenience only — fine if it doesn't persist.
    }
  }

  const active = processes.find((p) => p.id === activeId)

  return (
    <ActiveProcessContext.Provider value={{ active, processes, isLoading, setActiveId: updateActiveId }}>
      {children}
    </ActiveProcessContext.Provider>
  )
}

export function useActiveProcess(): ActiveProcessContextValue {
  const ctx = useContext(ActiveProcessContext)
  if (!ctx) throw new Error('useActiveProcess must be used within ActiveProcessProvider')
  return ctx
}

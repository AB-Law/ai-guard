// Auth stub — there is no real backend auth yet. This just gates the app behind
// a login screen and remembers the "session" in localStorage, so the real
// implementation can slot in later by swapping what `login()` does.

import { createContext, useContext, useState, type ReactNode } from 'react'

const STORAGE_KEY = 'aegis.auth.user'

export interface AuthUser {
  email: string
}

interface AuthContextValue {
  user: AuthUser | null
  login: (email: string) => void
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

function readStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => readStoredUser())

  function login(email: string) {
    const next = { email }
    setUser(next)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
      // localStorage unavailable — session just won't survive a refresh.
    }
  }

  function logout() {
    setUser(null)
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {
      // ignore
    }
  }

  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

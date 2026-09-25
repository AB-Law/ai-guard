// Dashboard session: POST /auth/login exchanges the shared DASHBOARD_PASSWORD
// for a short-lived JWT (see api/auth.py). We store that token plus a
// locally-chosen email (used only for attribution — "actor" on approvals,
// display name — the backend has no concept of per-user identity, everyone
// shares one password) in localStorage.

import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import * as api from './api'

const USER_STORAGE_KEY = 'aegis.auth.user'

export interface AuthUser {
  email: string
}

interface AuthContextValue {
  user: AuthUser | null
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

function readStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_STORAGE_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // A stored user is only meaningful alongside a token — if one is missing
  // (e.g. the token expired and got cleared by a 401) neither counts as
  // signed in.
  const [user, setUser] = useState<AuthUser | null>(() => (api.getToken() ? readStoredUser() : null))

  useEffect(() => {
    function onUnauthorized() {
      setUser(null)
      try {
        localStorage.removeItem(USER_STORAGE_KEY)
      } catch {
        // ignore
      }
    }
    window.addEventListener(api.UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(api.UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  async function login(email: string, password: string) {
    const { access_token } = await api.login(password)
    api.setToken(access_token)
    const next = { email }
    setUser(next)
    try {
      localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(next))
    } catch {
      // localStorage unavailable — session just won't survive a refresh.
    }
  }

  function logout() {
    api.setToken(null)
    setUser(null)
    try {
      localStorage.removeItem(USER_STORAGE_KEY)
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

import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ShieldCheck } from 'lucide-react'
import { Input } from '../components/ui/Input'
import { Button } from '../components/ui/Button'
import { useAuth } from '../lib/auth'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(email || 'demo@aegis.dev', password)
      navigate('/', { replace: true })
    } catch {
      setError('Wrong password, or the server has no DASHBOARD_PASSWORD configured.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen w-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-[380px]">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <ShieldCheck size={34} className="text-accent" strokeWidth={1.5} />
          <div>
            <div className="text-lg font-extrabold tracking-wide">AEGIS</div>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
              Control Tower
            </div>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-7"
        >
          <div>
            <div className="text-[15px] font-bold">Sign in</div>
            <div className="mt-1 text-[12.5px] text-text-secondary">
              One shared dashboard password (set as <code className="font-mono">DASHBOARD_PASSWORD</code> on the
              server). Your email is just how your name shows up on approvals.
            </div>
          </div>

          <label className="flex flex-col gap-1.5 text-xs font-semibold text-text-secondary">
            Work email
            <Input
              type="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
          </label>

          <label className="flex flex-col gap-1.5 text-xs font-semibold text-text-secondary">
            Dashboard password
            <Input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>

          {error && <div className="text-xs font-semibold text-danger">{error}</div>}

          <Button type="submit" variant="accent" size="lg" className="mt-1 w-full" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>

        <div className="mt-4 text-center text-[11px] text-text-muted">
          SSO / per-user accounts — coming soon
        </div>
      </div>
    </div>
  )
}

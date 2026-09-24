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

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    // No backend auth yet — this just starts a local "session" so the rest of
    // the app has someone to attribute actions to. Wire a real /auth/login call here.
    login(email || 'demo@aegis.dev')
    navigate('/', { replace: true })
  }

  function continueAsDemo() {
    login('demo@aegis.dev')
    navigate('/', { replace: true })
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
              Authentication is not wired up yet — this screen is here so it can be
              configured later.
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
            Password
            <Input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>

          <Button type="submit" variant="accent" size="lg" className="mt-1 w-full">
            Sign in
          </Button>

          <div className="flex items-center gap-3 text-[11px] text-text-muted">
            <span className="h-px flex-1 bg-border" />
            or
            <span className="h-px flex-1 bg-border" />
          </div>

          <Button type="button" variant="default" size="lg" className="w-full" onClick={continueAsDemo}>
            Continue as demo user
          </Button>
        </form>

        <div className="mt-4 text-center text-[11px] text-text-muted">
          SSO / real auth provider — coming soon
        </div>
      </div>
    </div>
  )
}

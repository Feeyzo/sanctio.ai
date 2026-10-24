import React, { useState } from 'react'
import { api } from './api.js'

function useSubmit(path, onDone) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = (body) => async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try { onDone(await api(path, { method: 'POST', body })) } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return { error, busy, submit }
}

export function Login({ onDone, go }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { error, busy, submit } = useSubmit('/api/auth/login', onDone)
  return (
    <form className="card narrow login" onSubmit={submit({ email, password })}>
      <h2>Sign in</h2>
      <label>Email<input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <label>Password<input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      {error && <p className="error">{error}</p>}
      <button disabled={busy}>Sign in</button>
      <p className="muted small">New here? <a onClick={() => go('signup')}>Create an account</a></p>
    </form>
  )
}

export function Signup({ onDone, go }) {
  const [f, setF] = useState({ business_name: '', name: '', email: '', password: '' })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const { error, busy, submit } = useSubmit('/api/auth/signup', onDone)
  return (
    <form className="card narrow login" onSubmit={submit(f)}>
      <h2>Create your account</h2>
      <p className="muted">You get an API key straight away. No card needed.</p>
      <label>Business name<input required minLength={2} value={f.business_name} onChange={set('business_name')} placeholder="e.g. SwiftShip Logistics" /></label>
      <label>Your name<input required autoComplete="name" value={f.name} onChange={set('name')} /></label>
      <label>Work email<input type="email" required autoComplete="email" value={f.email} onChange={set('email')} /></label>
      <label>Password<input type="password" required minLength={8} autoComplete="new-password" value={f.password} onChange={set('password')} /><span className="small">At least 8 characters</span></label>
      {error && <p className="error">{error}</p>}
      <button disabled={busy}>Create account</button>
      <p className="muted small">Already have an account? <a onClick={() => go('login')}>Sign in</a></p>
    </form>
  )
}

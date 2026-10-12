import React, { useCallback, useEffect, useState } from 'react'
import { api, fmtDate, pretty } from './api.js'

const TABS = ['Overview', 'Handoffs', 'Approvals', 'Conversations', 'Security']

function Login({ onLogin }) {
  const [email, setEmail] = useState('admin@shopdemo.ng')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  async function submit(e) {
    e.preventDefault()
    try {
      const d = await api('/api/admin/login', { method: 'POST', body: { email, password } })
      onLogin(d)
    } catch (err) { setError(err.message) }
  }
  return (
    <form className="card narrow login" onSubmit={submit}>
      <h2>Support team sign in</h2>
      <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      {error && <p className="error">{error}</p>}
      <button>Sign in</button>
    </form>
  )
}

function Bars({ data }) {
  const entries = Object.entries(data || {}).sort((a, b) => b[1] - a[1])
  const max = Math.max(1, ...entries.map((e) => e[1]))
  if (!entries.length) return <p className="muted">No data yet.</p>
  return (
    <div className="bars">
      {entries.map(([k, v]) => (
        <div key={k} className="bar-row">
          <span>{pretty(k)}</span>
          <div className="bar"><div style={{ width: `${(v / max) * 100}%` }} /></div>
          <b>{v}</b>
        </div>
      ))}
    </div>
  )
}

function Overview({ auth }) {
  const [s, setS] = useState(null)
  useEffect(() => { api('/api/admin/stats', { headers: auth }).then(setS) }, [auth])
  if (!s) return <p className="muted">Loading…</p>
  const tiles = [
    ['Conversations', s.total_conversations], ['Resolved by AI', `${s.ai_resolution_rate}%`],
    ['Handoff rate', `${s.handoff_rate}%`], ['Open handoffs', s.open_handoffs],
    ['Pending approvals', s.pending_approvals], ['Security events', s.security_events],
    ['Avg. sentiment', s.average_sentiment],
  ]
  return (
    <>
      <div className="tiles">{tiles.map(([k, v]) => <div key={k} className="tile"><span>{k}</span><b>{v}</b></div>)}</div>
      <div className="grid2">
        <div className="card"><h3>Issue categories</h3><Bars data={s.conversations_by_category} /></div>
        <div className="card"><h3>Handoff reasons</h3><Bars data={s.handoff_reasons} /></div>
        <div className="card"><h3>Action decisions</h3><Bars data={s.actions_by_decision} /></div>
      </div>
    </>
  )
}

function Handoffs({ auth, open }) {
  const [rows, setRows] = useState([])
  const load = useCallback(() => api('/api/admin/handoffs', { headers: auth }).then(setRows), [auth])
  useEffect(() => { load() }, [load])
  const claim = async (id) => { await api(`/api/admin/handoffs/${id}/claim`, { method: 'POST', headers: auth }); load() }
  if (!rows.length) return <p className="muted">No handoffs yet.</p>
  return rows.map((h) => (
    <div key={h.id} className={`card handoff ${h.priority}`}>
      <div className="row-head">
        <strong>#{h.id} · {h.customer}</strong>
        <span className={`pill ${h.priority === 'high' ? 'bad' : 'warn'}`}>{h.priority}</span>
        <span className="pill">{h.status}{h.assigned_to ? ` · ${h.assigned_to}` : ''}</span>
        <span className="muted small">{fmtDate(h.created_at)}</span>
      </div>
      <div className="reasons">{h.reasons.map((r) => <span key={r} className="chip">{pretty(r)}</span>)}</div>
      <p className="small">{h.summary}</p>
      <div className="actions">
        {h.status === 'open' && <button onClick={() => claim(h.id)}>Claim</button>}
        <button className="ghost" onClick={() => open(h.conversation_id)}>Open conversation</button>
      </div>
    </div>
  ))
}

function Approvals({ auth }) {
  const [rows, setRows] = useState([])
  const load = useCallback(() => api('/api/admin/approvals', { headers: auth }).then(setRows), [auth])
  useEffect(() => { load() }, [load])
  const decide = async (id, v) => { await api(`/api/admin/approvals/${id}/${v}`, { method: 'POST', headers: auth }); load() }
  if (!rows.length) return <p className="muted">No actions waiting for approval.</p>
  return rows.map((a) => (
    <div key={a.id} className="card">
      <div className="row-head"><strong>{pretty(a.action)}</strong><span className="muted small">conversation #{a.conversation_id} · {fmtDate(a.at)}</span></div>
      <pre>{JSON.stringify(a.params, null, 2)}</pre>
      <p className="small muted">{a.reason}</p>
      <div className="actions">
        <button onClick={() => decide(a.id, 'approve')}>Approve</button>
        <button className="danger" onClick={() => decide(a.id, 'reject')}>Reject</button>
      </div>
    </div>
  ))
}

function ConversationDetail({ auth, id, back }) {
  const [c, setC] = useState(null)
  const [reply, setReply] = useState('')
  const load = useCallback(() => api(`/api/admin/conversations/${id}`, { headers: auth }).then(setC), [auth, id])
  useEffect(() => { load() }, [load])
  if (!c) return <p className="muted">Loading…</p>
  const send = async (e) => {
    e.preventDefault()
    if (!reply.trim()) return
    await api(`/api/admin/conversations/${id}/reply`, { method: 'POST', headers: auth, body: { message: reply } })
    setReply(''); load()
  }
  const resolve = async () => { await api(`/api/admin/conversations/${id}/resolve`, { method: 'POST', headers: auth }); load() }
  return (
    <div className="grid-detail">
      <div className="card">
        <button className="ghost" onClick={back}>← Back</button>
        <h3>Conversation #{c.id} · {c.customer} <span className="muted small">{c.customer_email}</span></h3>
        <p><span className="pill">{pretty(c.status)}</span> <span className="pill">{pretty(c.category)}</span></p>
        <div className="messages admin">
          {c.messages.map((m) => (
            <div key={m.id} className={`bubble ${m.sender}`}>
              {m.sender === 'human' && <div className="tag">Support team</div>}
              {m.content}
              {m.sender === 'customer' && (
                <div className="meta">sentiment {m.sentiment} · {pretty(m.intent) || '—'}{m.confidence != null ? ` · ${Math.round(m.confidence * 100)}%` : ''}</div>
              )}
            </div>
          ))}
        </div>
        <form className="composer" onSubmit={send}>
          <input value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Reply as support team…" />
          <button>Send</button>
          {c.status !== 'resolved' && <button type="button" className="ghost" onClick={resolve}>Mark resolved</button>}
        </form>
      </div>
      <div className="card">
        <h3>Action audit log</h3>
        {!c.actions.length && <p className="muted">No actions.</p>}
        {c.actions.map((a) => (
          <div key={a.id} className="audit">
            <b>{pretty(a.action)}</b>{' '}
            <span className={`pill ${['executed', 'approved'].includes(a.decision) ? 'good' : ['denied', 'rejected'].includes(a.decision) ? 'bad' : 'warn'}`}>{pretty(a.decision)}</span>
            <div className="small muted">{JSON.stringify(a.params)} — {a.reason}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function Conversations({ auth, open }) {
  const [rows, setRows] = useState([])
  const [status, setStatus] = useState('')
  useEffect(() => { api(`/api/admin/conversations${status ? `?status=${status}` : ''}`, { headers: auth }).then(setRows) }, [auth, status])
  return (
    <div className="card">
      <div className="filters">
        {['', 'active', 'handed_off', 'resolved'].map((s) => (
          <button key={s} className={status === s ? 'active' : 'ghost'} onClick={() => setStatus(s)}>{s ? pretty(s) : 'all'}</button>
        ))}
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>#</th><th>Customer</th><th>Category</th><th>Status</th><th>Sentiment</th><th>Last message</th><th>Updated</th></tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} onClick={() => open(c.id)}>
                <td>{c.id}</td><td>{c.customer}</td><td>{pretty(c.category)}</td><td>{pretty(c.status)}</td>
                <td>{c.sentiment}</td><td className="ellipsis">{c.last_message}</td><td className="small">{fmtDate(c.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Security({ auth }) {
  const [rows, setRows] = useState([])
  useEffect(() => { api('/api/admin/security-events', { headers: auth }).then(setRows) }, [auth])
  if (!rows.length) return <p className="muted">No security events recorded.</p>
  return (
    <div className="card table-wrap">
      <table>
        <thead><tr><th>Time</th><th>Type</th><th>Conversation</th><th>Detail</th></tr></thead>
        <tbody>{rows.map((e) => (
          <tr key={e.id}><td className="small">{fmtDate(e.at)}</td><td><span className="pill bad">{pretty(e.type)}</span></td>
            <td>#{e.conversation_id}</td><td className="small">{e.detail.message || JSON.stringify(e.detail)}</td></tr>
        ))}</tbody>
      </table>
    </div>
  )
}

export default function Admin() {
  const [session, setSession] = useState(() => {
    try { return JSON.parse(sessionStorage.getItem('admin') || 'null') } catch { return null }
  })
  const [tab, setTab] = useState('Overview')
  const [openId, setOpenId] = useState(null)
  const login = (d) => { setSession(d); try { sessionStorage.setItem('admin', JSON.stringify(d)) } catch { /* ignore */ } }
  const logout = () => { setSession(null); try { sessionStorage.removeItem('admin') } catch { /* ignore */ } }
  if (!session) return <Login onLogin={login} />
  const auth = { Authorization: `Bearer ${session.token}` }
  const open = (id) => { setOpenId(id); setTab('Conversations') }
  return (
    <div>
      <div className="tabs">
        {TABS.map((t) => <button key={t} className={tab === t ? 'active' : ''} onClick={() => { setTab(t); setOpenId(null) }}>{t}</button>)}
        <span className="spacer" /><span className="muted small">{session.name}</span>
        <button className="ghost" onClick={logout}>Sign out</button>
      </div>
      {tab === 'Overview' && <Overview auth={auth} />}
      {tab === 'Handoffs' && <Handoffs auth={auth} open={open} />}
      {tab === 'Approvals' && <Approvals auth={auth} />}
      {tab === 'Conversations' && (openId ? <ConversationDetail auth={auth} id={openId} back={() => setOpenId(null)} /> : <Conversations auth={auth} open={open} />)}
      {tab === 'Security' && <Security auth={auth} />}
    </div>
  )
}

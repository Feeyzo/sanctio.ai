import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { api, fmtDate, pretty } from './api.js'
import Setup from './Setup.jsx'
import Actions from './Actions.jsx'
import Knowledge from './Knowledge.jsx'
import Playground from './Playground.jsx'

const NAV = [
  ['Agent', ['Overview', 'Setup', 'Actions', 'Knowledge', 'Playground']],
  ['Support', ['Handoffs', 'Approvals', 'Conversations', 'Security']],
]
const ABOUT = {
  Overview: 'How your agent is doing across all conversations.',
  Setup: 'Your API key, webhook secret and what the agent knows about your business.',
  Actions: 'What your agent may do in your app. Each action calls an endpoint on your backend, after the security engine has approved it.',
  Knowledge: 'Troubleshooting guides, FAQs and policies. The agent answers from these, together with what it looks up in your app.',
  Playground: 'Chat with your agent as one of your customers and see what it decides on each turn.',
  Handoffs: 'Conversations the agent passed to your team, with the reason and a summary.',
  Approvals: 'Actions waiting for a person to approve or reject.',
  Conversations: 'Every conversation, with its messages and the audit log of actions.',
  Security: 'Suspected prompt-injection attempts and the actions that were blocked.',
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

function Overview({ auth, setTab }) {
  const [s, setS] = useState(null)
  useEffect(() => { api('/api/admin/stats', { headers: auth }).then(setS).catch(() => {}) }, [auth])
  if (!s) return <p className="muted">Loading…</p>
  const tiles = [
    ['Conversations', s.total_conversations], ['Resolved by AI', `${s.ai_resolution_rate}%`],
    ['Handoff rate', `${s.handoff_rate}%`], ['Open handoffs', s.open_handoffs],
    ['Pending approvals', s.pending_approvals], ['Security events', s.security_events],
    ['Avg. sentiment', s.average_sentiment],
  ]
  return (
    <>
      {!s.actions_configured && (
        <div className="card notice">
          <strong>Finish setting up your agent</strong>
          <p className="muted">Your agent can chat, but it cannot look anything up or act yet. Connect your app by adding
            actions, and add your troubleshooting guides so it can help customers properly.</p>
          <div className="actions">
            <button onClick={() => setTab('Actions')}>Add an action</button>
            <button className="ghost" onClick={() => setTab('Knowledge')}>Add a guide</button>
            <button className="ghost" onClick={() => setTab('Setup')}>View API key</button>
          </div>
        </div>
      )}
      <div className="tiles">{tiles.map(([k, v]) => <div key={k} className="tile"><span>{k}</span><b>{v}</b></div>)}</div>
      <div className="grid2">
        <div className="card"><h3>Issue categories</h3><Bars data={s.conversations_by_category} /></div>
        <div className="card"><h3>Handoff reasons</h3><Bars data={s.handoff_reasons} /></div>
        <div className="card"><h3>Action decisions</h3><Bars data={s.actions_by_decision} /></div>
      </div>
    </>
  )
}

const CHANNELS = { web: 'Web', whatsapp: 'WhatsApp' }

function ChannelBadge({ channel }) {
  return <span className={`pill channel ${channel}`}>{CHANNELS[channel] || channel}</span>
}

function ChannelFilter({ value, onChange }) {
  return (
    <div className="filters">
      {['', 'web', 'whatsapp'].map((c) => (
        <button key={c} className={value === c ? 'active' : 'ghost'} onClick={() => onChange(c)}>{c ? CHANNELS[c] : 'all channels'}</button>
      ))}
    </div>
  )
}

function Handoffs({ auth, open }) {
  const [rows, setRows] = useState([])
  const [channel, setChannel] = useState('')
  const load = useCallback(() => api(`/api/admin/handoffs${channel ? `?channel=${channel}` : ''}`, { headers: auth }).then(setRows), [auth, channel])
  useEffect(() => { load() }, [load])
  const claim = async (id) => { await api(`/api/admin/handoffs/${id}/claim`, { method: 'POST', headers: auth }); load() }
  const filter = <ChannelFilter value={channel} onChange={setChannel} />
  if (!rows.length) return <>{filter}<div className="card empty">No handoffs yet. Conversations that need a person will appear here.</div></>
  return <>{filter}{rows.map((h) => (
    <div key={h.id} className={`card handoff ${h.priority}`}>
      <div className="row-head">
        <strong>#{h.id} · {h.customer}</strong>
        <ChannelBadge channel={h.channel} />
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
  ))}</>
}

function Approvals({ auth }) {
  const [rows, setRows] = useState([])
  const load = useCallback(() => api('/api/admin/approvals', { headers: auth }).then(setRows), [auth])
  useEffect(() => { load() }, [load])
  const [error, setError] = useState('')
  const decide = async (id, v) => {
    setError('')
    try { await api(`/api/admin/approvals/${id}/${v}`, { method: 'POST', headers: auth }) } catch (e) { setError(e.message) }
    load()
  }
  if (!rows.length) return <div className="card empty">No actions waiting for approval.</div>
  return rows.map((a) => (
    <div key={a.id} className="card">
      {error && <p className="error">{error}</p>}
      <div className="row-head"><strong>{pretty(a.action)}</strong><span className="muted small">conversation #{a.conversation_id} · {fmtDate(a.at)}</span></div>
      {a.summary && <p>{a.summary}</p>}
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
  const [error, setError] = useState('')
  const load = useCallback(() => api(`/api/admin/conversations/${id}`, { headers: auth }).then(setC), [auth, id])
  useEffect(() => { load() }, [load])
  if (!c) return <p className="muted">Loading…</p>
  const send = async (e) => {
    e.preventDefault()
    if (!reply.trim()) return
    setError('')
    try {
      await api(`/api/admin/conversations/${id}/reply`, { method: 'POST', headers: auth, body: { message: reply } })
      setReply('')
    } catch (err) { setError(err.message) }
    load()
  }
  const resolve = async () => { await api(`/api/admin/conversations/${id}/resolve`, { method: 'POST', headers: auth }); load() }
  return (
    <div className="grid-detail">
      <div className="card">
        <button className="ghost" onClick={back}>← Back</button>
        <h3>Conversation #{c.id} · {c.customer} <span className="muted small">{c.customer_email || (c.channel === 'whatsapp' ? c.contact : '')}</span></h3>
        <p><ChannelBadge channel={c.channel} /> <span className="pill">{pretty(c.status)}</span> <span className="pill">{pretty(c.category)}</span></p>
        {c.whatsapp_window_open === false && (
          <p className="notice-text small">The customer last wrote more than 24 hours ago. WhatsApp only allows a template message until they write again.</p>
        )}
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
        {error && <p className="error">{error}</p>}
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
  const [channel, setChannel] = useState('')
  useEffect(() => {
    const q = new URLSearchParams(Object.entries({ status, channel }).filter(([, v]) => v)).toString()
    api(`/api/admin/conversations${q ? `?${q}` : ''}`, { headers: auth }).then(setRows)
  }, [auth, status, channel])
  return (
    <div className="card">
      <div className="filters">
        {['', 'active', 'handed_off', 'resolved'].map((s) => (
          <button key={s} className={status === s ? 'active' : 'ghost'} onClick={() => setStatus(s)}>{s ? pretty(s) : 'all'}</button>
        ))}
      </div>
      <ChannelFilter value={channel} onChange={setChannel} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>#</th><th>Customer</th><th>Channel</th><th>Category</th><th>Status</th><th>Sentiment</th><th>Last message</th><th>Updated</th></tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} onClick={() => open(c.id)}>
                <td>{c.id}</td><td>{c.customer}</td><td><ChannelBadge channel={c.channel} /></td><td>{pretty(c.category)}</td><td>{pretty(c.status)}</td>
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
  if (!rows.length) return <div className="card empty">No security events recorded.</div>
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

export default function Dashboard({ session, onExpired }) {
  const [tab, setTab] = useState('Overview')
  const [openId, setOpenId] = useState(null)
  const auth = useMemo(() => ({ Authorization: `Bearer ${session.token}` }), [session.token])
  // any dashboard call answered with 401 means the sign-in has expired
  useEffect(() => {
    window.addEventListener('sanctio:unauthorized', onExpired)
    return () => window.removeEventListener('sanctio:unauthorized', onExpired)
  }, [onExpired])
  // counts shown next to the queues that need a person; refreshed whenever the page changes
  const [counts, setCounts] = useState({})
  useEffect(() => {
    api('/api/admin/stats', { headers: auth })
      .then((s) => setCounts({ Handoffs: s.open_handoffs, Approvals: s.pending_approvals })).catch(() => {})
  }, [auth, tab])
  const open = (id) => { setOpenId(id); setTab('Conversations') }
  return (
    <div className="dash">
      <nav className="side" aria-label="Dashboard">
        <div className="who"><strong>{session.business}</strong><span className="muted small">{session.name}</span></div>
        {NAV.map(([group, items]) => (
          <React.Fragment key={group}>
            <div className="group">{group}</div>
            {items.map((t) => (
              <button key={t} className={tab === t ? 'active' : ''} aria-current={tab === t ? 'page' : undefined}
                onClick={() => { setTab(t); setOpenId(null) }}>
                {t}{counts[t] > 0 && <span className="badge">{counts[t]}</span>}
              </button>
            ))}
          </React.Fragment>
        ))}
      </nav>
      <div>
      <header className="page-head"><h2>{tab}</h2><p>{ABOUT[tab]}</p></header>
      {tab === 'Overview' && <Overview auth={auth} setTab={setTab} />}
      {tab === 'Setup' && <Setup auth={auth} newApiKey={session.newApiKey} />}
      {tab === 'Actions' && <Actions auth={auth} />}
      {tab === 'Knowledge' && <Knowledge auth={auth} />}
      {tab === 'Playground' && <Playground auth={auth} />}
      {tab === 'Handoffs' && <Handoffs auth={auth} open={open} />}
      {tab === 'Approvals' && <Approvals auth={auth} />}
      {tab === 'Conversations' && (openId ? <ConversationDetail auth={auth} id={openId} back={() => setOpenId(null)} /> : <Conversations auth={auth} open={open} />)}
      {tab === 'Security' && <Security auth={auth} />}
      </div>
    </div>
  )
}

import React, { useEffect, useRef, useState } from 'react'
import { api, pretty } from './api.js'

function sentimentClass(s) {
  if (s <= -0.6) return 'bad'
  if (s < -0.05) return 'warn'
  if (s > 0.05) return 'good'
  return ''
}

export default function Playground({ auth }) {
  const [customerId, setCustomerId] = useState('')
  const [chatAuth, setChatAuth] = useState(null)
  const [conv, setConv] = useState(null)
  const [messages, setMessages] = useState([])
  const [trace, setTrace] = useState(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef(null)

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // poll for human replies once the conversation is with the support team
  useEffect(() => {
    if (!chatAuth || !conv || trace?.status !== 'handed_off') return
    const t = setInterval(async () => {
      try {
        const d = await api(`/api/v1/conversations/${conv}`, { headers: chatAuth })
        setMessages(d.messages.map((m) => ({ sender: m.sender, content: m.content })))
      } catch { /* ignore */ }
    }, 4000)
    return () => clearInterval(t)
  }, [chatAuth, conv, trace?.status])

  async function start(e) {
    e.preventDefault()
    setError('')
    try {
      const d = await api('/api/admin/playground/session', { method: 'POST', headers: auth, body: { customer_id: customerId.trim() } })
      setChatAuth({ Authorization: `Bearer ${d.session_token}` })
      setConv(null); setTrace(null); setMessages([])
    } catch (err) { setError(err.message) }
  }

  async function send(e) {
    e.preventDefault()
    const message = text.trim()
    if (!message || busy) return
    setText(''); setBusy(true); setError('')
    setMessages((m) => [...m, { sender: 'customer', content: message }])
    try {
      const d = await api('/api/v1/chat', { method: 'POST', headers: chatAuth, body: { message, conversation_id: conv } })
      setConv(d.conversation_id)
      setTrace(d)
      setMessages((m) => [...m, { sender: 'agent', content: d.reply }])
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  if (!chatAuth) {
    return (
      <form className="card narrow login" onSubmit={start}>
        <h3>Chat with your agent as a customer</h3>
        <p className="muted">Enter a customer ID from your own system. The agent will call your endpoints as that
          customer, exactly as it would in your app, so use a test account.</p>
        <label>Customer ID<input required maxLength={64} value={customerId} onChange={(e) => setCustomerId(e.target.value)} placeholder="e.g. 42 or C-1001" /></label>
        {error && <p className="error">{error}</p>}
        <button>Start chat</button>
      </form>
    )
  }

  return (
    <div className="chat-layout">
      <section className="card chat">
        <div className="chat-head">
          <div><strong>Playground</strong><span className="muted"> · customer {customerId}</span></div>
          <button className="ghost" onClick={() => setChatAuth(null)}>Change customer</button>
        </div>
        <div className="messages">
          {!messages.length && <p className="muted">Say something a customer would, for example “Where is my order?”</p>}
          {messages.map((m, i) => (
            <div key={i} className={`bubble ${m.sender}`}>
              {m.sender === 'human' && <div className="tag">Support team</div>}
              {m.content}
            </div>
          ))}
          {busy && <div className="bubble agent typing">…</div>}
          <div ref={endRef} />
        </div>
        <form className="composer" onSubmit={send}>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type your message…" maxLength={1000} aria-label="Message" />
          <button disabled={busy || !text.trim()}>Send</button>
        </form>
        {error && <p className="error">{error}</p>}
      </section>

      <aside className="card trace">
        <h3>What the agent decided</h3>
        {!trace ? <p className="muted">Send a message to see the analysis for each turn.</p> : (
          <dl>
            <dt>Sentiment</dt>
            <dd><span className={`pill ${sentimentClass(trace.sentiment)}`}>{trace.sentiment_label} ({trace.sentiment})</span></dd>
            <dt>Intent</dt><dd>{pretty(trace.intent) || '—'}</dd>
            <dt>AI confidence</dt><dd>{trace.confidence != null ? `${Math.round(trace.confidence * 100)}%` : '—'}</dd>
            <dt>Action requested</dt><dd>{trace.action ? pretty(trace.action.name) : 'none'}</dd>
            <dt>Security engine decision</dt>
            <dd>{trace.action ? <><span className={`pill ${trace.action.decision === 'executed' ? 'good' : ['denied', 'failed'].includes(trace.action.decision) ? 'bad' : 'warn'}`}>{pretty(trace.action.decision)}</span><div className="muted small">{trace.action.reason}</div></> : '—'}</dd>
            <dt>Human handoff</dt>
            <dd>{trace.handoff ? <><span className={`pill ${trace.handoff.priority === 'high' ? 'bad' : 'warn'}`}>{trace.handoff.priority} priority</span><div className="muted small">{trace.handoff.reasons.map(pretty).join(', ')}</div></> : 'no'}</dd>
            <dt>Conversation</dt><dd>#{trace.conversation_id} · {pretty(trace.status)}</dd>
            <dt>Model</dt><dd>{trace.engine}</dd>
          </dl>
        )}
      </aside>
    </div>
  )
}

import React, { useEffect, useState } from 'react'
import { api, fmtDate } from './api.js'

// Setup page card: shows whether WhatsApp is ready, connects the business number from Meta,
// and links customers' WhatsApp numbers to their accounts.

const Tick = ({ ok, children }) => <li className={ok ? 'ok' : 'missing'}>{ok ? '✓' : '✗'} {children}</li>

export default function WhatsAppSetup({ auth }) {
  const [s, setS] = useState(null)
  const [error, setError] = useState('')
  const [number, setNumber] = useState({ phone_number_id: '', display_phone: '' })
  const [link, setLink] = useState({ customer_id: '', customer_name: '', phone: '' })
  const [copied, setCopied] = useState(false)
  const webhook = window.location.origin + '/webhooks/whatsapp'

  const load = () => api('/api/admin/whatsapp/status', { headers: auth }).then(setS).catch((e) => setError(e.message))
  useEffect(() => { load() }, [auth])

  const run = async (fn) => {
    setError('')
    try { await fn(); await load() } catch (e) { setError(e.message) }
  }
  const addNumber = (e) => {
    e.preventDefault()
    run(async () => {
      await api('/api/admin/whatsapp/numbers', { method: 'POST', headers: auth, body: number })
      setNumber({ phone_number_id: '', display_phone: '' })
    })
  }
  const addLink = (e) => {
    e.preventDefault()
    run(async () => {
      await api('/api/admin/whatsapp/link', { method: 'POST', headers: auth, body: link })
      setLink({ customer_id: '', customer_name: '', phone: '' })
    })
  }
  const copy = () => { navigator.clipboard?.writeText(webhook); setCopied(true); setTimeout(() => setCopied(false), 1500) }

  if (!s) return <div className="card wa-setup"><h3>WhatsApp</h3><p className="muted">{error || 'Loading…'}</p></div>
  const ready = s.server.access_token && s.server.app_secret && s.server.verify_token && s.numbers.length > 0

  return (
    <div className="card wa-setup">
      <div className="row-head">
        <h3>WhatsApp</h3>
        <span className={'badge ' + (ready ? 'good' : 'warn')}>{ready ? 'Ready' : 'Not ready'}</span>
      </div>
      <p className="muted small">Customers can message your WhatsApp Business number and get the same agent, with the
        same rules, as the web chat.</p>

      <div className="wa-cols">
        <div>
          <h4>1. Server settings</h4>
          <ul className="checklist">
            <Tick ok={s.server.access_token}>Access token (<code>WHATSAPP_ACCESS_TOKEN</code>)</Tick>
            <Tick ok={s.server.app_secret}>App secret (<code>WHATSAPP_APP_SECRET</code>)</Tick>
            <Tick ok={s.server.verify_token}>Verify token (<code>WHATSAPP_VERIFY_TOKEN</code>)</Tick>
          </ul>
          <p className="muted small">These are set on the server (Render → Environment), not here.</p>

          <h4>2. Webhook in Meta</h4>
          <p className="small">Callback URL:</p>
          <div className="copy-row"><code>{webhook}</code>
            <button type="button" className="ghost" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button></div>
          <p className="muted small">Use the same verify token as the server, then subscribe to <code>messages</code>.</p>
          <p className="small">Last message received: <strong>{s.last_message_at
            ? fmtDate(s.last_message_at) : 'none yet'}</strong></p>
        </div>

        <div>
          <h4>3. Your business number</h4>
          {s.numbers.length ? (
            <ul className="plain">{s.numbers.map((n) => (
              <li key={n.id}>{n.display_phone || 'Number'} <span className="muted small">(ID {n.phone_number_id})</span>{' '}
                <button type="button" className="link" onClick={() => run(() =>
                  api(`/api/admin/whatsapp/numbers/${n.id}`, { method: 'DELETE', headers: auth }))}>remove</button></li>
            ))}</ul>
          ) : (
            <form className="inline-form" onSubmit={addNumber}>
              <input required pattern="\d{5,32}" placeholder="Phone number ID from Meta" value={number.phone_number_id}
                onChange={(e) => setNumber({ ...number, phone_number_id: e.target.value.trim() })} />
              <input placeholder="Display number, e.g. +1 555 123 4567" value={number.display_phone}
                onChange={(e) => setNumber({ ...number, display_phone: e.target.value })} />
              <button>Connect</button>
            </form>
          )}

          <h4>4. Link customers’ phones</h4>
          <p className="muted small">Only link a number after confirming the customer owns it. Messages from an unlinked
            number get general answers but cannot change anything.</p>
          <form className="inline-form" onSubmit={addLink}>
            <input required placeholder="Customer ID, e.g. C-1001" value={link.customer_id}
              onChange={(e) => setLink({ ...link, customer_id: e.target.value })} />
            <input placeholder="Name (optional)" value={link.customer_name}
              onChange={(e) => setLink({ ...link, customer_name: e.target.value })} />
            <input required placeholder="WhatsApp number, e.g. +2348031234567" value={link.phone}
              onChange={(e) => setLink({ ...link, phone: e.target.value })} />
            <button>Link</button>
          </form>
          {s.linked_customers.length > 0 && (
            <table className="small">
              <thead><tr><th>Customer</th><th>WhatsApp</th><th /></tr></thead>
              <tbody>{s.linked_customers.map((c) => (
                <tr key={c.customer_id}><td>{c.customer_id}{c.name ? ' · ' + c.name : ''}</td><td>{c.phone}</td>
                  <td><button type="button" className="link" onClick={() => run(() =>
                    api(`/api/admin/whatsapp/link/${encodeURIComponent(c.customer_id)}`, { method: 'DELETE', headers: auth }))}>unlink</button></td></tr>
              ))}</tbody>
            </table>
          )}
        </div>
      </div>
      {error && <p className="error small">{error}</p>}
    </div>
  )
}

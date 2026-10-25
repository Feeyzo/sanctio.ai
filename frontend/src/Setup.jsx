import React, { useEffect, useState } from 'react'
import { api } from './api.js'

export function Secret({ value }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* select manually */ }
  }
  return (
    <div className="secret">
      <code>{value}</code>
      <button type="button" className="ghost" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
    </div>
  )
}

export default function Setup({ auth, newApiKey }) {
  const [b, setB] = useState(null)
  const [key, setKey] = useState(newApiKey || '')
  const [confirmRotate, setConfirmRotate] = useState(false)
  const [showSecret, setShowSecret] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [llmTest, setLlmTest] = useState(null)
  const [testing, setTesting] = useState(false)
  const [resetState, setResetState] = useState('')  // '' | 'confirm' | 'working' | message
  useEffect(() => { api('/api/admin/business', { headers: auth }).then(setB).catch((e) => setError(e.message)) }, [auth])
  if (!b) return <p className="muted">{error || 'Loading…'}</p>

  const save = async (e) => {
    e.preventDefault()
    setError('')
    try {
      setB(await api('/api/admin/business', { method: 'PUT', headers: auth, body: { name: b.name, description: b.description } }))
      setSaved(true); setTimeout(() => setSaved(false), 1500)
    } catch (err) { setError(err.message) }
  }
  const testLlm = async () => {
    setTesting(true)
    setLlmTest(null)
    try { setLlmTest(await api('/api/admin/llm/test', { method: 'POST', headers: auth })) }
    catch (err) { setLlmTest({ ok: false, error: err.message }) }
    finally { setTesting(false) }
  }
  const resetDemo = async () => {
    setResetState('working')
    try {
      const d = await api('/api/admin/demo/reset', { method: 'POST', headers: auth })
      setResetState(d.shipments === 'done' ? 'Demo reset: conversations cleared and shipments restored.'
        : `Conversations cleared. Shipments: ${d.shipments}`)
    } catch (err) { setResetState(`Reset failed: ${err.message}`) }
  }
  const rotate = async () => {
    try {
      const d = await api('/api/admin/business/rotate-api-key', { method: 'POST', headers: auth })
      setKey(d.api_key)
      setConfirmRotate(false)
      setB(await api('/api/admin/business', { headers: auth }))
    } catch (err) { setError(err.message) }
  }

  return (
    <div className="grid2">
      <div className="card">
        <h3>API key</h3>
        {key ? (
          <>
            <p className="notice-text">Copy your API key now. It will not be shown again.</p>
            <Secret value={key} />
          </>
        ) : <p>Your key starts with <code>{b.api_key_prefix}…</code> <span className="muted">(the full key was shown once, when it was created)</span></p>}
        <p className="muted small">Keep it on your server. It is used to create customer sessions.</p>
        {confirmRotate ? (
          <div className="actions">
            <span className="small">The current key stops working immediately. Continue?</span>
            <button className="danger" onClick={rotate}>Yes, replace the key</button>
            <button className="ghost" onClick={() => setConfirmRotate(false)}>Keep it</button>
          </div>
        ) : <button className="ghost" onClick={() => setConfirmRotate(true)}>Create a new key</button>}

        <h3 className="gap">Webhook secret</h3>
        <p className="muted small">Sanctio signs every action request to your backend with this secret, so you can check
          the request is genuine.</p>
        {showSecret ? <Secret value={b.webhook_secret} /> : <button className="ghost" onClick={() => setShowSecret(true)}>Show secret</button>}

        {b.is_demo && (
          <>
            <h3 className="gap">Demo data</h3>
            <p className="muted small">Clears every conversation, handoff and log, and puts SwiftShip's shipments back
              to how they started. Use it before each rehearsal and before your presentation.</p>
            {resetState === 'confirm' ? (
              <div className="row-head">
                <button type="button" className="danger" onClick={resetDemo}>Yes, reset the demo</button>
                <button type="button" className="ghost" onClick={() => setResetState('')}>Cancel</button>
              </div>
            ) : (
              <button type="button" className="ghost" disabled={resetState === 'working'}
                onClick={() => setResetState('confirm')}>{resetState === 'working' ? 'Resetting…' : 'Reset demo'}</button>
            )}
            {resetState && !['confirm', 'working'].includes(resetState) && <p className="small">{resetState}</p>}
          </>
        )}

        <h3 className="gap">AI model</h3>
        <p>{b.llm_provider === 'gemini'
          ? (b.llm_status?.models || ['Google Gemini']).join(', then ')
          : 'Built-in rule-based engine'}</p>
        {b.llm_provider !== 'gemini' && <p className="muted small">No AI key is configured on this server, so the agent
          matches messages to your actions and guides by keyword, and only understands simple phrasing. Set{' '}
          <code>GEMINI_API_KEY</code> or <code>GROQ_API_KEY</code> on the server for full language understanding.</p>}
        {b.llm_provider === 'gemini' && b.llm_status?.last_call_ok === false && (
          <p className="error small">The last AI call failed, so the agent answered with the rule-based engine
            instead: {b.llm_status.last_error}</p>)}
        {b.llm_provider === 'gemini' && (
          <>
            <button type="button" className="ghost" disabled={testing} onClick={testLlm}>
              {testing ? 'Testing…' : 'Test AI'}</button>
            {llmTest && (llmTest.ok
              ? <p className="small">{llmTest.model} answered in {llmTest.seconds}s: “{llmTest.reply}”</p>
              : <p className="error small">The AI did not answer: {llmTest.error}</p>)}
          </>
        )}
      </div>

      <form className="card login" onSubmit={save}>
        <h3>Your business</h3>
        <label>Business name<input required minLength={2} value={b.name} onChange={(e) => setB({ ...b, name: e.target.value })} /></label>
        <label>What your business does
          <textarea rows={5} maxLength={2000} value={b.description} onChange={(e) => setB({ ...b, description: e.target.value })}
            placeholder="e.g. SwiftShip delivers parcels between Nigerian cities. Customers book pickups in our app and track them with a tracking number like SHP-1001." />
          <span className="small">The agent reads this to understand your customers' questions.</span>
        </label>
        {error && <p className="error">{error}</p>}
        <button>{saved ? 'Saved' : 'Save'}</button>
      </form>
    </div>
  )
}

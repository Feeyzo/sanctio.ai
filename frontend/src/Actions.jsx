import React, { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'

const BLANK = { name: '', description: '', url: '', params: [], mutates: false, risk: 'low', approval: 'never', approval_amount: '', enabled: true }
const BLANK_PARAM = { name: '', type: 'string', description: '', required: true, pattern: '' }

function ActionForm({ auth, initial, lastUrl, onSaved, onCancel }) {
  const [f, setF] = useState(() => ({ ...BLANK, url: lastUrl, ...initial, approval_amount: initial?.approval_amount ?? '' }))
  const [error, setError] = useState('')
  const set = (k, v) => setF((old) => ({ ...old, [k]: v }))
  const setParam = (i, k, v) => set('params', f.params.map((p, j) => (j === i ? { ...p, [k]: v } : p)))

  const save = async (e) => {
    e.preventDefault()
    setError('')
    const body = { ...f, approval: f.mutates ? f.approval : 'never',
      approval_amount: f.mutates && f.approval === 'over_amount' ? Number(f.approval_amount) : null }
    try {
      await api(f.id ? `/api/admin/actions/${f.id}` : '/api/admin/actions', { method: f.id ? 'PUT' : 'POST', headers: auth, body })
      onSaved()
    } catch (err) { setError(err.message) }
  }

  return (
    <form className="card login" onSubmit={save}>
      <h3>{f.id ? `Edit ${f.name}` : 'New action'}</h3>
      <div className="form-row">
        <label>Name<input required value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="cancel_shipment" pattern="[a-z][a-z0-9_]+" title="Lowercase letters, digits and underscores" /></label>
        <label>Endpoint URL<input required type="url" value={f.url} onChange={(e) => set('url', e.target.value)} placeholder="https://your-app.example.com/sanctio" /></label>
      </div>
      <label>Description<input required value={f.description} onChange={(e) => set('description', e.target.value)} placeholder="Cancel a shipment that has not been picked up yet" />
        <span className="small">The agent reads this to decide when the action applies.</span></label>

      <h4>Parameters the agent must collect</h4>
      {!f.params.length && <p className="muted small">None. The verified customer ID is always sent automatically.</p>}
      {f.params.map((p, i) => (
        <div key={i} className="param-row">
          <input required aria-label="Parameter name" value={p.name} onChange={(e) => setParam(i, 'name', e.target.value)} placeholder="tracking_number" />
          <select aria-label="Type" value={p.type} onChange={(e) => setParam(i, 'type', e.target.value)}>
            {['string', 'number', 'integer', 'boolean'].map((t) => <option key={t}>{t}</option>)}
          </select>
          <input aria-label="Description" value={p.description} onChange={(e) => setParam(i, 'description', e.target.value)} placeholder="tracking number (e.g. SHP-1001)" />
          <input aria-label="Pattern" value={p.pattern} onChange={(e) => setParam(i, 'pattern', e.target.value)} placeholder="Pattern, e.g. SHP-\d{4,8}" />
          <label className="check"><input type="checkbox" checked={p.required} onChange={(e) => setParam(i, 'required', e.target.checked)} />Required</label>
          <button type="button" className="ghost" onClick={() => set('params', f.params.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      {f.params.length < 8 && <button type="button" className="ghost" onClick={() => set('params', [...f.params, { ...BLANK_PARAM }])}>Add parameter</button>}

      <h4>Safety</h4>
      <label className="check"><input type="checkbox" checked={f.mutates} onChange={(e) => set('mutates', e.target.checked)} />
        This action changes data <span className="muted">(previewed first, and the customer must confirm)</span></label>
      <div className="form-row">
        <label>Risk level
          <select value={f.risk} onChange={(e) => set('risk', e.target.value)}>
            {['low', 'medium', 'high'].map((r) => <option key={r}>{r}</option>)}
          </select></label>
        {f.mutates && (
          <label>Human approval
            <select value={f.approval} onChange={(e) => set('approval', e.target.value)}>
              <option value="never">Not needed</option>
              <option value="always">Always</option>
              <option value="over_amount">When the amount is over a limit</option>
            </select></label>
        )}
        {f.mutates && f.approval === 'over_amount' && (
          <label>Limit<input required type="number" min="0" step="any" value={f.approval_amount} onChange={(e) => set('approval_amount', e.target.value)} placeholder="50000" />
            <span className="small">Compared with the "amount" your endpoint returns.</span></label>
        )}
      </div>
      <label className="check"><input type="checkbox" checked={f.enabled} onChange={(e) => set('enabled', e.target.checked)} />Enabled</label>
      {error && <p className="error">{error}</p>}
      <div className="actions"><button>Save action</button><button type="button" className="ghost" onClick={onCancel}>Cancel</button></div>
    </form>
  )
}

function TestPanel({ auth, action }) {
  const [customer, setCustomer] = useState('')
  const [params, setParams] = useState({})
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const run = async (e) => {
    e.preventDefault()
    setError(''); setResult(null)
    // send values as typed; the server converts them to each parameter's declared type
    const filled = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== ''))
    try {
      setResult(await api(`/api/admin/actions/${action.id}/test`, { method: 'POST', headers: auth, body: { customer_id: customer, params: filled } }))
    } catch (err) { setError(err.message) }
  }
  return (
    <form className="test-panel" onSubmit={run}>
      <p className="muted small">Sends a signed request to your endpoint{action.mutates ? ' as a dry run, so nothing is changed' : ''}.</p>
      <div className="form-row">
        <label>Customer ID<input required value={customer} onChange={(e) => setCustomer(e.target.value)} placeholder="An ID from your system" /></label>
        {action.params.map((p) => (
          <label key={p.name}>{p.name}<input required={p.required} value={params[p.name] || ''} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })} /></label>
        ))}
      </div>
      <button>Send test request</button>
      {error && <p className="error">{error}</p>}
      {result && (
        <>
          <p><span className={`pill ${result.ok ? 'good' : 'bad'}`}>{result.ok ? 'endpoint accepted' : result.unreachable ? 'could not reach endpoint' : 'endpoint refused'}</span> {result.error}</p>
          {result.warnings.map((w) => <p key={w} className="notice-text">{w}</p>)}
          {result.ok && <pre>{JSON.stringify({ summary: result.summary, amount: result.amount, data: result.data }, null, 2)}</pre>}
        </>
      )}
    </form>
  )
}

export default function Actions({ auth }) {
  const [rows, setRows] = useState(null)
  const [editing, setEditing] = useState(null) // null | {} (new) | action
  const [testing, setTesting] = useState(null)
  const [removing, setRemoving] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(() => api('/api/admin/actions', { headers: auth }).then(setRows).catch((e) => setError(e.message)), [auth])
  useEffect(() => { load() }, [load])
  if (!rows) return <p className="muted">{error || 'Loading…'}</p>
  if (editing) {
    return <ActionForm auth={auth} initial={editing} lastUrl={rows.at(-1)?.url || ''} onCancel={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />
  }
  const remove = async (id) => { await api(`/api/admin/actions/${id}`, { method: 'DELETE', headers: auth }); setRemoving(null); load() }
  return (
    <>
      <div className="row-head">
        <span className="spacer" />
        <button onClick={() => setEditing({})}>New action</button>
      </div>
      {!rows.length && <div className="card empty">No actions yet. Start with a read-only one, such as looking up an order or shipment.</div>}
      {rows.map((a) => (
        <div key={a.id} className="card">
          <div className="row-head">
            <strong><code>{a.name}</code></strong>
            <span className={`pill ${a.mutates ? 'warn' : 'good'}`}>{a.mutates ? 'changes data' : 'read-only'}</span>
            <span className="pill">{a.risk} risk</span>
            {a.approval !== 'never' && <span className="pill bad">{a.approval === 'always' ? 'needs approval' : `approval over ${Number(a.approval_amount).toLocaleString()}`}</span>}
            {!a.enabled && <span className="pill">disabled</span>}
          </div>
          <p>{a.description}</p>
          <p className="muted small">{a.params.length ? `Parameters: ${a.params.map((p) => p.name).join(', ')}` : 'No parameters'} · {a.url}</p>
          <div className="actions">
            <button className="ghost" onClick={() => setTesting(testing === a.id ? null : a.id)}>{testing === a.id ? 'Close test' : 'Test'}</button>
            <button className="ghost" onClick={() => setEditing(a)}>Edit</button>
            {removing === a.id
              ? <><button className="danger" onClick={() => remove(a.id)}>Delete for good</button><button className="ghost" onClick={() => setRemoving(null)}>Keep</button></>
              : <button className="ghost" onClick={() => setRemoving(a.id)}>Delete</button>}
          </div>
          {testing === a.id && <TestPanel auth={auth} action={a} />}
        </div>
      ))}
    </>
  )
}

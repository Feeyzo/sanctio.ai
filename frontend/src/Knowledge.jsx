import React, { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'

export default function Knowledge({ auth }) {
  const [rows, setRows] = useState(null)
  const [editing, setEditing] = useState(null) // null | { title, content, id? }
  const [removing, setRemoving] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(() => api('/api/admin/knowledge', { headers: auth }).then(setRows).catch((e) => setError(e.message)), [auth])
  useEffect(() => { load() }, [load])
  if (!rows) return <p className="muted">{error || 'Loading…'}</p>

  const save = async (e) => {
    e.preventDefault()
    setError('')
    try {
      await api(editing.id ? `/api/admin/knowledge/${editing.id}` : '/api/admin/knowledge',
        { method: editing.id ? 'PUT' : 'POST', headers: auth, body: { title: editing.title, content: editing.content } })
      setEditing(null); load()
    } catch (err) { setError(err.message) }
  }
  const remove = async (id) => { await api(`/api/admin/knowledge/${id}`, { method: 'DELETE', headers: auth }); setRemoving(null); load() }

  if (editing) {
    return (
      <form className="card login" onSubmit={save}>
        <h3>{editing.id ? 'Edit guide' : 'New guide'}</h3>
        <label>Title<input required minLength={2} maxLength={160} value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} placeholder="Late delivery" />
          <span className="small">Name the problem the way a customer would describe it.</span></label>
        <label>Steps or answer
          <textarea required rows={9} minLength={5} maxLength={6000} value={editing.content} onChange={(e) => setEditing({ ...editing, content: e.target.value })}
            placeholder={'1. Check the expected delivery date on your shipment.\n2. Make sure your phone is reachable. Riders call before delivery.\n3. If it is more than 2 days late, we will escalate it to dispatch.'} /></label>
        {error && <p className="error">{error}</p>}
        <div className="actions"><button>Save guide</button><button type="button" className="ghost" onClick={() => { setEditing(null); setError('') }}>Cancel</button></div>
      </form>
    )
  }
  return (
    <>
      <div className="row-head">
        <span className="spacer" />
        <button onClick={() => setEditing({ title: '', content: '' })}>New guide</button>
      </div>
      {!rows.length && <div className="card empty">No guides yet. Add the problems your customers ask about most.</div>}
      {rows.map((k) => (
        <div key={k.id} className="card">
          <strong>{k.title}</strong>
          <p className="pre-line">{k.content}</p>
          <div className="actions">
            <button className="ghost" onClick={() => setEditing(k)}>Edit</button>
            {removing === k.id
              ? <><button className="danger" onClick={() => remove(k.id)}>Delete for good</button><button className="ghost" onClick={() => setRemoving(null)}>Keep</button></>
              : <button className="ghost" onClick={() => setRemoving(k.id)}>Delete</button>}
          </div>
        </div>
      ))}
    </>
  )
}

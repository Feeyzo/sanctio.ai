import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import ChatDemo from './ChatDemo.jsx'
import Admin from './Admin.jsx'
import './styles.css'

function App() {
  const [route, setRoute] = useState(window.location.pathname.startsWith('/admin') ? 'admin' : 'chat')
  useEffect(() => {
    const onPop = () => setRoute(window.location.pathname.startsWith('/admin') ? 'admin' : 'chat')
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const go = (r) => {
    window.history.pushState({}, '', r === 'admin' ? '/admin' : '/')
    setRoute(r)
  }
  return (
    <>
      <header className="topbar">
        <div className="brand"><span className="logo">◆</span> SecureAgent <small>AI Customer Service API</small></div>
        <nav>
          <button className={route === 'chat' ? 'active' : ''} onClick={() => go('chat')}>Customer chat</button>
          <button className={route === 'admin' ? 'active' : ''} onClick={() => go('admin')}>Admin dashboard</button>
        </nav>
      </header>
      <main>{route === 'admin' ? <Admin /> : <ChatDemo />}</main>
    </>
  )
}

createRoot(document.getElementById('root')).render(<App />)

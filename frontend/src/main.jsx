import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import Landing from './Landing.jsx'
import Docs from './Docs.jsx'
import { Login, Signup } from './Auth.jsx'
import Dashboard from './Dashboard.jsx'
import './styles.css'

const ROUTES = ['docs', 'login', 'signup', 'dashboard']
const SECTIONS = [['product', 'Product'], ['how', 'How it works'], ['features', 'Features'], ['technology', 'Technology']]
const routeOf =(path) => ROUTES.find((r) => path.startsWith(`/${r}`)) || 'home'

function loadSession() {
  try { return JSON.parse(sessionStorage.getItem('account') || 'null') } catch { return null }
}

function App() {
  const [route, setRoute] = useState(routeOf(window.location.pathname))
  const [session, setSession] = useState(loadSession)
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => {
    const onPop = () => setRoute(routeOf(window.location.pathname))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const go = (r) => {
    window.history.pushState({}, '', r === 'home' ? '/' : `/${r}`)
    setRoute(r)
    window.scrollTo(0, 0)
  }
  // the one-time API key from sign-up is kept in memory only, never in storage
  const signIn = (d) => {
    const { api_key: apiKey, ...rest } = d
    try { sessionStorage.setItem('account', JSON.stringify(rest)) } catch { /* ignore */ }
    setSession({ ...rest, newApiKey: apiKey })
    go('dashboard')
  }
  const signOut = () => {
    try { sessionStorage.removeItem('account') } catch { /* ignore */ }
    setSession(null)
    go('home')
  }
  // landing-page sections; from any other page this returns home first, then scrolls
  const toSection = (id) => {
    setMenuOpen(false)
    if (route !== 'home') go('home')
    setTimeout(() => document.getElementById(id)?.scrollIntoView(), 60)
  }
  const link = (r, label, cls = '') => (
    <button className={`${cls} ${route === r ? 'active' : ''}`} onClick={() => { setMenuOpen(false); go(r) }}>{label}</button>
  )
  return (
    <>
      <header className="topbar">
        <button className="brand" onClick={() => { setMenuOpen(false); go('home') }}><span className="logo">◆</span> Sanctio</button>
        <button className="menu-toggle" aria-expanded={menuOpen} aria-controls="site-nav" onClick={() => setMenuOpen(!menuOpen)}>
          {menuOpen ? 'Close' : 'Menu'}
        </button>
        <nav id="site-nav" className={menuOpen ? 'open' : ''} aria-label="Main">
          {route !== 'dashboard' && SECTIONS.map(([id, label]) => <button key={id} onClick={() => toSection(id)}>{label}</button>)}
          <span className="nav-gap" />
          {link('docs', 'Docs')}
          {session ? <>{link('dashboard', 'Dashboard')}<button onClick={() => { setMenuOpen(false); signOut() }}>Sign out</button></>
            : <>{link('login', 'Sign in')}{link('signup', 'Get API key', 'cta')}</>}
        </nav>
      </header>
      {route === 'home' && <Landing go={go} toSection={toSection} signedIn={!!session} />}
      {route === 'docs' && <Docs go={go} />}
      <main hidden={route === 'home' || route === 'docs'}>
        {route === 'login' && <Login onDone={signIn} go={go} />}
        {route === 'signup' && <Signup onDone={signIn} go={go} />}
        {route === 'dashboard' && (session ? <Dashboard session={session} onExpired={signOut} /> : <Login onDone={signIn} go={go} />)}
      </main>
    </>
  )
}

createRoot(document.getElementById('root')).render(<App />)

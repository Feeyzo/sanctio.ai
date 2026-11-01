import React from 'react'

// A simple home page: what Sanctio is, its main features, and how a business uses it.
const FEATURES = [
  ['Answers customer questions', 'The agent replies in normal language using the business\'s own help articles.'],
  ['Performs verified actions', 'It can track, cancel or refund, but only after the policy engine checks the request and the customer confirms.'],
  ['Hands off to humans', 'Angry customers, repeated failures and large refunds are passed to a staff member with a summary.'],
  ['Blocks prompt injection', 'Messages like "ignore your rules" are detected and logged, and cannot unlock any action.'],
]

const STEPS = [
  'The business creates an account and gets an API key.',
  'It registers the actions the agent may perform, each pointing to an endpoint on its own server.',
  'It adds help articles so the agent can answer common questions.',
  'It adds the chat widget to its website, or connects WhatsApp.',
]

export default function Home({ go, signedIn }) {
  return (
    <div className="home">
      <section className="home-intro">
        <h1>Sanctio</h1>
        <p className="home-tagline">A secure AI customer service agent API with sentiment-aware human handoff and verified action execution.</p>
        <p>Businesses add Sanctio to their apps so customers can get help any time. The AI suggests what to do, and a fixed set of rules decides whether it is allowed.</p>
        <div className="home-buttons">
          {signedIn
            ? <button onClick={() => go('dashboard')}>Go to dashboard</button>
            : <><button onClick={() => go('signup')}>Get an API key</button><button className="ghost" onClick={() => go('login')}>Sign in</button></>}
          <button className="ghost" onClick={() => go('docs')}>Read the docs</button>
        </div>
      </section>

      <section>
        <h2>Main features</h2>
        <div className="home-grid">
          {FEATURES.map(([title, text]) => (
            <div className="card" key={title}><h3>{title}</h3><p className="muted">{text}</p></div>
          ))}
        </div>
      </section>

      <section>
        <h2>How a business uses it</h2>
        <ol className="home-steps">{STEPS.map((s) => <li key={s}>{s}</li>)}</ol>
      </section>

      <footer className="home-footer muted small">
        Final year project, Department of Software Engineering, Bayero University Kano.
      </footer>
    </div>
  )
}

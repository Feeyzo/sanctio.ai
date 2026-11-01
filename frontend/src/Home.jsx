import React from 'react'

// Home page: what Sanctio is, how a message is handled, its features and where it can be used.
const FEATURES = [
  ['💬', 'Answers questions', 'Replies in normal language using the business\'s own help articles and live data.'],
  ['✅', 'Verified actions', 'Tracks, cancels or refunds only after the policy engine checks the request and the customer confirms.'],
  ['🙋', 'Human handoff', 'Angry customers, repeated failures and large refunds go to a staff member with a summary.'],
  ['🛡️', 'Prompt-injection protection', 'Messages like "ignore your rules" are detected and logged, and cannot unlock any action.'],
  ['📱', 'Web chat and WhatsApp', 'One pipeline for every channel, so the same rules apply wherever the customer writes.'],
  ['📋', 'Audit log', 'Every request, decision and reason is recorded and visible in the dashboard.'],
]

const FLOW = [
  ['Customer asks', '"Please cancel SHP-1002"'],
  ['AI suggests', 'cancel_shipment for SHP-1002'],
  ['Rules decide', 'Right customer? Allowed? Under the limit?'],
  ['Customer confirms', 'Only then does the business carry it out'],
]

const USES = [
  ['Logistics', 'Track parcels, cancel before pickup, change delivery addresses, refund damaged items.'],
  ['Banking', 'Explain failed transfers, block lost cards, and pass possible fraud straight to a person.'],
  ['E-commerce', 'Order status, returns and refunds, with large amounts always approved by staff.'],
]

function ChatPreview() {
  return (
    <div className="preview card">
      <div className="preview-head">SwiftShip support</div>
      <div className="bubble me">Please cancel SHP-1002</div>
      <div className="check-row">Policy check passed: your shipment, not yet picked up</div>
      <div className="bubble bot">Please confirm: Cancel shipment SHP-1002 (Abuja to Kaduna). Reply YES to confirm.</div>
      <div className="bubble me">yes</div>
      <div className="bubble bot">Done. SHP-1002 has been cancelled.</div>
    </div>
  )
}

export default function Home({ go, signedIn }) {
  return (
    <div className="home">
      <section className="home-hero">
        <div>
          <p className="home-label">Secure AI customer service API</p>
          <h1>An AI support agent that can act, but only within the rules.</h1>
          <p className="home-lead">Sanctio answers customer questions, performs real actions like cancellations and refunds,
            and hands difficult cases to a person. The AI suggests what to do; a fixed set of rules decides whether it is allowed.</p>
          <div className="home-buttons">
            {signedIn
              ? <button onClick={() => go('dashboard')}>Go to dashboard</button>
              : <><button onClick={() => go('signup')}>Get an API key</button><button className="ghost" onClick={() => go('login')}>Sign in</button></>}
            <button className="ghost" onClick={() => go('docs')}>Read the docs</button>
          </div>
        </div>
        <ChatPreview />
      </section>

      <section>
        <h2>How a request is handled</h2>
        <div className="flow-row">
          {FLOW.map(([title, text], i) => (
            <div className="flow-step" key={title}>
              <span className="flow-num">{i + 1}</span>
              <strong>{title}</strong>
              <p className="muted small">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2>Features</h2>
        <div className="home-grid">
          {FEATURES.map(([icon, title, text]) => (
            <div className="card feature" key={title}>
              <span className="feature-icon" aria-hidden="true">{icon}</span>
              <h3>{title}</h3>
              <p className="muted">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2>Where it can be used</h2>
        <div className="home-grid three">
          {USES.map(([title, text]) => <div className="card" key={title}><h3>{title}</h3><p className="muted">{text}</p></div>)}
        </div>
      </section>

      <section className="home-cta card">
        <div>
          <h2>Add Sanctio to your app</h2>
          <p className="muted">Create an account, register your actions, and add the chat widget or connect WhatsApp.</p>
        </div>
        <button onClick={() => go(signedIn ? 'dashboard' : 'signup')}>{signedIn ? 'Open dashboard' : 'Get started'}</button>
      </section>

      <footer className="home-footer muted small">
        <span>Sanctio · Final year project, Department of Software Engineering, Bayero University Kano.</span>
        <span>Built with FastAPI, React, PostgreSQL and the WhatsApp Cloud API.</span>
      </footer>
    </div>
  )
}

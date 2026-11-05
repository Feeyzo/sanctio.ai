import React from 'react'

// Home page: what Sanctio is, how a request is handled, how it compares with a typical chatbot,
// its features, how to integrate it, and where it can be used. Static: no animations.

// Simple line icons (24x24, stroke only)
const ICONS = {
  chat: 'M4 5h16v10H8l-4 4z',
  check: 'M5 12l4 4 10-10',
  person: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c0-4 4-6 8-6s8 2 8 6',
  shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',
  phone: 'M8 3h8v18H8zM11 18h2',
  list: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01',
  lock: 'M6 11h12v10H6zM9 11V7a3 3 0 0 1 6 0v4',
  box: 'M3 7l9-4 9 4v10l-9 4-9-4zM3 7l9 4 9-4M12 11v10',
  bank: 'M3 10l9-6 9 6M5 10v8M10 10v8M14 10v8M19 10v8M3 20h18',
  cart: 'M3 4h3l2 11h11l2-8H7M9 20h.01M18 20h.01',
}
const Icon = ({ name }) => (
  <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
    <path d={ICONS[name]} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const STATS = [
  ['100%', 'of actions checked by the policy engine'],
  ['123', 'automated tests, including attack scenarios'],
  ['2', 'channels: web chat and WhatsApp'],
  ['3', 'answer engines: Groq, Gemini, rule-based fallback'],
]

const FLOW = [
  ['chat', 'Customer asks', '"Please cancel SHP-1002"'],
  ['list', 'AI suggests', 'cancel_shipment for SHP-1002'],
  ['shield', 'Rules decide', 'Right customer? Allowed action? Under the limit? Business confirms in a dry run.'],
  ['check', 'Customer confirms', 'Nothing changes until the customer says yes'],
  ['person', 'Human if needed', 'Anger, refunds over the limit or repeated failures go to staff'],
]

const COMPARE = [
  ['Performs real actions (cancel, refund, change address)', 'Rarely', 'Yes, through the business’s own API'],
  ['Who decides if an action is allowed', 'The AI model', 'Fixed rules outside the AI'],
  ['Customer identity', 'Often taken from the chat', 'Only from the verified login session'],
  ['Prompt-injection attack', 'May follow the attacker', 'Logged; data-changing actions refused'],
  ['Angry or upset customer', 'Keeps replying', 'Handed to a person with a summary'],
  ['Large refunds', 'No control', 'Held for staff approval'],
  ['Record of what happened', 'Chat history only', 'Audit log of every request and decision'],
]

const FEATURES = [
  ['chat', 'Understands customers', 'Plain-language requests and questions, answered from live data and the business’s help articles.'],
  ['shield', 'Verified actions', 'Every action passes the policy engine and a dry run before the customer is asked to confirm.'],
  ['person', 'Sentiment-aware handoff', 'Strong anger, repeated failures and requests for a human go to a support agent with a summary.'],
  ['lock', 'Attack resistant', 'Injection attempts are detected and logged; identity never comes from the conversation.'],
  ['phone', 'Web chat and WhatsApp', 'One pipeline for every channel, so the same rules apply wherever the customer writes.'],
  ['list', 'Dashboard and audit log', 'Escalations, approvals, conversations, security events and resolution statistics.'],
]

const USES = [
  ['box', 'Logistics', 'Track parcels, cancel before pickup, change delivery addresses and handle refunds for damaged items.'],
  ['bank', 'Banking', 'Explain failed transfers, block lost cards and send possible fraud straight to a person.'],
  ['cart', 'E-commerce', 'Order status, returns and refunds, with large amounts always approved by staff.'],
]

function ProductPreview() {
  return (
    <div className="mock" aria-label="Example conversation">
      <div className="mock-bar"><span /><span /><span /><em>swiftship.ng/account</em></div>
      <div className="mock-body">
        <div className="mock-head"><strong>SwiftShip support</strong><small>Signed in as Amina Yusuf</small></div>
        <div className="bubble me">Please cancel SHP-1002</div>
        <div className="checks">
          <div className="checks-title"><Icon name="shield" /> Policy engine</div>
          <div><Icon name="check" /> Verified session: Amina (C-1001)</div>
          <div><Icon name="check" /> Action registered: cancel_shipment</div>
          <div><Icon name="check" /> Business dry run: not yet picked up</div>
        </div>
        <div className="bubble bot">Please confirm: cancel shipment SHP-1002 (Abuja to Kaduna)? Reply YES to confirm.</div>
        <div className="bubble me">yes</div>
        <div className="bubble bot">Done. SHP-1002 has been cancelled.</div>
      </div>
      <div className="mock-note"><Icon name="person" /><div><strong>Handoff ready</strong><br />Angry customers go to a person with a summary.</div></div>
    </div>
  )
}

export default function Home({ go, signedIn }) {
  const start = () => go(signedIn ? 'dashboard' : 'signup')
  return (
    <div className="home">
      <section className="hero">
        <div className="hero-text">
          <span className="pill">Secure AI customer service API</span>
          <h1>An AI support agent that can act, but only within the rules.</h1>
          <p className="home-lead">Sanctio answers customer questions, performs real actions like cancellations and refunds,
            and hands difficult cases to a person. The AI suggests what to do; a fixed set of rules decides whether it is allowed.</p>
          <div className="home-buttons">
            <button onClick={start}>{signedIn ? 'Go to dashboard' : 'Get an API key'}</button>
            {!signedIn && <button className="ghost" onClick={() => go('login')}>Sign in</button>}
            <button className="ghost" onClick={() => go('docs')}>Read the docs</button>
          </div>
          <ul className="trust">
            <li><Icon name="check" /> Every action verified</li>
            <li><Icon name="check" /> Human handoff built in</li>
            <li><Icon name="check" /> Works offline with the rule-based engine</li>
          </ul>
        </div>
        <ProductPreview />
      </section>

      <section className="stats">
        {STATS.map(([n, label]) => <div key={label}><strong>{n}</strong><span>{label}</span></div>)}
      </section>

      <section>
        <p className="eyebrow">How it works</p>
        <h2>From message to verified action</h2>
        <div className="flow">
          {FLOW.map(([icon, title, text], i) => (
            <div className={'flow-step' + (i === 2 ? ' key' : '')} key={title}>
              <div className="flow-top"><span className="flow-num">{i + 1}</span><Icon name={icon} /></div>
              <strong>{title}</strong>
              <p>{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section>
        <p className="eyebrow">Why it matters</p>
        <h2>A typical AI chatbot compared with Sanctio</h2>
        <div className="compare card">
          <table>
            <thead><tr><th /><th>Typical AI chatbot</th><th>Sanctio</th></tr></thead>
            <tbody>{COMPARE.map(([row, other, ours]) => (
              <tr key={row}><td>{row}</td><td className="muted">{other}</td><td><Icon name="check" /> {ours}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </section>

      <section>
        <p className="eyebrow">Features</p>
        <h2>Everything a support team needs, with safety built in</h2>
        <div className="home-grid">
          {FEATURES.map(([icon, title, text]) => (
            <div className="card feature" key={title}>
              <span className="feature-icon"><Icon name={icon} /></span>
              <h3>{title}</h3>
              <p className="muted">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="integrate">
        <div>
          <p className="eyebrow">Integration</p>
          <h2>Connect your app in three steps</h2>
          <ol className="steps">
            <li><strong>Keep your API key on your server.</strong> It proves which business is calling.</li>
            <li><strong>Open a session when a customer signs in.</strong> Sanctio returns a token for that one customer.</li>
            <li><strong>Add the chat widget</strong> with the token, or connect your WhatsApp number.</li>
          </ol>
          <button className="ghost" onClick={() => go('docs')}>See the full docs</button>
        </div>
        <pre className="code-card"><code>{`// on your server, when a customer signs in
POST /api/v1/sessions
X-API-Key: sk_live_...
{ "customer_id": "C-1001", "customer_name": "Amina" }

// in your web page
<script src="https://<sanctio>/widget.js"></script>
<script>
  Sanctio.init({ sessionToken: "<token from your server>" })
</script>`}</code></pre>
      </section>

      <section>
        <p className="eyebrow">Use cases</p>
        <h2>Where it can be used</h2>
        <div className="home-grid">
          {USES.map(([icon, title, text]) => (
            <div className="card feature" key={title}>
              <span className="feature-icon"><Icon name={icon} /></span>
              <h3>{title}</h3>
              <p className="muted">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="home-cta">
        <div>
          <h2>Add Sanctio to your app</h2>
          <p>Create an account, register your actions, and add the chat widget or connect WhatsApp.</p>
        </div>
        <button onClick={start}>{signedIn ? 'Open dashboard' : 'Get started'}</button>
      </section>

      <footer className="home-footer muted small">
        <span>Sanctio · Final year project, Department of Software Engineering, Bayero University Kano.</span>
        <span>Built with FastAPI, React, PostgreSQL and the WhatsApp Cloud API.</span>
      </footer>
    </div>
  )
}

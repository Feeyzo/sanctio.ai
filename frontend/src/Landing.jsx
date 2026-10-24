import React from 'react'
import HeroFlow from './HeroFlow.jsx'

const CHATBOT = ['Answers from a script', 'Cannot see the customer’s account', 'Ends with “please contact support”']
const SANCTIO = [
  'Understands the complaint and how the customer feels',
  'Looks up live data in your system through the tools you connect',
  'Carries out permitted actions, such as a cancellation or refund',
  'Hands over to a person, with the full context, when it should',
]

const STEPS = [
  ['Receive', 'A signed-in customer writes in from your app. Your backend has already told Sanctio who they are, so identity never comes from the chat.'],
  ['Interpret', 'The agent works out what the customer wants, how confident it is, and how the customer is feeling.'],
  ['Select an action', 'It chooses from the actions you registered, or a troubleshooting guide you wrote. It asks for a missing detail instead of guessing.'],
  ['Call permitted tools', 'A separate security engine checks the request. Only then does Sanctio call your endpoint, as a preview first for anything that changes data.'],
  ['Communicate the result', 'The customer gets a clear answer. If the case is risky, large or heated, a person on your team takes over.'],
]

const CHECKS = [
  ['Allow-list', 'Only actions the business registered and enabled can be requested.'],
  ['Input validation', 'Parameters must match the declared schema exactly: no extra fields, correct types and formats.'],
  ['Injection screening', 'A suspected prompt-injection attempt blocks every data-changing action in that turn and is logged.'],
  ['Verified identity', 'The customer ID comes from the session the business created, never from the conversation.'],
  ['Preview, then confirm', 'Data-changing actions are previewed as a dry run, and the customer must confirm before they run.'],
  ['Human approval', 'Actions over a limit the business sets wait for a person to approve them.'],
]

const STACK = ['FastAPI', 'SQLAlchemy', 'React', 'Vite', 'Google Gemini (optional)', 'HMAC-signed webhooks']

export default function Landing({ go, toSection, signedIn }) {
  const start = () => go(signedIn ? 'dashboard' : 'signup')
  return (
    <div className="landing">
      <section className="hero">
        <div className="hero-grid">
          <div className="hero-copy">
            <p className="eyebrow">AI customer service agents</p>
            <h1>Customer support that doesn’t just answer. <span className="accent">It acts.</span></h1>
            <p className="lead">Sanctio gives your business an AI agent that understands what a customer needs, reasons
              through the fix, and carries out the actions you permit through your own tools and APIs.</p>
            <div className="hero-cta">
              <button className="big" onClick={() => toSection('product')}>Explore Sanctio</button>
              <button className="big ghost-light" onClick={() => toSection('how')}>See how it works</button>
            </div>
            <p className="creed">Understand <i>·</i> Reason <i>·</i> Resolve</p>
          </div>
          <HeroFlow />
        </div>
      </section>

      <section id="product" className="wrap section">
        <p className="eyebrow">Product</p>
        <h2 className="display">Most support bots stop at the answer.<br />Sanctio finishes the job.</h2>
        <div className="compare">
          <div className="compare-col">
            <h3>A typical chatbot</h3>
            <ul>{CHATBOT.map((t) => <li key={t}>{t}</li>)}</ul>
          </div>
          <div className="compare-col strong">
            <h3>A Sanctio agent</h3>
            <ul>{SANCTIO.map((t) => <li key={t}>{t}</li>)}</ul>
          </div>
        </div>
      </section>

      <section id="how" className="wrap section split">
        <div className="split-head">
          <p className="eyebrow">How it works</p>
          <h2 className="display">From a message to a resolved problem.</h2>
          <p className="muted">Five steps happen on every turn. The AI proposes; a rule-based engine decides.</p>
        </div>
        <ol className="timeline">
          {STEPS.map(([title, text], i) => (
            <li key={title}><span className="tick">{String(i + 1).padStart(2, '0')}</span><div><h3>{title}</h3><p>{text}</p></div></li>
          ))}
        </ol>
      </section>

      <section id="features" className="wrap section">
        <p className="eyebrow">Core capabilities</p>
        <h2 className="display">Built to resolve, not to deflect.</h2>
        <div className="bento">
          <article className="b-wide">
            <h3>Understands the request</h3>
            <p>Reads intent and sentiment from plain language, and knows when it is not sure.</p>
            <div className="demo" aria-hidden="true">
              <q>My parcel was meant to arrive on Friday and nobody is telling me anything.</q>
              <div className="tags"><span>intent · late_delivery</span><span>sentiment · negative</span><span>needs · tracking number</span></div>
            </div>
          </article>
          <article className="b-wide">
            <h3>Solves problems in steps</h3>
            <p>Looks up the facts first, then applies the guide that fits, and asks for what is missing.</p>
            <ol className="demo mini-steps" aria-hidden="true">
              <li>Look up the shipment</li><li>Match the “late delivery” guide</li><li>Explain what happens next</li>
            </ol>
          </article>
          <article>
            <h3>Acts through your APIs</h3>
            <p>Each action is one signed request to an endpoint you control. Your data stays in your system.</p>
            <pre className="demo" aria-hidden="true">{'POST /your-endpoint\n{ "action": "cancel_order",\n  "customer_id": "C-1001",\n  "dry_run": true }'}</pre>
          </article>
          <article>
            <h3>Knows when to step back</h3>
            <p>Frustration, repeated failure or a request for a person passes the case to your team with a summary.</p>
            <div className="demo meter" aria-hidden="true"><span /><small>sentiment falling · handed to a person</small></div>
          </article>
          <article>
            <h3>Handles requests with care</h3>
            <p>Every action is proposed, checked, confirmed and logged, in that order.</p>
            <div className="demo chain" aria-hidden="true"><span>proposed</span><span>checked</span><span>confirmed</span><span>executed</span></div>
          </article>
        </div>
      </section>

      <section id="technology" className="tech">
        <div className="wrap tech-grid">
          <div>
            <p className="eyebrow">Security and reliability</p>
            <h2 className="display">The model can ask.<br />It cannot decide.</h2>
            <p>An AI that can change real data needs limits that do not depend on the AI behaving well. In Sanctio the
              language model only proposes an action. A separate, deterministic engine decides whether it runs, and
              every decision is kept in an audit log.</p>
            <p className="fine">Sanctio is a final-year software engineering project. It has not been independently
              audited or certified, and it is not presented as production-ready.</p>
            <ul className="stack" aria-label="Built with">{STACK.map((s) => <li key={s}>{s}</li>)}</ul>
          </div>
          <ol className="checks">
            {CHECKS.map(([title, text], i) => (
              <li key={title}><span>{String(i + 1).padStart(2, '0')}</span><div><h3>{title}</h3><p>{text}</p></div></li>
            ))}
          </ol>
        </div>
      </section>

      <section className="wrap closing">
        <h2 className="display">See it handle a real request.</h2>
        <p className="muted">Create an account, connect one endpoint, and try the agent in the dashboard playground.</p>
        <div className="hero-cta">
          <button className="big" onClick={start}>{signedIn ? 'Open dashboard' : 'Get your API key'}</button>
          <button className="big ghost" onClick={() => go('docs')}>Read the docs</button>
        </div>
      </section>
      <footer className="wrap">
        <span>◆ Sanctio</span>
        <span className="muted small">A secure AI customer service agent API · final-year software engineering project</span>
      </footer>
    </div>
  )
}

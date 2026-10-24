import React, { useEffect, useState } from 'react'

/* Illustrative walk-through of one request: customer -> agent -> permitted tools -> resolution.
   It is a product visualisation, not live data. Steps: 0 request, 1 plan, 2-4 tools, 5 resolved. */
const TOOLS = [
  ['Verify identity', 'verified session'],
  ['Look up account', 'customer record'],
  ['Send reset link', 'password-reset API'],
]
const STATUS = [
  'Reading the request',
  'Intent: account recovery',
  'Verifying identity',
  'Looking up the account',
  'Requesting a reset link',
  'Resolved with 3 permitted actions',
]
const DURATION = [1700, 1700, 1200, 1200, 1200, 4600]
const LAST = STATUS.length - 1

// Connectors are drawn in a 100 x 40 box and stretched to the row width, so the
// lines stay attached to the cards at every screen size.
const TO_AGENT = ['M40 0 C40 24 50 16 50 40']
const BRANCH = ['M50 0 C50 22 16.5 18 16.5 40', 'M50 0 L50 40', 'M50 0 C50 22 83.5 18 83.5 40']
const MERGE = ['M16.5 0 C16.5 22 50 18 50 40', 'M50 0 L50 40', 'M83.5 0 C83.5 22 50 18 50 40']

function Wire({ paths, states }) {
  return (
    <svg className="wire" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
      {paths.map((d, i) => (
        <g key={d} className={states[i]}>
          <path className="wire-base" d={d} />
          <path className="wire-pulse" d={d} />
        </g>
      ))}
    </svg>
  )
}

const phase = (step, at) => (step < at ? 'idle' : step === at ? 'live' : 'done')

export default function HeroFlow() {
  const [step, setStep] = useState(0)
  useEffect(() => {
    // with reduced motion, show the finished state and do not cycle
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setStep(LAST); return }
    const t = setTimeout(() => setStep((s) => (s === LAST ? 0 : s + 1)), DURATION[step])
    return () => clearTimeout(t)
  }, [step])

  const resolved = step === LAST
  return (
    <figure className="flow">
      <div className="flow-top" aria-hidden="true">
        <span>Example flow · account recovery</span>
        <span className="flow-dots">{STATUS.map((s, i) => <i key={s} className={i <= step ? 'on' : ''} />)}</span>
      </div>

      <div aria-hidden="true">
        <div className={`flow-card flow-request ${step === 0 ? 'hot' : ''}`}>
          <div className="flow-label"><span className="avatar">AY</span>Customer<em>signed in</em></div>
          <p>I can’t get into my account. The reset email never arrives.</p>
        </div>

        <Wire paths={TO_AGENT} states={[phase(step, 0)]} />

        <div className={`flow-agent ${step > 0 && !resolved ? 'thinking' : ''}`}>
          <div className="orb">
            <svg viewBox="0 0 24 24" width="26" height="26"><path d="M12 2 22 12 12 22 2 12Z" fill="currentColor" /></svg>
          </div>
          <strong>Sanctio agent</strong>
          <span className="flow-status" key={step}>{STATUS[step]}</span>
          <span className={`gate ${step >= 2 ? 'passed' : ''}`}>
            <svg viewBox="0 0 16 16" width="12" height="12"><path d="M8 1.5 13.5 3.6v4.2c0 3.2-2.2 5.6-5.5 6.7C4.7 13.4 2.5 11 2.5 7.8V3.6Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" /></svg>
            Security engine {step >= 2 ? 'checks each action' : 'standing by'}
          </span>
        </div>

        <Wire paths={BRANCH} states={TOOLS.map((_, i) => phase(step, i + 2))} />

        <div className="flow-tools">
          {TOOLS.map(([name, detail], i) => (
            <div key={name} className={`flow-card tool ${phase(step, i + 2)}`}>
              <span className="tool-state" />
              <b>{name}</b>
              <small>{detail}</small>
            </div>
          ))}
        </div>

        <Wire paths={MERGE} states={TOOLS.map(() => (resolved ? 'done' : 'idle'))} />

        <div className={`flow-card flow-result ${resolved ? 'resolved' : ''}`}>
          <div className="flow-label">Resolution<em className="result-pill">{resolved ? 'Resolved' : 'In progress'}</em></div>
          <p>Identity confirmed. A new reset link is on its way to the email on file.</p>
        </div>
      </div>

      <figcaption>
        <span className="sr-only">A customer who cannot sign in writes to the Sanctio agent. The agent checks each step
          with the security engine, verifies identity, looks up the account, requests a password reset, and reports
          the result. </span>
        Illustrative example, not live data
      </figcaption>
    </figure>
  )
}

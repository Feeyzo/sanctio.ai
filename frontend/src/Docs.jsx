import React from 'react'

const BASE = window.location.origin

const SECTIONS = [
  ['overview', 'Overview'], ['quickstart', 'Quickstart'], ['auth', 'Authentication'], ['sessions', 'Create a session'],
  ['chat', 'Send a message'], ['conversations', 'Read a conversation'], ['actions', 'Connect your app (actions)'],
  ['signature', 'Verify the signature'], ['knowledge', 'Knowledge base'], ['security', 'Security engine'],
  ['handoff', 'Human handoff'], ['widget', 'Chat widget'], ['errors', 'Errors'],
]

const Code = ({ children }) => <pre className="code">{children}</pre>

function Table({ head, rows }) {
  return (
    <div className="table-wrap">
      <table className="plain">
        <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((r) => <tr key={r[0]}>{r.map((c, i) => <td key={i}>{i === 0 ? <code>{c}</code> : c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

export default function Docs({ go }) {
  return (
    <div className="docs wrap">
      <aside>
        <strong>Documentation</strong>
        {SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}
        <a href="/api/docs" target="_blank" rel="noreferrer">API reference (OpenAPI) ↗</a>
      </aside>
      <article>
        <h1>Sanctio API documentation</h1>
        <p className="lead">Add an AI customer service agent to your app that can answer questions, troubleshoot, and
          perform real actions in your system, with every action checked by a security engine.</p>

        <h2 id="overview">Overview</h2>
        <p>There are three parts to an integration:</p>
        <ol>
          <li><strong>Sessions.</strong> When one of your customers opens support, your backend asks Sanctio for a
            session token for that customer. This is how the agent knows who it is talking to.</li>
          <li><strong>Chat.</strong> Your app sends the customer's messages with that token and shows the replies. You
            can use the ready-made widget or build your own UI.</li>
          <li><strong>Actions.</strong> You tell Sanctio what the agent may do (for example <code>track_shipment</code>
            or <code>cancel_order</code>) and give it one endpoint on your backend to call. Sanctio decides
            <em> whether</em> an action may run; your backend does the actual work.</li>
        </ol>
        <p>Base URL: <code>{BASE}</code></p>

        <h2 id="quickstart">Quickstart</h2>
        <ol>
          <li><a onClick={() => go('signup')}>Create an account</a> and copy your API key. It is shown once.</li>
          <li>In the dashboard, open <strong>Actions</strong> and add the things your agent may do, each pointing at
            an endpoint on your backend. Add your troubleshooting guides under <strong>Knowledge</strong>.</li>
          <li>Build that endpoint (<a href="#actions">see below</a>) and use the <strong>Test</strong> button to check it.</li>
          <li>Try the agent in the dashboard <strong>Playground</strong>.</li>
          <li>From your backend, create a session for the signed-in customer, then load the widget with the token.</li>
        </ol>

        <h2 id="auth">Authentication</h2>
        <Table head={['Credential', 'Where it lives', 'Used for']} rows={[
          ['X-API-Key: sk_live_…', 'Your server only. Never ship it in a web page or mobile app.', 'Creating customer sessions'],
          ['Authorization: Bearer <session token>', 'Your customer’s browser or app. Expires after 60 minutes.', 'Chatting as that one customer'],
          ['Webhook secret whsec_…', 'Your server only.', 'Checking that action requests really come from Sanctio'],
        ]} />

        <h2 id="sessions">Create a session</h2>
        <p>Call this from your backend after you have authenticated the customer yourself. Use your own stable ID for
          the customer: it is the ID Sanctio sends back to you with every action.</p>
        <Code>{`curl -X POST ${BASE}/api/v1/sessions \\
  -H "X-API-Key: sk_live_..." \\
  -H "Content-Type: application/json" \\
  -d '{"customer_id": "C-1001", "customer_name": "Amina Yusuf", "customer_email": "amina@example.com"}'

{ "session_token": "p3Zk...", "customer_id": "C-1001" }`}</Code>
        <Table head={['Field', 'Notes']} rows={[
          ['customer_id', 'Required. Your ID for this customer, up to 64 characters.'],
          ['customer_name', 'Optional. Shown to your support team.'],
          ['customer_email', 'Optional. Shown to your support team.'],
          ['customer_phone', 'Optional. A mobile number you have verified, in international format (+2348030000001). Links the customer\'s WhatsApp messages to this account; only send it once you have confirmed the customer owns the number.'],
        ]} />
        <p>To end a session early (for example on logout): <code>DELETE /api/v1/sessions</code> with the session token.</p>

        <h2 id="chat">Send a message</h2>
        <Code>{`curl -X POST ${BASE}/api/v1/chat \\
  -H "Authorization: Bearer <session token>" \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Where is my shipment SHP-1001?", "conversation_id": null}'

{
  "conversation_id": 12,
  "reply": "Shipment SHP-1001 (Lagos to Kano) is in transit. Expected delivery: 2026-10-14.",
  "status": "active",
  "intent": "track_shipment",
  "confidence": 0.9,
  "sentiment": 0.0,
  "sentiment_label": "neutral",
  "action": { "name": "track_shipment", "decision": "executed", "reason": "Read-only action permitted" },
  "handoff": null,
  "engine": "gemini"
}`}</Code>
        <p>Send <code>conversation_id: null</code> for the first message, then pass back the ID you receive to continue
          the same conversation. Messages can be up to 1,000 characters.</p>
        <Table head={['Response field', 'Meaning']} rows={[
          ['reply', 'What to show the customer.'],
          ['status', 'active, handed_off (a person has taken over) or resolved.'],
          ['action.decision', 'executed, awaiting_confirmation, pending_approval, denied, failed, declined_by_customer.'],
          ['handoff', 'Set when the conversation was passed to your team: { id, reasons, priority }.'],
          ['sentiment', 'From -1 (very negative) to +1 (very positive).'],
        ]} />

        <h2 id="conversations">Read a conversation</h2>
        <p>Once a conversation is <code>handed_off</code>, your team replies from the dashboard. Poll this endpoint to
          show those replies (the widget does this for you). <code>sender</code> is <code>customer</code>,
          <code> agent</code> or <code>human</code>.</p>
        <Code>{`GET ${BASE}/api/v1/conversations/12
Authorization: Bearer <session token>

{ "id": 12, "status": "handed_off",
  "messages": [ { "sender": "customer", "content": "...", "at": "2026-10-12T10:31:00" } ] }`}</Code>

        <h2 id="actions">Connect your app (actions)</h2>
        <p>An action is something the agent may do in your system. You define each one in the dashboard:</p>
        <Table head={['Setting', 'Meaning']} rows={[
          ['name', 'Lowercase with underscores, e.g. cancel_shipment. Use a clear verb: the agent matches it to what customers ask.'],
          ['description', 'One sentence saying what it does and when it applies. The agent reads this.'],
          ['parameters', 'What the agent must collect, e.g. tracking_number. Add a pattern such as SHP-\\d{4,8} to enforce the format.'],
          ['endpoint URL', 'Where Sanctio sends the request. All your actions can share one URL.'],
          ['changes data', 'Turn on for anything that modifies your system. These get a dry run and customer confirmation.'],
          ['approval', 'never, always, or when the amount is over a limit you set. Approval requests go to your team.'],
        ]} />
        <p>You never declare a customer ID parameter. Sanctio adds the verified <code>customer_id</code> itself.</p>

        <h3>The request Sanctio sends you</h3>
        <Code>{`POST https://your-app.example.com/sanctio
Content-Type: application/json
X-Sanctio-Timestamp: 1791800000
X-Sanctio-Signature: sha256=3f1a...

{
  "action": "cancel_shipment",
  "customer_id": "C-1001",
  "params": { "tracking_number": "SHP-1002" },
  "dry_run": true,
  "conversation_id": 12,
  "request_id": "0b9e2c..."
}`}</Code>

        <h3>What to send back</h3>
        <Code>{`// It can be done (or, for a dry run, could be done):
{ "ok": true,
  "dry_run": true,
  "summary": "Cancel shipment SHP-1002 (Abuja to Kaduna)",
  "amount": 3000,
  "data": { "tracking_number": "SHP-1002", "status": "pending_pickup" } }

// It cannot be done. "error" is shown to the customer, so keep it friendly:
{ "ok": false, "error": "Shipment is already in transit and cannot be cancelled" }`}</Code>
        <Table head={['Field', 'Notes']} rows={[
          ['ok', 'true or false. Use false for business refusals such as "not found" or "too late to cancel".'],
          ['dry_run', 'Echo back the value you received. Required for data-changing actions.'],
          ['summary', 'A short description. For a dry run it is used in the confirmation question to the customer.'],
          ['amount', 'The money involved, as a number. Needed if the action has an approval limit.'],
          ['data', 'An object with any details. The agent uses it to answer and troubleshoot.'],
        ]} />

        <h3>Three rules for your endpoint</h3>
        <ol>
          <li><strong>Scope everything to <code>customer_id</code>.</strong> Only look up records belonging to that
            customer. Return the same error for "does not exist" and "belongs to someone else".</li>
          <li><strong>Change nothing when <code>dry_run</code> is true.</strong> Check that the action is possible,
            describe it in <code>summary</code>, and echo <code>"dry_run": true</code>. Sanctio calls again with
            <code> dry_run: false</code> once the customer (and, if needed, your team) has agreed. If your endpoint
            does not echo the flag, Sanctio refuses to use the action.</li>
          <li><strong>Verify the signature</strong> before trusting the request.</li>
        </ol>

        <h3>Example endpoint (Node.js / Express)</h3>
        <Code>{`const crypto = require('crypto')
const express = require('express')
const app = express()

// keep the raw body: the signature is computed over the exact bytes
app.post('/sanctio', express.raw({ type: 'application/json' }), async (req, res) => {
  const timestamp = req.get('X-Sanctio-Timestamp')
  const expected = 'sha256=' + crypto.createHmac('sha256', process.env.SANCTIO_WEBHOOK_SECRET)
    .update(timestamp + '.').update(req.body).digest('hex')
  const given = req.get('X-Sanctio-Signature') || ''
  const fresh = Math.abs(Date.now() / 1000 - Number(timestamp)) < 300
  if (!fresh || given.length !== expected.length ||
      !crypto.timingSafeEqual(Buffer.from(given), Buffer.from(expected))) {
    return res.status(401).json({ ok: false, error: 'Bad signature' })
  }

  const { action, customer_id, params, dry_run } = JSON.parse(req.body)

  if (action === 'track_shipment') {
    const s = await db.shipments.findOne({ ref: params.tracking_number, customerId: customer_id })
    if (!s) return res.json({ ok: false, error: 'Shipment not found on this account' })
    return res.json({ ok: true, summary: \`Shipment \${s.ref} is \${s.status}\`, data: s })
  }

  if (action === 'cancel_shipment') {
    const s = await db.shipments.findOne({ ref: params.tracking_number, customerId: customer_id })
    if (!s) return res.json({ ok: false, error: 'Shipment not found on this account' })
    if (s.status !== 'pending_pickup') return res.json({ ok: false, error: 'It has already been picked up' })
    if (!dry_run) await db.shipments.update(s.id, { status: 'cancelled' })
    return res.json({ ok: true, dry_run, summary: \`Cancel shipment \${s.ref}\`, amount: s.fee })
  }

  res.json({ ok: false, error: 'Unknown action' })
})`}</Code>

        <h2 id="signature">Verify the signature</h2>
        <p>The signature is an HMAC-SHA256 of <code>timestamp + "." + raw request body</code>, keyed with your webhook
          secret (dashboard → Setup). Reject requests whose timestamp is more than five minutes old.</p>
        <Code>{`# Python (FastAPI / Flask): body is the raw request bytes
import hashlib, hmac, time

def is_from_sanctio(secret: str, timestamp: str, signature: str, body: bytes) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature) and abs(time.time() - int(timestamp)) < 300`}</Code>

        <h2 id="knowledge">Knowledge base</h2>
        <p>Add your troubleshooting guides, FAQs and policies under <strong>Knowledge</strong> in the dashboard. Write
          each one as short numbered steps with a clear title, for example "Late delivery" or "Payment deducted but no
          booking". The agent uses them together with what it looks up in your system: for "my package SHP-1001 is
          late" it first checks the shipment, then gives the steps that fit. It only states facts from your actions and
          your articles.</p>

        <h2 id="security">Security engine</h2>
        <p>The AI can only <em>propose</em> an action. A separate, rule-based engine decides, in this order:</p>
        <ol>
          <li>The action must be one you registered and enabled.</li>
          <li>Parameters must match your schema exactly: no extra fields, correct types, your patterns.</li>
          <li>If the message looks like a prompt-injection attempt, every data-changing action is blocked and the event is logged.</li>
          <li>Each session has a limit on data-changing actions.</li>
          <li>Your endpoint is asked, as a dry run and with the verified customer ID, whether the action is possible.</li>
          <li>If the action needs approval, or the amount your system reports is over your limit, it goes to a person.</li>
          <li>Otherwise the customer must confirm with a clear yes before it runs. It is checked again at that point.</li>
        </ol>
        <p>Every proposal and decision is kept in the audit log on each conversation.</p>

        <h2 id="handoff">Human handoff</h2>
        <p>A conversation is passed to your team when the customer asks for a person, is strongly or repeatedly
          negative, the agent has failed to help twice, an action needs approval, or injection attempts repeat. The
          agent stops acting, the response has <code>status: "handed_off"</code>, and your team sees the conversation in
          the dashboard with a summary, the reasons and the action history. Their replies appear in the conversation
          with <code>sender: "human"</code>.</p>

        <h2 id="widget">Chat widget</h2>
        <p>The quickest way to add chat. Create the session on your server, then put the token in the page:</p>
        <Code>{`<script src="${BASE}/widget.js"></script>
<script>
  Sanctio.init({
    sessionToken: '{{ token from POST /api/v1/sessions }}',
    title: 'SwiftShip Support',      // optional
    color: '#0a0a0a',                // optional
    greeting: 'Hi! How can I help?', // optional
  })
</script>`}</Code>

        <h2 id="errors">Errors</h2>
        <p>Errors are JSON: <code>{'{ "detail": "..." }'}</code>.</p>
        <Table head={['Status', 'Meaning']} rows={[
          ['401', 'Missing or wrong API key, or the session token is invalid, expired or revoked.'],
          ['404', 'The conversation does not exist or belongs to another customer.'],
          ['422', 'The request is malformed, or the message is empty or too long.'],
        ]} />
        <p className="muted">An action that is refused is not an HTTP error: the chat call succeeds and
          <code> action.decision</code> tells you what happened.</p>
      </article>
    </div>
  )
}

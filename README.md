# sanctio.ai
A secure customer service agent API that businesses can plug into their apps.

It understands complaints, troubleshoots, and performs real actions like order cancellations and refunds, but only
after a security engine verifies each one. It detects frustrated customers and hands complex or risky cases to humans
with full context.

## How it fits together
- **Website** (`frontend/`): landing page, API documentation, sign-up, and the business dashboard (API key, actions,
  knowledge base, playground, handoffs, approvals, conversations, security log).
- **API** (`backend/`): the integration API (`/api/v1/...`), the dashboard API (`/api/admin/...`) and the chat widget
  (`/widget.js`).
- **Your app**: a business registers *actions* that point at an endpoint on its own backend. The agent proposes an
  action, the policy engine (`backend/app/policy.py`) decides, and only then does Sanctio call that endpoint with the
  customer ID from the verified session.

## Run it locally
```powershell
# terminal 1 - API on http://localhost:8000
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# terminal 2 - website on http://localhost:5173
cd frontend
npm install
npm run dev
```
Open http://localhost:5173, create an account, and follow the Docs page. The interactive API reference is at
http://localhost:8000/api/docs.

## Configuration (environment variables)
| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | empty | Google Gemini key. Without it the agent uses the built-in rule-based engine. Check it in the dashboard: **Setup → AI model → Test AI**. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Model used when a key is set. If Google retires it, the error shown under **Setup → Test AI** names the replacement; set it here. |
| `GROQ_API_KEY` | empty | Free key from [console.groq.com](https://console.groq.com/keys). Groq (Llama) answers when Gemini is busy or failing, or on its own if no Gemini key is set. |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model. |
| `GEMINI_FALLBACK_MODEL` | empty | Optional second model, used when the main one is still overloaded after two retries (e.g. a *lite* model listed in AI Studio). |
| `APP_SECRET` | development value | Signs dashboard sign-in tokens. **Set a long random value in production.** |
| `ALLOW_PRIVATE_WEBHOOK_URLS` | `1` | Allows `http://localhost` action URLs for development. **Set to `0` in production.** |
| `DATABASE_URL` | SQLite file | Any SQLAlchemy URL. |
| `CORS_ORIGINS` | `*` | Comma-separated origins allowed to call the API from a browser. |
| `WHATSAPP_ACCESS_TOKEN` | empty | Meta access token used to send WhatsApp messages (a system-user token in production). |
| `WHATSAPP_PHONE_NUMBER_ID` | empty | Default sending number (Meta's *Phone number ID*, not the phone number itself). |
| `WHATSAPP_VERIFY_TOKEN` | empty | Any random string; enter the same value in the Meta app's webhook settings. |
| `WHATSAPP_APP_SECRET` | empty | Meta app secret. Verifies `X-Hub-Signature-256` on every webhook. Empty = all webhooks rejected. |
| `WHATSAPP_API_VERSION` | `v23.0` | Graph API version. |

The app reads real environment variables; it does not load a `.env` file by itself.

## Tests
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```
The tests run the whole flow against an in-process fake logistics backend (`backend/tests/fake_business.py`), which
is also a compact reference for how a business's action endpoint should behave.

## WhatsApp channel
Customers can also chat with the agent on WhatsApp, through Meta's official **WhatsApp Cloud API**
(`backend/app/channels/`). WhatsApp is only another entry point: every message runs through the same
`agent.handle_message` pipeline, policy engine and handoff engine as the web chat.

- **Webhook:** `GET /webhooks/whatsapp` answers Meta's verification handshake. `POST /webhooks/whatsapp` checks the
  `X-Hub-Signature-256` HMAC over the raw body (401 if it is wrong), answers 200 at once and processes the
  messages in the background. Each WhatsApp message id is handled once, even when Meta retries.
- **Which business:** each business connects its number (Meta's *phone number ID*):
  `POST /api/admin/whatsapp/numbers {"phone_number_id": "...", "display_phone": "+1 555 ..."}`.
- **Which customer:** the business links a number to a customer by passing `customer_phone` (E.164, for example
  `+2348030000001`) to `POST /api/v1/sessions`. Only do this once you have verified the customer owns the number.
  Messages from a linked number get an internal session for that customer. An unlinked number gets no
  session, so it can ask general questions but the policy engine refuses every order or account action, and the
  reply explains how to link the number.
- **Confirmations:** actions that need confirmation are sent with **Confirm** / **Cancel** buttons. A tap counts
  only for that customer's latest pending action. Old, forged or other customers' buttons change nothing and
  are logged as security events.
- **Human replies:** a team member's reply to a WhatsApp conversation is sent on WhatsApp. More than 24 hours after
  the customer's last message, WhatsApp only allows template messages, so the dashboard shows
  "24-hour window closed — a template message is required" and nothing is sent.
- Voice notes, images and stickers get a polite request to type the question instead.

**Upgrading an existing database:** this adds a table and columns, and makes `conversations.customer_id` nullable.
`create_all` does not change existing tables. In development, delete `backend/agent.db` and it is recreated on
start. For PostgreSQL:
```sql
ALTER TABLE customers ADD COLUMN phone VARCHAR(20) NOT NULL DEFAULT '';
CREATE INDEX ix_customers_phone ON customers (phone);
ALTER TABLE sessions ADD COLUMN channel VARCHAR(16) NOT NULL DEFAULT 'web';
ALTER TABLE conversations ALTER COLUMN customer_id DROP NOT NULL;
ALTER TABLE conversations ADD COLUMN channel VARCHAR(16) NOT NULL DEFAULT 'web';
ALTER TABLE conversations ADD COLUMN contact VARCHAR(20) NOT NULL DEFAULT '';
ALTER TABLE conversations ADD COLUMN wa_phone_number_id VARCHAR(32) NOT NULL DEFAULT '';
-- whatsapp_numbers and whatsapp_inbound are new tables: create_all creates them on start
```

### Try it locally with Meta's test number and ngrok
1. In [Meta for Developers](https://developers.facebook.com/apps), create an app of type **Business** and add the
   **WhatsApp** product. Under *WhatsApp → API Setup* you get a test number, its **Phone number ID**, and a
   temporary access token (valid for 24 hours). Add your own phone as an allowed recipient and verify it.
   The app secret is under *App settings → Basic*.
2. Start the API with the WhatsApp settings:
   ```powershell
   cd backend
   $env:WHATSAPP_ACCESS_TOKEN = "EAAG..."          # temporary token from API Setup
   $env:WHATSAPP_PHONE_NUMBER_ID = "1234567890"    # Phone number ID from API Setup
   $env:WHATSAPP_VERIFY_TOKEN = "any-long-random-string"
   $env:WHATSAPP_APP_SECRET = "app-secret-from-basic-settings"
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
   ```
3. Expose it: `ngrok http 8000`, and copy the `https://....ngrok-free.app` URL.
4. In *WhatsApp → Configuration → Webhook*, set the callback URL to `https://<ngrok-host>/webhooks/whatsapp`
   and the verify token to the same value as `WHATSAPP_VERIFY_TOKEN`, then click **Verify and save**. Subscribe to
   the **messages** field.
5. Connect the number to your business and link yourself as a customer (use your dashboard sign-in token and API key):
   ```powershell
   $admin = @{ Authorization = "Bearer <token from /api/auth/login>" }
   Invoke-RestMethod -Method Post http://localhost:8000/api/admin/whatsapp/numbers -Headers $admin `
     -ContentType application/json -Body '{"phone_number_id": "1234567890", "display_phone": "test number"}'
   Invoke-RestMethod -Method Post http://localhost:8000/api/v1/sessions -Headers @{ "X-API-Key" = "sk_live_..." } `
     -ContentType application/json -Body '{"customer_id": "C-1001", "customer_name": "Me", "customer_phone": "+234..."}'
   ```
6. Send a WhatsApp message to the test number from your phone. Try a question, an order lookup, a cancellation
   (you get Confirm/Cancel buttons), "I want to speak to a human" (then reply from the dashboard), and a voice note.
   Message it from a phone number you have not linked to see what an unlinked number can do.

The WhatsApp tests (`backend/tests/test_whatsapp.py`) replace the Graph API with an in-process fake, so no network is needed.

## Demo business: SwiftShip
`demo_business/app.py` is a small, separate web app playing a real business that has integrated Sanctio. It has a
customer sign-in (pick a demo customer), a shipments page that refreshes every 3 seconds, the Sanctio chat widget
(using a session its server opened with the API key), and the signed action endpoint Sanctio calls (`POST /sanctio`).

`backend/scripts/seed_demo.py` creates or resets the matching business on Sanctio: actions pointing at SwiftShip,
knowledge-base articles, customers (with linked WhatsApp numbers if given), and the dashboard login. A reset wipes
the demo business's conversations, handoffs and logs, then also resets SwiftShip's shipments.

Run both locally:
```powershell
# terminal 1 - Sanctio (as above), terminal 2 - SwiftShip on http://localhost:8100
cd demo_business
$env:SANCTIO_URL = "http://localhost:8000"; $env:DEMO_API_KEY = "sk_live_local_demo_key"
$env:DEMO_WEBHOOK_SECRET = "whsec_local_demo_secret"; $env:DEMO_RESET_TOKEN = "local-reset"
..\backend\.venv\Scripts\python.exe -m uvicorn app:app --port 8100

# terminal 3 - seed / reset (same DEMO_* values, plus these)
cd backend
$env:DEMO_API_KEY = "sk_live_local_demo_key"; $env:DEMO_WEBHOOK_SECRET = "whsec_local_demo_secret"
$env:DEMO_RESET_TOKEN = "local-reset"; $env:DEMO_BUSINESS_URL = "http://localhost:8100"; $env:DEMO_ADMIN_PASSWORD = "Passw0rd!23"
.\.venv\Scripts\python.exe -m scripts.seed_demo
```
Then open http://localhost:8100 as a customer, and http://localhost:5173 signed in as `demo@swiftship.test`.

## Deploy for a live demo (Render, free)
`render.yaml` describes everything: the `sanctio` service (Docker: API + website), the `swiftship-demo` service,
and a PostgreSQL database, all on Render's **free** plans. Things to know about free plans:
- **Services sleep after 15 minutes without visitors** and take about a minute to wake. Opening SwiftShip also wakes
  Sanctio, and Sanctio wakes SwiftShip when it starts, so opening one link is enough. Do it ~10 minutes before you present.
- **The free database expires 30 days after it is created.** Create it within 30 days of your defence, or use a free
  [Neon](https://neon.tech) database instead: paste its connection string as `DATABASE_URL` on the sanctio service.
- **There is no Shell tab**, so reset the demo from the dashboard (step 5).

1. Push the repository to GitHub. In Render: **New → Blueprint**, choose the repository and the `main` branch.
2. When asked for values: `DEMO_ADMIN_PASSWORD` (your dashboard password), `GEMINI_API_KEY` (from
   https://aistudio.google.com/apikey), and the WhatsApp values (optional, see below). Leave `DEMO_BUSINESS_URL` and
   `SANCTIO_URL` blank for now.
3. After the first deploy, copy the two public URLs. Set `DEMO_BUSINESS_URL` on **sanctio** to the swiftship-demo URL,
   and `SANCTIO_URL` on **swiftship-demo** to the sanctio URL. Both redeploy. On start, Sanctio seeds the demo
   business if it doesn't exist yet.
4. Open the SwiftShip URL, sign in as a customer and chat. Sign in to the Sanctio URL as `demo@swiftship.test`
   to see the dashboard, and press **Setup → AI model → Test AI**.
5. **Reset before each rehearsal and before the defence:** sign in as `demo@swiftship.test` and press
   **Setup → Demo data → Reset demo**. It clears conversations, handoffs and logs, and restores the shipments.

**WhatsApp on the hosted demo:** use a permanent access token (Meta Business Settings → System users → generate
a token with `whatsapp_business_messaging`). The temporary API Setup token expires after 24 hours. Set the
callback URL to `https://<sanctio-url>/webhooks/whatsapp` and the verify token to the generated
`WHATSAPP_VERIFY_TOKEN` (shown in the service's Environment tab). To link customers' phones, set
`DEMO_CUSTOMER_PHONES` (for example `C-1001=+2348030000001`) on both services and reset. Meta's test number only
messages the phone numbers you have added as recipients.

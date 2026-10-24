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
| `GEMINI_API_KEY` | empty | Google Gemini key. Without it the agent uses the built-in rule-based engine. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model used when a key is set. |
| `APP_SECRET` | development value | Signs dashboard sign-in tokens. **Set a long random value in production.** |
| `ALLOW_PRIVATE_WEBHOOK_URLS` | `1` | Allows `http://localhost` action URLs for development. **Set to `0` in production.** |
| `DATABASE_URL` | SQLite file | Any SQLAlchemy URL. |
| `CORS_ORIGINS` | `*` | Comma-separated origins allowed to call the API from a browser. |

The app reads real environment variables; it does not load a `.env` file by itself.

## Tests
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```
The tests run the whole flow against an in-process fake logistics backend (`backend/tests/fake_business.py`), which
is also a compact reference for how a business's action endpoint should behave.

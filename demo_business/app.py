"""SwiftShip: a small demo business that has integrated Sanctio.

It plays the part of a real customer of the platform:
  * its customers sign in on its own website (a fake sign-in: pick a demo customer)
  * its server opens a Sanctio session for the signed-in customer and embeds the chat widget
  * it exposes the action endpoint Sanctio calls (POST /sanctio): it verifies Sanctio's signature, scopes
    every request to the customer id Sanctio sends, and changes nothing when dry_run is true

Settings (environment variables):
  SANCTIO_URL          public URL of the Sanctio instance, e.g. https://sanctio.onrender.com
  DEMO_API_KEY         the business's Sanctio API key (server side only, never sent to the browser)
  DEMO_WEBHOOK_SECRET  verifies requests from Sanctio
  DEMO_RESET_TOKEN     protects POST /demo/reset
  DEMO_CUSTOMER_PHONES optional "C-1001=+2348030000001,...": verified numbers, linked to WhatsApp via the session
"""
import hashlib
import hmac
import html
import json
import os
import threading
import time
from datetime import date, timedelta
from urllib.parse import parse_qs

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

SANCTIO_URL = os.getenv("SANCTIO_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("DEMO_API_KEY", "")
WEBHOOK_SECRET = os.getenv("DEMO_WEBHOOK_SECRET", "")
RESET_TOKEN = os.getenv("DEMO_RESET_TOKEN", "")
PHONES = dict(p.split("=", 1) for p in filter(None, os.getenv("DEMO_CUSTOMER_PHONES", "").replace(" ", "").split(",")))
MAX_CLOCK_SKEW = 300  # seconds; older signed requests are refused (replay protection)
sanctio_transport: httpx.BaseTransport | None = None  # tests route calls to an in-process Sanctio

CUSTOMERS = {"C-1001": ("Amina Yusuf", "amina@example.com"), "C-1002": ("Chinedu Okafor", "chinedu@example.com"),
             "C-1003": ("Fatima Bello", "fatima@example.com")}

app = FastAPI(title="SwiftShip (Sanctio demo business)", docs_url=None, redoc_url=None)


# ------------------------------------------------------------------ the business's own data
class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        d = lambda days: (date.today() + timedelta(days=days)).isoformat()  # noqa: E731
        with self.lock:
            self.shipments = {
                "SHP-1001": {"customer": "C-1001", "route": "Lagos to Kano", "status": "in_transit", "fee": 4500,
                             "address": "15 Zoo Road, Kano", "eta": d(2)},
                "SHP-1002": {"customer": "C-1001", "route": "Abuja to Kaduna", "status": "pending_pickup", "fee": 3000,
                             "address": "22 Ahmadu Bello Way, Kaduna", "eta": d(4)},
                "SHP-1003": {"customer": "C-1001", "route": "Lagos to Ibadan", "status": "delivered", "fee": 8000,
                             "address": "3 Ring Road, Ibadan", "eta": d(-8)},
                "SHP-2001": {"customer": "C-1002", "route": "Kano to Jos", "status": "pending_pickup", "fee": 5000,
                             "address": "7 Bank Road, Jos", "eta": d(3)},
                "SHP-3001": {"customer": "C-1003", "route": "Lagos to Abuja", "status": "delivered", "fee": 95000,
                             "address": "1 Aso Drive, Abuja", "eta": d(-9)},
            }

    def mine(self, customer: str) -> list[dict]:
        return [{"tracking_number": ref, **{k: v for k, v in s.items() if k != "customer"}}
                for ref, s in self.shipments.items() if s["customer"] == customer]

    def run(self, action: str, customer: str, params: dict, dry_run: bool) -> dict:
        with self.lock:
            return self._run(action, customer, params, dry_run)

    def _run(self, action, customer, params, dry_run):
        if action == "list_shipments":
            return {"ok": True, "data": {"shipments": [{k: s[k] for k in ("tracking_number", "route", "status")}
                                                       for s in self.mine(customer)]}}
        ref = str(params.get("tracking_number", "")).upper()
        s = self.shipments.get(ref)
        if not s or s["customer"] != customer:  # same answer for "not found" and "not yours"
            return {"ok": False, "error": "Shipment not found on this account"}
        status = s["status"].replace("_", " ")
        if action == "track_shipment":
            return {"ok": True, "summary": f"Shipment {ref} ({s['route']}) is {status}. Expected delivery: {s['eta']}.",
                    "data": {"tracking_number": ref, **{k: s[k] for k in ("route", "status", "eta", "address")}}}
        if action == "cancel_shipment":
            if s["status"] != "pending_pickup":
                return {"ok": False, "error": f"Shipment is already {status} and cannot be cancelled"}
            if not dry_run:
                s["status"] = "cancelled"
            return {"ok": True, "dry_run": dry_run, "summary": f"Cancel shipment {ref} ({s['route']})",
                    "data": {"tracking_number": ref, "status": s["status"]}}
        if action == "change_delivery_address":
            if s["status"] != "pending_pickup":
                return {"ok": False, "error": "The address can only be changed before pickup"}
            new = str(params.get("new_address", "")).strip()[:200]
            if not dry_run:
                s["address"] = new
            return {"ok": True, "dry_run": dry_run, "summary": f"Change the delivery address of {ref} to \"{new}\"",
                    "data": {"tracking_number": ref, "address": new}}
        if action == "request_refund":
            if s["status"] != "delivered":
                return {"ok": False, "error": "Refunds apply to delivered shipments only"}
            if not dry_run:
                s["status"] = "refunded"
            return {"ok": True, "dry_run": dry_run, "amount": s["fee"],
                    "summary": f"Refund NGN {s['fee']:,} for shipment {ref}",
                    "data": {"tracking_number": ref, "refund_amount": s["fee"], "status": s["status"]}}
        return {"ok": False, "error": "Unknown action"}


store = Store()


# ------------------------------------------------------------------ the endpoint Sanctio calls
def valid_sanctio_request(request: Request, body: bytes) -> bool:
    timestamp = request.headers.get("X-Sanctio-Timestamp", "")
    if not WEBHOOK_SECRET or not timestamp.isdigit() or abs(time.time() - int(timestamp)) > MAX_CLOCK_SKEW:
        return False
    expected = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, request.headers.get("X-Sanctio-Signature", ""))


@app.post("/sanctio")
async def sanctio_action(request: Request):
    body = await request.body()
    if not valid_sanctio_request(request, body):
        return JSONResponse({"ok": False, "error": "Bad signature"}, status_code=401)
    req = json.loads(body)
    params = req.get("params") if isinstance(req.get("params"), dict) else {}
    return store.run(str(req.get("action")), str(req.get("customer_id")), params, req.get("dry_run") is not False)


@app.post("/demo/reset")
def reset(request: Request):
    if not RESET_TOKEN or not hmac.compare_digest(request.headers.get("X-Demo-Token", ""), RESET_TOKEN):
        return JSONResponse({"ok": False}, status_code=403)
    store.reset()
    return {"ok": True}


@app.get("/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------------------------ the business's website
def _cookie_value(customer_id: str) -> str:
    sig = hmac.new(("signin:" + WEBHOOK_SECRET).encode(), customer_id.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{customer_id}.{sig}"


def signed_in(request: Request) -> str | None:
    customer_id, _, _ = request.cookies.get("swiftship", "").partition(".")
    if customer_id in CUSTOMERS and hmac.compare_digest(request.cookies.get("swiftship", ""), _cookie_value(customer_id)):
        return customer_id
    return None


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>SwiftShip</title>
<style>
:root {{ --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --brand:#c2410c; --soft:#fff7ed; }}
* {{ box-sizing:border-box; }} body {{ margin:0; font:15px/1.5 system-ui,sans-serif; color:var(--ink); background:#f8fafc; }}
header {{ display:flex; align-items:center; justify-content:space-between; padding:14px 24px; background:#fff; border-bottom:1px solid var(--line); }}
.logo {{ font-weight:800; font-size:20px; color:var(--brand); letter-spacing:-.02em; }} .logo span {{ color:var(--ink); }}
main {{ max-width:900px; margin:0 auto; padding:28px 16px 120px; }}
h1 {{ font-size:26px; margin:0 0 6px; }} .muted {{ color:var(--muted); }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; margin-top:20px; }}
.card {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:18px; }}
button {{ font:inherit; font-weight:600; border:0; border-radius:8px; padding:9px 16px; cursor:pointer; color:#fff; background:var(--brand); }}
button.ghost {{ background:#fff; color:var(--ink); border:1px solid var(--line); }}
.table {{ width:100%; border-collapse:collapse; margin-top:16px; background:#fff; border:1px solid var(--line); border-radius:12px; overflow:hidden; }}
.table th, .table td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); font-size:14px; }}
.table th {{ background:#f1f5f9; font-weight:600; }} .wrap {{ overflow-x:auto; }}
.status {{ display:inline-block; padding:2px 10px; border-radius:99px; font-size:12px; font-weight:600; background:#e2e8f0; }}
.status.pending_pickup {{ background:#fef3c7; color:#92400e; }} .status.in_transit {{ background:#dbeafe; color:#1e40af; }}
.status.delivered {{ background:#dcfce7; color:#166534; }} .status.cancelled {{ background:#fee2e2; color:#991b1b; }}
.status.refunded {{ background:#ede9fe; color:#5b21b6; }}
.changed {{ animation: flash 1.6s ease-out; }} @keyframes flash {{ from {{ background:#fde68a; }} to {{ background:transparent; }} }}
.banner {{ background:var(--soft); border:1px solid #fed7aa; border-radius:10px; padding:12px 14px; margin-top:16px; }}
.error {{ background:#fef2f2; border-color:#fecaca; }}
</style></head><body>
<header><div class="logo">Swift<span>Ship</span></div>{nav}</header>
<main>{body}</main>{scripts}</body></html>"""


def page(body: str, nav: str = "", scripts: str = "") -> HTMLResponse:
    return HTMLResponse(PAGE.format(body=body, nav=nav, scripts=scripts))


_last_wake = 0.0


def wake_sanctio() -> None:
    """Free hosting puts idle services to sleep. Opening SwiftShip starts waking Sanctio in the
    background, so it is ready by the time the customer has signed in."""
    global _last_wake
    if sanctio_transport is not None or time.time() - _last_wake < 60:
        return
    _last_wake = time.time()

    def ping():
        try:
            httpx.get(f"{SANCTIO_URL}/api/health", timeout=90)
        except httpx.HTTPError:
            pass
    threading.Thread(target=ping, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    wake_sanctio()
    if signed_in(request):
        return RedirectResponse("/account", status_code=303)
    cards = "".join(
        f"""<form class="card" method="post" action="/login"><input type="hidden" name="customer_id" value="{cid}">
        <strong>{html.escape(name)}</strong><div class="muted">{html.escape(email)}</div>
        <div class="muted" style="margin:6px 0 12px">Customer {cid}</div><button>Sign in</button></form>"""
        for cid, (name, email) in CUSTOMERS.items())
    return page(f"""<h1>Sign in to SwiftShip</h1>
      <p class="muted">Demo store: choose a customer to sign in as. In a real app this is your normal login;
      Sanctio only ever learns who the customer is from this website's server.</p><div class="cards">{cards}</div>""")


@app.post("/login")
async def login(request: Request):
    customer_id = parse_qs((await request.body()).decode()).get("customer_id", [""])[0]
    if customer_id not in CUSTOMERS:
        return RedirectResponse("/", status_code=303)
    response = RedirectResponse("/account", status_code=303)
    response.set_cookie("swiftship", _cookie_value(customer_id), httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("swiftship")
    return response


def open_sanctio_session(customer_id: str) -> str:
    """Server to server, with the secret API key: the browser only receives the session token."""
    name, email = CUSTOMERS[customer_id]
    body = {"customer_id": customer_id, "customer_name": name, "customer_email": email}
    if PHONES.get(customer_id):
        body["customer_phone"] = PHONES[customer_id]  # numbers this business has verified
    # long timeout: on Render's free plan Sanctio may be waking up, which takes about a minute
    with httpx.Client(transport=sanctio_transport, timeout=90) as client:
        r = client.post(f"{SANCTIO_URL}/api/v1/sessions", json=body, headers={"X-API-Key": API_KEY})
    r.raise_for_status()
    return r.json()["session_token"]


@app.get("/account", response_class=HTMLResponse)
def account(request: Request):
    customer_id = signed_in(request)
    if not customer_id:
        return RedirectResponse("/", status_code=303)
    name = CUSTOMERS[customer_id][0]
    nav = f"""<form method="post" action="/logout" style="margin:0"><span class="muted">{html.escape(name)}</span>
      <button class="ghost" style="margin-left:10px">Sign out</button></form>"""
    try:
        token = open_sanctio_session(customer_id)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        token, problem = None, f"Support chat is unavailable: could not reach Sanctio at {SANCTIO_URL} ({exc.__class__.__name__})."
    body = f"""<h1>Hello, {html.escape(name.split()[0])}</h1>
      <p class="muted">Your shipments. Questions about a delivery? Use the chat in the corner.</p>
      <div class="wrap"><table class="table"><thead><tr><th>Tracking</th><th>Route</th><th>Status</th><th>Address</th>
      <th>Expected</th><th>Fee</th></tr></thead><tbody id="rows"></tbody></table></div>
      {'' if token else f'<div class="banner error">{html.escape(problem)}</div>'}
      <div class="banner"><b>Try asking:</b> "Where is SHP-1001?" · "My package SHP-1001 is late" · "Cancel SHP-1002" ·
      "I want a refund for SHP-1003" · "I want to speak to a human"</div>"""
    widget = (f"""<script src="{html.escape(SANCTIO_URL)}/widget.js"></script>
      <script>Sanctio.init({{ sessionToken: {json.dumps(token)}, title: 'SwiftShip support', color: '#c2410c' }})</script>"""
              if token else "")
    scripts = widget + """<script>
      let last = {}
      async function load() {
        const rows = await fetch('/api/my-shipments').then(r => r.ok ? r.json() : [])
        document.getElementById('rows').innerHTML = rows.map(s => {
          const changed = last[s.tracking_number] && last[s.tracking_number] !== s.status + s.address
          last[s.tracking_number] = s.status + s.address
          const esc = (v) => String(v).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))
          return `<tr class="${changed ? 'changed' : ''}"><td><b>${esc(s.tracking_number)}</b></td><td>${esc(s.route)}</td>
            <td><span class="status ${esc(s.status)}">${esc(s.status.replace('_', ' '))}</span></td><td>${esc(s.address)}</td>
            <td>${esc(s.eta)}</td><td>NGN ${Number(s.fee).toLocaleString()}</td></tr>`
        }).join('')
      }
      load(); setInterval(load, 3000)
    </script>"""
    return page(body, nav, scripts)


@app.get("/api/my-shipments")
def my_shipments(request: Request):
    customer_id = signed_in(request)
    if not customer_id:
        return JSONResponse([], status_code=401)
    return store.mine(customer_id)

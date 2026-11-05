"""Bella Wears: a small fashion shop that sells only on WhatsApp, used for the WhatsApp demo.

It has no website for customers. Customers message the shop's WhatsApp number and Sanctio answers for
the owner: prices, orders (pay on delivery), tracking, cancellations and returns. This file plays the
shop's own system:
  * POST /shop/sanctio   the action endpoint Sanctio calls (signed, like SwiftShip's /sanctio)
  * GET  /shop           the owner's order board: new orders appear live; the owner dispatches and delivers

Customers are identified by the id Sanctio sends, which for WhatsApp customers is made from their phone
number (e.g. WA-2348031234567), so a customer only ever sees orders placed from their own number.
"""
import hashlib
import hmac
import html
import json
import os
import re
import threading
import time
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

DEMO_WEBHOOK_SECRET = os.getenv("DEMO_WEBHOOK_SECRET", "")
MAX_CLOCK_SKEW = 300
DELIVERY_FEE = 2500
MAX_QUANTITY = 10

router = APIRouter(prefix="/shop")


def shop_secret(demo_secret: str) -> str:
    """The shop's webhook secret, made from the demo secret so no extra setting is needed.
    The seed script uses the same function, so Sanctio and the shop agree on it."""
    return hmac.new(demo_secret.encode(), b"bella-wears", hashlib.sha256).hexdigest() if demo_secret else ""


# code: (name, category, price in naira, sizes, stock)
PRODUCTS = {
    "BW-101": ("Black kaftan (men)", "men", 18500, ["M", "L", "XL"], 6),
    "BW-102": ("Embroidered agbada set (men)", "men", 65000, ["L", "XL"], 3),
    "BW-103": ("Ankara maxi dress", "women", 22000, ["S", "M", "L"], 8),
    "BW-104": ("Adire two-piece set", "women", 27500, ["S", "M", "L"], 5),
    "BW-105": ("Black abaya", "women", 15000, ["S", "M", "L", "XL"], 10),
    "BW-106": ("Leather slippers (men)", "shoes", 12000, ["41", "42", "43", "44", "45"], 7),
    "BW-107": ("Lace fabric, 5 yards", "fabric", 45000, [], 4),
    "BW-108": ("Fila cap", "accessories", 6500, [], 0),
}


class Shop:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.stock = {code: p[4] for code, p in PRODUCTS.items()}
            self.orders: dict[str, dict] = {}
            self.next_number = 1001

    # ---------------------------------------------------------------- helpers
    def find_product(self, text: str) -> tuple[str | None, str]:
        """Match a product code (BW-101) or words of its name. Returns (code, error)."""
        text = str(text or "").strip()
        code = text.upper()
        if code in PRODUCTS:
            return code, ""
        words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in ("the", "a", "an", "for", "set")]
        matches = [c for c, p in PRODUCTS.items() if words and all(w.rstrip("s") in p[0].lower() for w in words)]
        if len(matches) == 1:
            return matches[0], ""
        if matches:
            return None, "Which one do you mean: " + ", ".join(f"{PRODUCTS[c][0]} ({c})" for c in matches) + "?"
        return None, f"We don't sell \"{text[:40]}\". Ask to see the catalogue for what we have."

    def product_view(self, code: str) -> dict:
        name, category, price, sizes, _ = PRODUCTS[code]
        return {"code": code, "name": name, "category": category, "price": price, "sizes": sizes,
                "in_stock": self.stock[code]}

    def mine(self, customer: str) -> list[dict]:
        return [o for o in self.orders.values() if o["customer"] == customer]

    # ---------------------------------------------------------------- actions Sanctio can call
    def run(self, action: str, customer: str, params: dict, dry_run: bool) -> dict:
        with self.lock:
            return self._run(action, customer, params, dry_run)

    def _run(self, action, customer, params, dry_run):
        if action == "list_products":
            query = str(params.get("query", "")).lower().strip()
            items = [self.product_view(c) for c, p in PRODUCTS.items()
                     if not query or query in p[0].lower() or query in p[1] or query == c.lower()]
            if not items:  # nothing matched the words: show everything rather than nothing
                items = [self.product_view(c) for c in PRODUCTS]
            return {"ok": True, "summary": f"{len(items)} products. Delivery is NGN {DELIVERY_FEE:,}; pay on delivery.",
                    "data": {"products": items, "delivery_fee": DELIVERY_FEE}}
        if action == "place_order":
            return self._place_order(customer, params, dry_run)
        if action == "list_orders":
            return {"ok": True, "data": {"orders": [self._public(o) for o in self.mine(customer)]},
                    "summary": f"{len(self.mine(customer))} orders"}

        ref = str(params.get("order_number", "")).upper()
        order = self.orders.get(ref)
        if not order or order["customer"] != customer:  # same answer for "not found" and "not yours"
            return {"ok": False, "error": "Order not found for this WhatsApp number"}
        what = f"{order['quantity']} × {order['product']}"
        if action == "track_order":
            return {"ok": True, "summary": f"Order {ref} ({what}) is {order['status']}.", "data": self._public(order)}
        if action == "cancel_order":
            if order["status"] != "processing":
                return {"ok": False, "error": f"Order {ref} has already been {order['status']}, so it can't be cancelled"}
            if not dry_run:
                order["status"] = "cancelled"
                self.stock[order["code"]] += order["quantity"]
            return {"ok": True, "dry_run": dry_run, "summary": f"Cancel order {ref} ({what})",
                    "data": self._public(order)}
        if action == "change_delivery_address":
            if order["status"] != "processing":
                return {"ok": False, "error": "The address can only be changed before the order is dispatched"}
            new = str(params.get("new_address", "")).strip()[:200]
            if len(new) < 8:
                return {"ok": False, "error": "Please give the full delivery address"}
            if not dry_run:
                order["address"] = new
            return {"ok": True, "dry_run": dry_run, "summary": f"Deliver order {ref} to \"{new}\" instead",
                    "data": self._public(order)}
        if action == "request_return":
            if order["status"] != "delivered":
                return {"ok": False, "error": "Only delivered orders can be returned"}
            refund = order["price"] * order["quantity"]
            if not dry_run:
                order["status"] = "returned"
                order["refund"] = refund
            return {"ok": True, "dry_run": dry_run, "amount": refund,
                    "summary": f"Return order {ref} ({what}) and refund NGN {refund:,} after our rider collects it",
                    "data": self._public(order)}
        return {"ok": False, "error": "Unknown action"}

    def _place_order(self, customer, params, dry_run):
        code, problem = self.find_product(params.get("product", ""))
        if problem:
            return {"ok": False, "error": problem}
        name, _, price, sizes, _ = PRODUCTS[code]
        size = str(params.get("size", "")).strip().upper()
        if sizes and size not in sizes:
            return {"ok": False, "error": f"Which size? {name} comes in {', '.join(sizes)}"}
        try:
            quantity = int(params.get("quantity", 1))
        except (TypeError, ValueError):
            quantity = 0
        if not 1 <= quantity <= MAX_QUANTITY:
            return {"ok": False, "error": f"You can order between 1 and {MAX_QUANTITY} at a time"}
        if self.stock[code] < quantity:
            left = self.stock[code]
            return {"ok": False, "error": f"Sorry, {name} is out of stock" if not left
                    else f"Sorry, only {left} {name} left in stock"}
        address = str(params.get("delivery_address", "")).strip()[:200]
        if len(address) < 8:
            return {"ok": False, "error": "Please give the full delivery address"}
        total = price * quantity + DELIVERY_FEE
        item = f"{quantity} × {name}" + (f" (size {size})" if sizes else "")
        details = f"{item} = NGN {total:,} including NGN {DELIVERY_FEE:,} delivery, pay on delivery to {address}"
        if dry_run:
            return {"ok": True, "dry_run": True, "amount": total, "summary": "Order " + details}
        ref = f"ORD-{self.next_number}"
        self.next_number += 1
        self.stock[code] -= quantity
        self.orders[ref] = {"order_number": ref, "customer": customer, "code": code, "product": name, "size": size,
                            "quantity": quantity, "price": price, "total": total, "address": address,
                            "status": "processing", "placed": datetime.now().strftime("%H:%M")}
        return {"ok": True, "dry_run": False, "amount": total, "summary": f"Order {ref} placed: {details}",
                "data": self._public(self.orders[ref])}

    @staticmethod
    def _public(order: dict) -> dict:
        return {k: v for k, v in order.items() if k != "customer"}

    # ---------------------------------------------------------------- the owner's buttons
    def advance(self, ref: str) -> bool:
        with self.lock:
            order = self.orders.get(ref)
            nxt = {"processing": "dispatched", "dispatched": "delivered"}.get(order["status"]) if order else None
            if nxt:
                order["status"] = nxt
            return bool(nxt)


shop = Shop()


# ------------------------------------------------------------------ the endpoint Sanctio calls
def valid_sanctio_request(request: Request, body: bytes) -> bool:
    secret = shop_secret(DEMO_WEBHOOK_SECRET)
    timestamp = request.headers.get("X-Sanctio-Timestamp", "")
    if not secret or not timestamp.isdigit() or abs(time.time() - int(timestamp)) > MAX_CLOCK_SKEW:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, request.headers.get("X-Sanctio-Signature", ""))


@router.post("/sanctio")
async def sanctio_action(request: Request):
    body = await request.body()
    if not valid_sanctio_request(request, body):
        return JSONResponse({"ok": False, "error": "Bad signature"}, status_code=401)
    req = json.loads(body)
    params = req.get("params") if isinstance(req.get("params"), dict) else {}
    return shop.run(str(req.get("action")), str(req.get("customer_id")), params, req.get("dry_run") is not False)


# ------------------------------------------------------------------ the owner's order board
def masked(customer: str) -> str:
    """WA-2348031234567 -> +234 803 *** 4567 (the board may be shown on a projector)."""
    digits = customer.removeprefix("WA-")
    return f"+{digits[:3]} {digits[3:6]} *** {digits[-4:]}" if digits.isdigit() and len(digits) > 8 else customer


@router.get("/api/orders")
def orders_json():
    with shop.lock:
        orders = [{**Shop._public(o), "customer": masked(o["customer"])} for o in reversed(list(shop.orders.values()))]
        stock = [shop.product_view(c) for c in PRODUCTS]
    return {"orders": orders, "products": stock}


@router.post("/orders/{ref}/advance")
def advance(ref: str):
    if not shop.advance(ref.upper()):
        return JSONResponse({"ok": False}, status_code=409)
    return {"ok": True}


BOARD = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Bella Wears – orders</title>
<style>
:root { --ink:#1f2937; --muted:#6b7280; --line:#e5e7eb; --brand:#9d174d; }
* { box-sizing:border-box; } body { margin:0; font:15px/1.5 system-ui,sans-serif; color:var(--ink); background:#fdf2f8; }
header { display:flex; justify-content:space-between; align-items:center; padding:14px 24px; background:#fff; border-bottom:1px solid var(--line); }
.logo { font-weight:800; font-size:20px; color:var(--brand); } main { max-width:1000px; margin:0 auto; padding:24px 16px 60px; }
h2 { font-size:18px; margin:28px 0 8px; } .muted { color:var(--muted); }
.wrap { overflow-x:auto; } table { width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); }
th, td { text-align:left; padding:9px 11px; border-bottom:1px solid var(--line); font-size:14px; } th { background:#fce7f3; }
.status { padding:2px 10px; border-radius:99px; font-size:12px; font-weight:600; background:#e5e7eb; }
.processing { background:#fef3c7; color:#92400e; } .dispatched { background:#dbeafe; color:#1e40af; }
.delivered { background:#dcfce7; color:#166534; } .cancelled { background:#fee2e2; color:#991b1b; } .returned { background:#ede9fe; color:#5b21b6; }
button { font:inherit; font-size:13px; font-weight:600; border:0; border-radius:6px; padding:5px 12px; cursor:pointer; color:#fff; background:var(--brand); }
.out { color:#b91c1c; font-weight:600; }
</style></head><body>
<header><div class="logo">Bella Wears</div><span class="muted">Owner view · orders taken on WhatsApp by Sanctio</span></header>
<main>
<p class="muted">Customers order by WhatsApp; Sanctio answers them and places orders here. Dispatch and deliver orders
with the buttons. Pay on delivery.</p>
<h2>Orders</h2><div class="wrap"><table><thead><tr><th>Order</th><th>Time</th><th>Customer</th><th>Item</th><th>Total</th>
<th>Deliver to</th><th>Status</th><th></th></tr></thead><tbody id="orders"></tbody></table></div>
<h2>Stock</h2><div class="wrap"><table><thead><tr><th>Code</th><th>Product</th><th>Sizes</th><th>Price</th><th>In stock</th></tr></thead>
<tbody id="stock"></tbody></table></div>
</main>
<script>
const esc = (v) => String(v ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))
const naira = (n) => 'NGN ' + Number(n).toLocaleString()
async function load() {
  const d = await fetch('/shop/api/orders').then(r => r.json())
  document.getElementById('orders').innerHTML = d.orders.length ? d.orders.map(o => `<tr>
    <td><b>${esc(o.order_number)}</b></td><td>${esc(o.placed)}</td><td>${esc(o.customer)}</td>
    <td>${esc(o.quantity)} × ${esc(o.product)}${o.size ? ' (' + esc(o.size) + ')' : ''}</td><td>${naira(o.total)}</td>
    <td>${esc(o.address)}</td><td><span class="status ${esc(o.status)}">${esc(o.status)}</span></td>
    <td>${o.status === 'processing' ? `<button onclick="advance('${esc(o.order_number)}')">Dispatch</button>`
       : o.status === 'dispatched' ? `<button onclick="advance('${esc(o.order_number)}')">Delivered</button>` : ''}</td></tr>`).join('')
    : '<tr><td colspan="8" class="muted">No orders yet. Send the shop a WhatsApp message to order.</td></tr>'
  document.getElementById('stock').innerHTML = d.products.map(p => `<tr><td>${esc(p.code)}</td><td>${esc(p.name)}</td>
    <td>${esc(p.sizes.join(', ') || '–')}</td><td>${naira(p.price)}</td>
    <td class="${p.in_stock ? '' : 'out'}">${p.in_stock || 'Out of stock'}</td></tr>`).join('')
}
async function advance(ref) { await fetch('/shop/orders/' + ref + '/advance', { method: 'POST' }); load() }
load(); setInterval(load, 3000)
</script></body></html>"""


@router.get("", response_class=HTMLResponse)
def board():
    return HTMLResponse(BOARD)

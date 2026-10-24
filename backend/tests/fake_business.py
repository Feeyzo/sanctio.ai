"""An in-process stand-in for a business's backend (a small logistics company).

It behaves the way the integration guide tells businesses to build their action
endpoint: verify the signature, scope everything to the `customer_id` in the
request, and change nothing when `dry_run` is true.
"""
import hashlib
import hmac
import json

import httpx

BASE = "https://api.swiftship.test"


class FakeLogistics:
    def __init__(self):
        self.secret = ""
        self.calls = []  # every request body received, for assertions
        self.shipments = {
            "SHP-1001": {"customer": "C-1001", "route": "Lagos to Kano", "status": "in_transit", "fee": 4500,
                         "address": "15 Zoo Road, Kano", "eta": "2026-10-14"},
            "SHP-1002": {"customer": "C-1001", "route": "Abuja to Kaduna", "status": "pending_pickup", "fee": 3000,
                         "address": "22 Ahmadu Bello Way, Kaduna", "eta": "2026-10-16"},
            "SHP-1003": {"customer": "C-1001", "route": "Lagos to Ibadan", "status": "delivered", "fee": 8000,
                         "address": "3 Ring Road, Ibadan", "eta": "2026-10-02"},
            "SHP-2001": {"customer": "C-1002", "route": "Kano to Jos", "status": "pending_pickup", "fee": 5000,
                         "address": "7 Bank Road, Jos", "eta": "2026-10-15"},
            "SHP-3001": {"customer": "C-1003", "route": "Lagos to Abuja", "status": "delivered", "fee": 95000,
                         "address": "1 Aso Drive, Abuja", "eta": "2026-10-01"},
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = request.content
        expected = "sha256=" + hmac.new(self.secret.encode(), request.headers["X-Sanctio-Timestamp"].encode() + b"."
                                        + body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("X-Sanctio-Signature", "")):
            return httpx.Response(401, json={"ok": False, "error": "Bad signature"})
        req = json.loads(body)
        self.calls.append(req)
        path = request.url.path
        if path == "/down":
            return httpx.Response(503, text="maintenance")
        if path == "/ignores-dry-run":  # a badly built endpoint: acts immediately and never echoes dry_run
            return httpx.Response(200, json={"ok": True, "summary": "Did it straight away"})
        return httpx.Response(200, json=self.run(req["action"], req["customer_id"], req["params"], req["dry_run"]))

    def run(self, action: str, customer: str, params: dict, dry_run: bool) -> dict:
        if action == "list_shipments":
            mine = [{"tracking_number": ref, "route": s["route"], "status": s["status"]}
                    for ref, s in self.shipments.items() if s["customer"] == customer]
            return {"ok": True, "data": {"shipments": mine}}

        ref = params["tracking_number"].upper()
        s = self.shipments.get(ref)
        if not s or s["customer"] != customer:  # same answer for "not found" and "not yours"
            return {"ok": False, "error": "Shipment not found on this account"}

        if action == "track_shipment":
            return {"ok": True, "summary": f"Shipment {ref} ({s['route']}) is {s['status'].replace('_', ' ')}. "
                                           f"Expected delivery: {s['eta']}.",
                    "data": {"tracking_number": ref, **{k: s[k] for k in ("route", "status", "eta", "address")}}}
        if action == "cancel_shipment":
            if s["status"] != "pending_pickup":
                return {"ok": False, "error": f"Shipment is already {s['status'].replace('_', ' ')} and cannot be cancelled"}
            if not dry_run:
                s["status"] = "cancelled"
            return {"ok": True, "dry_run": dry_run, "summary": f"Cancel shipment {ref} ({s['route']})",
                    "data": {"tracking_number": ref, "status": s["status"]}}
        if action == "change_delivery_address":
            if s["status"] != "pending_pickup":
                return {"ok": False, "error": "The address can only be changed before pickup"}
            if not dry_run:
                s["address"] = params["new_address"]
            return {"ok": True, "dry_run": dry_run,
                    "summary": f"Change the delivery address of {ref} to \"{params['new_address']}\"",
                    "data": {"tracking_number": ref, "address": params["new_address"]}}
        if action == "request_refund":
            if s["status"] != "delivered":
                return {"ok": False, "error": "Refunds apply to delivered shipments only"}
            if not dry_run:
                s["status"] = "refunded"
            return {"ok": True, "dry_run": dry_run, "amount": s["fee"],
                    "summary": f"Refund NGN {s['fee']:,} for shipment {ref}",
                    "data": {"tracking_number": ref, "refund_amount": s["fee"], "status": s["status"]}}
        return {"ok": False, "error": "Unknown action"}


TRACKING = {"name": "tracking_number", "type": "string", "description": "tracking number (e.g. SHP-1001)",
            "required": True, "pattern": r"SHP-\d{4,8}"}

ACTIONS = [
    {"name": "list_shipments", "description": "List the customer's recent shipments", "url": f"{BASE}/sanctio",
     "params": []},
    {"name": "track_shipment", "description": "Get the current status and location of a shipment or package",
     "url": f"{BASE}/sanctio", "params": [TRACKING]},
    {"name": "cancel_shipment", "description": "Cancel a shipment that has not been picked up", "url": f"{BASE}/sanctio",
     "params": [TRACKING], "mutates": True, "risk": "medium"},
    {"name": "change_delivery_address", "description": "Change the delivery address before pickup",
     "url": f"{BASE}/sanctio", "mutates": True, "risk": "medium",
     "params": [TRACKING, {"name": "new_address", "type": "string", "description": "full new delivery address"}]},
    {"name": "request_refund", "description": "Refund the fee for a delivered shipment (lost or damaged package)",
     "url": f"{BASE}/sanctio", "mutates": True, "risk": "high", "approval": "over_amount", "approval_amount": 50000,
     "params": [TRACKING, {"name": "reason", "type": "string", "description": "reason for the refund"}]},
]

ARTICLES = [
    {"title": "Late delivery", "content": "1. Check the expected delivery date on your shipment.\n"
     "2. Make sure your phone is reachable — riders call before delivery.\n"
     "3. If the date has passed by more than 2 days, we will escalate it to the dispatch team."},
    {"title": "Payment deducted but no shipment created", "content": "1. Debits without a booking are usually "
     "reversed by the bank within 24 hours.\n2. Check your email or SMS for a booking confirmation.\n"
     "3. If 24 hours have passed, share the transaction date and amount so we can trace it."},
    {"title": "Login problems", "content": "1. Use 'Forgot password' on the sign-in page.\n"
     "2. Check your spam folder for the reset email.\n3. Update the app, then try again."},
]

"""Create, or reset, the two demo businesses on this Sanctio instance:
  * SwiftShip Logistics: a courier with its own website and the chat widget (the main case study)
  * Bella Wears: a fashion shop that sells only on WhatsApp (the WhatsApp demo). Both run in demo_business/.

    python -m scripts.seed_demo              # full reset: wipes the demo business's data and recreates it
    python -m scripts.seed_demo --if-missing # only seed if the demo business does not exist yet (used on start)

Everything else stays untouched. Settings (environment variables):
    DEMO_API_KEY, DEMO_WEBHOOK_SECRET  shared with the demo business app (it uses them to call and verify Sanctio)
    DEMO_BUSINESS_URL                  public URL of the demo business app, e.g. https://swiftship-demo.onrender.com
    DEMO_ADMIN_PASSWORD                dashboard password for the demo account
    DEMO_ADMIN_EMAIL                   dashboard sign-in (default demo@swiftship.test)
    DEMO_SHOP_ADMIN_EMAIL              Bella Wears dashboard sign-in (default owner@bellawears.test, same password)
    DEMO_CUSTOMER_PHONES               optional: "C-1001=+2348030000001,C-1002=+234..." links WhatsApp numbers
    DEMO_RESET_TOKEN                   optional: also resets the shipments in the demo business app
    WHATSAPP_PHONE_NUMBER_ID           optional: connects that WhatsApp number to Bella Wears

Resetting keeps WhatsApp numbers and customer phones that were linked on the dashboard.
"""
import hashlib
import hmac
import json
import os
import sys
from dataclasses import dataclass, field

import httpx

from app import config
from app.channels.whatsapp_api import normalise_phone
from app.db import Base, SessionLocal, engine
from app.models import (Action, ActionLog, AdminUser, Business, Conversation, Customer, CustomerSession, Handoff,
                        KnowledgeArticle, Message, SecurityEvent, WhatsAppInbound, WhatsAppNumber)
from app.security import hash_password, sha256

DESCRIPTION = ("SwiftShip is a parcel delivery company operating between Nigerian cities. Customers book "
               "shipments online, track them, change delivery addresses before pickup, and claim refunds for "
               "lost or damaged parcels.")

CUSTOMERS = [("C-1001", "Amina Yusuf", "amina@example.com"), ("C-1002", "Chinedu Okafor", "chinedu@example.com"),
             ("C-1003", "Fatima Bello", "fatima@example.com")]

TRACKING = {"name": "tracking_number", "type": "string", "description": "tracking number (e.g. SHP-1001)",
            "required": True, "pattern": r"SHP-\d{4,8}"}

ACTIONS = [
    {"name": "list_shipments", "description": "List the customer's recent shipments", "params": []},
    {"name": "track_shipment", "description": "Get the current status and location of a shipment or package",
     "params": [TRACKING]},
    {"name": "cancel_shipment", "description": "Cancel a shipment that has not been picked up",
     "params": [TRACKING], "mutates": True, "risk": "medium"},
    {"name": "change_delivery_address", "description": "Change the delivery address before pickup",
     "mutates": True, "risk": "medium",
     "params": [TRACKING, {"name": "new_address", "type": "string", "description": "full new delivery address"}]},
    {"name": "request_refund", "description": "Refund the fee for a delivered shipment (lost or damaged package)",
     "mutates": True, "risk": "high", "approval": "over_amount", "approval_amount": 50000,
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
    {"title": "Refund policy", "content": "Refunds cover the delivery fee of a delivered shipment that arrived "
     "damaged or was lost. Refunds above NGN 50,000 are reviewed by our team before they are paid."},
]


SHOP_DESCRIPTION = (
    "Bella Wears is a small fashion shop in Kano that sells men's and women's Nigerian and modest fashion "
    "through WhatsApp only. Customers ask for prices and sizes, order with pay on delivery, track orders, "
    "cancel or change the address before dispatch, and return delivered items within 7 days. Product codes "
    "look like BW-101 and order numbers like ORD-1001. Always look up the catalogue for prices and stock; "
    "never guess a price. To order you need the product, the size (if it has sizes), the quantity and the "
    "full delivery address.")

ORDER = {"name": "order_number", "type": "string", "description": "order number (e.g. ORD-1001)",
         "required": True, "pattern": r"ORD-\d{4,8}"}

SHOP_ACTIONS = [
    {"name": "list_products", "description": "Show products with prices, sizes and stock",
     "params": [{"name": "query", "type": "string", "required": False,
                 "description": "optional word to filter by, e.g. kaftan, women, shoes"}]},
    {"name": "place_order", "description": "Place a pay-on-delivery order for one product",
     "mutates": True, "risk": "medium", "approval": "over_amount", "approval_amount": 150000,
     "params": [{"name": "product", "type": "string", "description": "product code (e.g. BW-101) or name"},
                {"name": "size", "type": "string", "required": False, "description": "size, if the product has sizes"},
                {"name": "quantity", "type": "integer", "description": "how many"},
                {"name": "delivery_address", "type": "string", "description": "full delivery address"}]},
    {"name": "list_orders", "description": "List the customer's orders", "params": []},
    {"name": "track_order", "description": "Get the status of an order", "params": [ORDER]},
    {"name": "cancel_order", "description": "Cancel an order that has not been dispatched",
     "params": [ORDER], "mutates": True, "risk": "medium"},
    {"name": "change_delivery_address", "description": "Change the delivery address before dispatch",
     "mutates": True, "risk": "medium",
     "params": [ORDER, {"name": "new_address", "type": "string", "description": "full new delivery address"}]},
    {"name": "request_return", "description": "Return a delivered order and refund the item price",
     "mutates": True, "risk": "high", "approval": "over_amount", "approval_amount": 50000,
     "params": [ORDER, {"name": "reason", "type": "string", "description": "reason for the return"}]},
]

SHOP_ARTICLES = [
    {"title": "Delivery", "content": "Delivery within Kano takes 1-2 days; other states 3-5 days. The delivery "
     "fee is NGN 2,500 per order. Our rider calls before delivery."},
    {"title": "Payment", "content": "We only take pay on delivery: cash or bank transfer to the rider when the "
     "order arrives. We never ask for card details, PINs or OTPs on WhatsApp."},
    {"title": "Returns and refunds", "content": "Delivered items can be returned within 7 days if unworn and "
     "with tags. Our rider collects the item and we refund the item price (not the delivery fee). Refunds "
     "above NGN 50,000 are approved by the owner first."},
    {"title": "Size guide", "content": "S fits chest 34-36 in, M 38-40 in, L 42-44 in, XL 46-48 in. Slippers "
     "come in sizes 41 to 45. If you are between sizes, take the larger one."},
    {"title": "Big orders", "content": "Orders above NGN 150,000 are confirmed by the owner before they are "
     "packed; the customer is told once it is approved."},
]


def shop_secret(demo_secret: str) -> str:
    """Same as shop_secret() in demo_business/shop.py: the shop's webhook secret, made from the demo secret."""
    return hmac.new(demo_secret.encode(), b"bella-wears", hashlib.sha256).hexdigest() if demo_secret else ""


@dataclass
class Settings:
    api_key: str
    webhook_secret: str
    business_url: str
    admin_password: str
    admin_email: str = "demo@swiftship.test"
    shop_admin_email: str = "owner@bellawears.test"
    phones: dict = field(default_factory=dict)
    reset_token: str = ""
    whatsapp_phone_number_id: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        phones = {}
        for pair in filter(None, os.getenv("DEMO_CUSTOMER_PHONES", "").split(",")):
            customer_id, _, phone = pair.partition("=")
            normalised = normalise_phone(phone)
            if not normalised:
                raise SystemExit(f"DEMO_CUSTOMER_PHONES: {phone!r} is not an international number")
            phones[customer_id.strip()] = normalised
        return cls(api_key=os.getenv("DEMO_API_KEY", ""), webhook_secret=os.getenv("DEMO_WEBHOOK_SECRET", ""),
                   business_url=os.getenv("DEMO_BUSINESS_URL", "").rstrip("/"),
                   admin_password=os.getenv("DEMO_ADMIN_PASSWORD", ""),
                   admin_email=os.getenv("DEMO_ADMIN_EMAIL", "demo@swiftship.test").strip().lower(),
                   shop_admin_email=os.getenv("DEMO_SHOP_ADMIN_EMAIL", "owner@bellawears.test").strip().lower(),
                   phones=phones, reset_token=os.getenv("DEMO_RESET_TOKEN", ""),
                   whatsapp_phone_number_id=config.WHATSAPP_PHONE_NUMBER_ID)

    def missing(self) -> list[str]:
        required = {"DEMO_API_KEY": self.api_key, "DEMO_WEBHOOK_SECRET": self.webhook_secret,
                    "DEMO_BUSINESS_URL": self.business_url, "DEMO_ADMIN_PASSWORD": self.admin_password}
        return [k for k, v in required.items() if not v]


def _wipe(db, business_id: int) -> None:
    """Delete the demo business's operational data, children first (PostgreSQL enforces foreign keys)."""
    conv_ids = [c for (c,) in db.query(Conversation.id).filter_by(business_id=business_id)]
    if conv_ids:
        for model in (SecurityEvent, Handoff, ActionLog, Message):
            db.query(model).filter(model.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.id.in_(conv_ids)).delete(synchronize_session=False)
    for model in (CustomerSession, Customer, Action, KnowledgeArticle, WhatsAppNumber):
        db.query(model).filter_by(business_id=business_id).delete(synchronize_session=False)


def _business(db, email: str, name: str) -> tuple[Business, AdminUser | None, dict, list]:
    """Find the demo business by its admin's email, or create it. Returns what must survive a reset:
    customer phones and WhatsApp numbers linked on the dashboard."""
    admin = db.query(AdminUser).filter_by(email=email).first()
    business = db.get(Business, admin.business_id) if admin else None
    if business is None:
        business = Business(name=name, api_key_hash="", webhook_secret="")
        db.add(business)
        db.flush()
        return business, None, {}, []
    phones = {c.external_id: c.phone for c in db.query(Customer).filter_by(business_id=business.id) if c.phone}
    numbers = [(n.phone_number_id, n.display_phone) for n in db.query(WhatsAppNumber).filter_by(business_id=business.id)]
    _wipe(db, business.id)
    return business, admin, phones, numbers


def _fill(db, business: Business, admin: AdminUser | None, email: str, contact: str, password: str, url: str,
          actions: list, articles: list) -> None:
    if admin is None:
        admin = AdminUser(business_id=business.id, email=email, name=contact)
        db.add(admin)
    admin.password_hash = hash_password(password)
    for a in actions:
        db.add(Action(business_id=business.id, name=a["name"], description=a["description"],
                      params=json.dumps(a["params"]), url=url, mutates=a.get("mutates", False),
                      risk=a.get("risk", "low"), approval=a.get("approval", "never"),
                      approval_amount=a.get("approval_amount")))
    for k in articles:
        db.add(KnowledgeArticle(business_id=business.id, title=k["title"], content=k["content"]))


def seed(db, s: Settings) -> Business:
    # ---- SwiftShip: website + chat widget
    business, admin, kept_phones, kept_numbers = _business(db, s.admin_email, "SwiftShip Logistics")
    business.name, business.description = "SwiftShip Logistics", DESCRIPTION
    # fixed credentials, shared with the demo business app through environment variables
    business.api_key_hash, business.api_key_prefix = sha256(s.api_key), s.api_key[:12]
    business.webhook_secret = s.webhook_secret
    business.whatsapp_open = False  # only customers who linked their number can act
    _fill(db, business, admin, s.admin_email, "SwiftShip Support", s.admin_password, f"{s.business_url}/sanctio",
          ACTIONS, ARTICLES)
    for external_id, name, email in CUSTOMERS:
        db.add(Customer(business_id=business.id, external_id=external_id, name=name, email=email,
                        phone=s.phones.get(external_id) or kept_phones.get(external_id, "")))
    swiftship_numbers = kept_numbers

    # ---- Bella Wears: WhatsApp only; anyone who messages can order
    shop, shop_admin, shop_phones, shop_numbers = _business(db, s.shop_admin_email, "Bella Wears")
    shop.name, shop.description = "Bella Wears", SHOP_DESCRIPTION
    shop_key = "sk_live_shop_" + sha256(s.api_key)[:24]  # not used: the shop has no website calling the API
    shop.api_key_hash, shop.api_key_prefix = sha256(shop_key), shop_key[:12]
    shop.webhook_secret = shop_secret(s.webhook_secret)
    shop.whatsapp_open = True
    _fill(db, shop, shop_admin, s.shop_admin_email, "Bella Wears Owner", s.admin_password,
          f"{s.business_url}/shop/sanctio", SHOP_ACTIONS, SHOP_ARTICLES)
    db.flush()

    # ---- WhatsApp numbers: put back the ones connected on the dashboard; the server's number goes to the shop
    pnid = s.whatsapp_phone_number_id
    for target, numbers in ((business, swiftship_numbers), (shop, shop_numbers)):
        for number_id, display in numbers:
            if number_id != pnid:
                db.add(WhatsAppNumber(business_id=target.id, phone_number_id=number_id, display_phone=display))
    if pnid:
        db.query(WhatsAppNumber).filter_by(phone_number_id=pnid).delete(synchronize_session=False)
        db.query(WhatsAppInbound).filter_by(phone_number_id=pnid).delete(synchronize_session=False)
        db.add(WhatsAppNumber(business_id=shop.id, phone_number_id=pnid, display_phone="Bella Wears WhatsApp"))
    db.commit()
    return business


RESET_TRANSPORT: httpx.BaseTransport | None = None  # tests route the reset call to an in-process demo app


def reset_demo_business(s: Settings, transport: httpx.BaseTransport | None = None) -> str:
    if not s.reset_token:
        return "skipped (DEMO_RESET_TOKEN not set)"
    try:
        # long timeout: on Render's free plan the demo business may be waking up (about a minute)
        with httpx.Client(transport=transport or RESET_TRANSPORT, timeout=90) as client:
            r = client.post(f"{s.business_url}/demo/reset", headers={"X-Demo-Token": s.reset_token})
        return "done" if r.status_code == 200 else f"failed ({r.status_code})"
    except httpx.HTTPError as exc:
        return f"failed ({exc})"


def main(argv: list[str]) -> int:
    s = Settings.from_env()
    Base.metadata.create_all(engine)
    if "--if-missing" in argv:
        with SessionLocal() as db:
            exists = lambda email: db.query(AdminUser).filter_by(email=email).first() is not None  # noqa: E731
            if not s.admin_email or (exists(s.admin_email) and exists(s.shop_admin_email)):
                print("Demo businesses already exist; not touching them.")
                return 0
        if s.missing():
            print(f"Demo business not seeded; set {', '.join(s.missing())} to enable it.")
            return 0
    elif s.missing():
        print(f"Missing settings: {', '.join(s.missing())}", file=sys.stderr)
        return 1
    with SessionLocal() as db:
        business = seed(db, s)
    print(f"Demo business '{business.name}' ready. Dashboard sign-in: {s.admin_email}")
    print(f"WhatsApp shop 'Bella Wears' ready. Dashboard sign-in: {s.shop_admin_email} (same password). "
          f"Order board: {s.business_url}/shop")
    print(f"WhatsApp number: {s.whatsapp_phone_number_id or 'not connected'} (Bella Wears). "
          f"Linked SwiftShip phones: {s.phones or 'none'}.")
    print(f"Demo business shipments reset: {reset_demo_business(s)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

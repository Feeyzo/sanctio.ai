"""Create, or reset, the SwiftShip demo business on this Sanctio instance.

    python -m scripts.seed_demo              # full reset: wipes the demo business's data and recreates it
    python -m scripts.seed_demo --if-missing # only seed if the demo business does not exist yet (used on start)

Everything else stays untouched. Settings (environment variables):
    DEMO_API_KEY, DEMO_WEBHOOK_SECRET  shared with the demo business app (it uses them to call and verify Sanctio)
    DEMO_BUSINESS_URL                  public URL of the demo business app, e.g. https://swiftship-demo.onrender.com
    DEMO_ADMIN_PASSWORD                dashboard password for the demo account
    DEMO_ADMIN_EMAIL                   dashboard sign-in (default demo@swiftship.test)
    DEMO_CUSTOMER_PHONES               optional: "C-1001=+2348030000001,C-1002=+234..." links WhatsApp numbers
    DEMO_RESET_TOKEN                   optional: also resets the shipments in the demo business app
    WHATSAPP_PHONE_NUMBER_ID           optional: connects that WhatsApp number to the demo business
"""
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


@dataclass
class Settings:
    api_key: str
    webhook_secret: str
    business_url: str
    admin_password: str
    admin_email: str = "demo@swiftship.test"
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


def seed(db, s: Settings) -> Business:
    admin = db.query(AdminUser).filter_by(email=s.admin_email).first()
    business = db.get(Business, admin.business_id) if admin else None
    if business is None:
        business = Business(name="SwiftShip Logistics", api_key_hash="", webhook_secret="")
        db.add(business)
        db.flush()
    else:
        _wipe(db, business.id)
    business.name, business.description = "SwiftShip Logistics", DESCRIPTION
    # fixed credentials, shared with the demo business app through environment variables
    business.api_key_hash, business.api_key_prefix = sha256(s.api_key), s.api_key[:12]
    business.webhook_secret = s.webhook_secret
    if admin is None:
        admin = AdminUser(business_id=business.id, email=s.admin_email, name="SwiftShip Support")
        db.add(admin)
    admin.password_hash = hash_password(s.admin_password)

    for a in ACTIONS:
        db.add(Action(business_id=business.id, name=a["name"], description=a["description"],
                      params=json.dumps(a["params"]), url=f"{s.business_url}/sanctio", mutates=a.get("mutates", False),
                      risk=a.get("risk", "low"), approval=a.get("approval", "never"),
                      approval_amount=a.get("approval_amount")))
    for k in ARTICLES:
        db.add(KnowledgeArticle(business_id=business.id, title=k["title"], content=k["content"]))
    for external_id, name, email in CUSTOMERS:
        db.add(Customer(business_id=business.id, external_id=external_id, name=name, email=email,
                        phone=s.phones.get(external_id, "")))
    if s.whatsapp_phone_number_id:
        pnid = s.whatsapp_phone_number_id
        db.query(WhatsAppNumber).filter_by(phone_number_id=pnid).delete(synchronize_session=False)
        db.query(WhatsAppInbound).filter_by(phone_number_id=pnid).delete(synchronize_session=False)
        db.add(WhatsAppNumber(business_id=business.id, phone_number_id=pnid, display_phone="SwiftShip WhatsApp"))
    db.commit()
    return business


def reset_demo_business(s: Settings, transport: httpx.BaseTransport | None = None) -> str:
    if not s.reset_token:
        return "skipped (DEMO_RESET_TOKEN not set)"
    try:
        with httpx.Client(transport=transport, timeout=15) as client:
            r = client.post(f"{s.business_url}/demo/reset", headers={"X-Demo-Token": s.reset_token})
        return "done" if r.status_code == 200 else f"failed ({r.status_code})"
    except httpx.HTTPError as exc:
        return f"failed ({exc})"


def main(argv: list[str]) -> int:
    s = Settings.from_env()
    Base.metadata.create_all(engine)
    if "--if-missing" in argv:
        with SessionLocal() as db:
            if not s.admin_email or db.query(AdminUser).filter_by(email=s.admin_email).first():
                print("Demo business already exists; not touching it.")
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
    print(f"Actions call {s.business_url}/sanctio. WhatsApp number: {s.whatsapp_phone_number_id or 'not connected'}. "
          f"Linked phones: {s.phones or 'none'}.")
    print(f"Demo business shipments reset: {reset_demo_business(s)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

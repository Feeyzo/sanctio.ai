"""WhatsApp channel (Meta WhatsApp Cloud API).

WhatsApp is only another entry point into `agent.handle_message`; the policy and handoff engines decide
exactly as they do for the web chat. What this module adds:

  * webhook verification (GET) and signed delivery (POST, X-Hub-Signature-256 over the raw body)
  * routing: Meta's phone_number_id -> the business that connected that number
  * identity: the sender's number -> a Customer whose phone the business has linked. A linked customer
    gets an internal session; an unlinked number gets none, so the policy engine denies every action.
  * Confirm / Cancel reply buttons for actions that need the customer's confirmation
"""
import hashlib
import hmac
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import agent, config, policy
from ..db import SessionLocal, get_db
from ..models import (ActionLog, AdminUser, Business, Conversation, Customer, CustomerSession, SecurityEvent,
                      WhatsAppInbound, WhatsAppNumber, now)
from ..security import require_admin, sha256
from .whatsapp_api import WhatsAppClient, WhatsAppError, normalise_phone

log = logging.getLogger("agent.whatsapp")
router = APIRouter()

WINDOW = timedelta(hours=24)
WINDOW_CLOSED = "24-hour window closed — a template message is required"
REENGAGEMENT_ERROR = 131047  # Graph API: more than 24 hours since the customer last replied
BUTTON_RE = re.compile(r"sanctio:(confirm|cancel):(\d{1,12})")
NON_TEXT_REPLY = ("Thanks! I can only read text messages at the moment, so I can't open voice notes, images "
                  "or stickers. Could you type your question instead?")
INVALID_BUTTON_REPLY = "That button is no longer valid, so nothing was changed. Is there anything else I can help with?"


# ------------------------------------------------------------------ webhook
def valid_signature(raw: bytes, header: str) -> bool:
    secret = config.WHATSAPP_APP_SECRET
    if not secret:  # not configured: accept nothing
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), (header or "").strip().encode())


@router.get("/webhooks/whatsapp", include_in_schema=False)
def verify_webhook(mode: str = Query("", alias="hub.mode"), token: str = Query("", alias="hub.verify_token"),
                   challenge: str = Query("", alias="hub.challenge")):
    """Meta's subscription handshake: echo the challenge if the verify token matches."""
    expected = config.WHATSAPP_VERIFY_TOKEN
    if mode == "subscribe" and expected and hmac.compare_digest(token.encode(), expected.encode()):
        return PlainTextResponse(challenge)
    raise HTTPException(403, "Verification failed")


@router.post("/webhooks/whatsapp", include_in_schema=False)
async def receive_webhook(request: Request, background: BackgroundTasks):
    raw = await request.body()  # the signature covers these exact bytes, so verify before parsing
    if not valid_signature(raw, request.headers.get("X-Hub-Signature-256", "")):
        log.warning("Rejected WhatsApp webhook with an invalid signature")
        raise HTTPException(401, "Invalid signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Body is not JSON")
    if isinstance(payload, dict) and payload.get("object") == "whatsapp_business_account":
        background.add_task(process_payload, payload)  # answer Meta immediately; it retries slow webhooks
    return {"ok": True}


def process_payload(payload: dict) -> None:
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            phone_number_id = str((value.get("metadata") or {}).get("phone_number_id", ""))
            for status in value.get("statuses") or []:
                log.info("WhatsApp status %s for message %s to %s%s", status.get("status"), status.get("id"),
                         status.get("recipient_id"), f" errors={status['errors']}" if status.get("errors") else "")
            for message in value.get("messages") or []:
                try:
                    with SessionLocal() as db:
                        process_message(db, phone_number_id, message)
                except Exception:
                    log.exception("Failed to process WhatsApp message %s", message.get("id"))


# ------------------------------------------------------------------ inbound message
def _sent_at(message: dict) -> datetime:
    try:
        sent = datetime.fromtimestamp(int(message.get("timestamp")), timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        return now()
    return min(sent, now())


def find_customer(db: Session, business_id: int, phone: str) -> Customer | None:
    matches = db.query(Customer).filter_by(business_id=business_id, phone=phone).limit(2).all()
    if len(matches) > 1:  # never guess between two accounts
        log.warning("Phone %s is linked to several customers of business %s; treating as unlinked", phone, business_id)
        return None
    return matches[0] if matches else None


def open_conversation(db: Session, business: Business, customer: Customer | None, phone: str,
                      phone_number_id: str, create: bool = True) -> Conversation | None:
    """One open (not resolved) WhatsApp conversation per customer, or per number when unlinked."""
    q = db.query(Conversation).filter(Conversation.business_id == business.id, Conversation.channel == "whatsapp",
                                      Conversation.status != "resolved")
    if customer:
        q = q.filter(Conversation.customer_id == customer.id)
    else:
        q = q.filter(Conversation.customer_id.is_(None), Conversation.contact == phone)
    conv = q.order_by(Conversation.id.desc()).first()
    if conv is None and create:
        conv = Conversation(business_id=business.id, customer_id=customer.id if customer else None,
                            channel="whatsapp")
        db.add(conv)
    if conv is not None:
        conv.contact, conv.wa_phone_number_id = phone, phone_number_id
        db.flush()
    return conv


def customer_session(db: Session, business: Business, customer: Customer) -> CustomerSession:
    """Reuse the customer's live WhatsApp session, or issue one. Its token is never handed out."""
    sess = (db.query(CustomerSession)
            .filter(CustomerSession.customer_id == customer.id, CustomerSession.business_id == business.id,
                    CustomerSession.channel == "whatsapp", CustomerSession.revoked.is_(False),
                    CustomerSession.expires_at > now())
            .order_by(CustomerSession.id.desc()).first())
    if sess is None:
        sess = CustomerSession(token_hash=sha256(secrets.token_urlsafe(32)), customer_id=customer.id,
                               business_id=business.id, channel="whatsapp",
                               expires_at=now() + timedelta(minutes=config.SESSION_TTL_MINUTES))
        db.add(sess)
        db.flush()
    return sess


def link_hint(business: Business, phone: str) -> str:
    return (f"To check orders or make changes on WhatsApp, this number ({phone}) needs to be linked to your "
            f"{business.name} account. Sign in to {business.name}'s app or website and add it to your profile, "
            "then message us again. Until then I can answer general questions.")


def process_message(db: Session, phone_number_id: str, message: dict) -> None:
    number = db.query(WhatsAppNumber).filter_by(phone_number_id=phone_number_id).first()
    if number is None:
        log.warning("WhatsApp message for unconnected phone_number_id %s ignored", phone_number_id)
        return
    sender, msg_id, msg_type = normalise_phone(str(message.get("from", ""))), message.get("id"), message.get("type", "")
    if not sender or not msg_id:
        return

    # Meta retries webhooks: the unique message id means each message is handled once
    db.add(WhatsAppInbound(wa_message_id=str(msg_id)[:128], phone_number_id=phone_number_id, sender=sender,
                           msg_type=str(msg_type)[:24], sent_at=_sent_at(message)))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        log.info("Duplicate WhatsApp message %s ignored", msg_id)
        return

    business = db.get(Business, number.business_id)
    client = WhatsAppClient(phone_number_id)
    customer = find_customer(db, business.id, sender)

    if msg_type == "text":
        text = (message.get("text") or {}).get("body", "")
    elif msg_type == "button":  # quick-reply button on a template message
        text = (message.get("button") or {}).get("text", "")
    elif msg_type == "interactive" and (message.get("interactive") or {}).get("type") == "button_reply":
        reply_id = message["interactive"].get("button_reply", {}).get("id", "")
        return handle_button(db, business, client, customer, sender, phone_number_id, reply_id)
    elif msg_type in ("reaction", "system", "ephemeral"):
        log.info("WhatsApp %s message from %s ignored", msg_type, sender)
        return
    else:
        log.info("WhatsApp %s message from %s: asked for text instead", msg_type or "unknown", sender)
        return _send(client, sender, NON_TEXT_REPLY)

    conv = open_conversation(db, business, customer, sender, phone_number_id)
    first_contact = customer is None and not conv.messages
    session = customer_session(db, business, customer) if customer else None
    db.commit()
    try:
        response = agent.handle_message(db, business, session, text, conv.id)
    except agent.AgentError as exc:
        db.rollback()
        detail = exc.detail if exc.status == 422 else "I couldn't process that message"
        return _send(client, sender, f"Sorry — {detail[0].lower()}{detail[1:]}. Please try again.")

    reply, action = response["reply"], response["action"]
    if customer is None and (first_contact or (action and action["reason"] == policy.NO_SESSION_REASON)):
        reply += "\n\n" + link_hint(business, sender)
    if action and action["decision"] == "awaiting_confirmation" and response["status"] != "handed_off":
        pending = (db.query(ActionLog).filter_by(conversation_id=conv.id, decision="awaiting_confirmation")
                   .order_by(ActionLog.id.desc()).first())
        if pending:
            reply = reply.replace("Reply YES to confirm or NO to stop.", "Tap Confirm or Cancel below.")
            return _send(client, sender, reply, buttons=[(f"sanctio:confirm:{pending.id}", "Confirm"),
                                                          (f"sanctio:cancel:{pending.id}", "Cancel")])
    _send(client, sender, reply)


def handle_button(db: Session, business: Business, client: WhatsAppClient, customer: Customer | None,
                  sender: str, phone_number_id: str, reply_id: str) -> None:
    """A Confirm/Cancel tap. It counts only for this customer's latest pending action in their open
    WhatsApp conversation; anything else (old, forged or another customer's id) changes nothing."""
    match = BUTTON_RE.fullmatch(reply_id or "")
    pending = db.get(ActionLog, int(match.group(2))) if match else None
    current = open_conversation(db, business, customer, sender, phone_number_id, create=False) if customer else None
    latest = (db.query(ActionLog).filter_by(conversation_id=current.id, decision="awaiting_confirmation")
              .order_by(ActionLog.id.desc()).first()) if current else None
    if not (pending and latest and pending.id == latest.id):
        log.warning("Rejected WhatsApp confirmation button %r from %s", reply_id[:64], sender)
        db.add(SecurityEvent(conversation_id=current.id if current else None, event_type="invalid_confirmation_button",
                             detail=json.dumps({"button_id": reply_id[:64], "sender": sender})))
        db.commit()
        return _send(client, sender, INVALID_BUTTON_REPLY)
    # the same words the web chat uses, so the agent's existing confirm/decline logic runs unchanged
    text = "yes" if match.group(1) == "confirm" else "no"
    response = agent.handle_message(db, business, customer_session(db, business, customer), text, current.id)
    _send(client, sender, response["reply"])


def _send(client: WhatsAppClient, to: str, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
    try:
        if buttons:
            client.send_buttons(to, text, buttons)
        else:
            client.send_text(to, text)
    except WhatsAppError as exc:
        log.error("WhatsApp reply to %s failed: %s", to, exc)


# ------------------------------------------------------------------ outbound from the dashboard
def window_open(db: Session, conv: Conversation) -> bool:
    """Free-form messages are allowed only within 24 hours of the customer's last message."""
    last = (db.query(func.max(WhatsAppInbound.sent_at))
            .filter(WhatsAppInbound.sender == conv.contact,
                    WhatsAppInbound.phone_number_id == conv.wa_phone_number_id).scalar())
    return last is not None and now() - last < WINDOW


def send_to_conversation(db: Session, conv: Conversation, text: str) -> None:
    """Deliver a team member's message. Raises WhatsAppError(WINDOW_CLOSED) outside the 24-hour window."""
    if not window_open(db, conv):
        raise WhatsAppError(WINDOW_CLOSED)
    try:
        WhatsAppClient(conv.wa_phone_number_id or None).send_text(conv.contact, text)
    except WhatsAppError as exc:
        if exc.code == REENGAGEMENT_ERROR:
            raise WhatsAppError(WINDOW_CLOSED, exc.status, exc.code)
        raise


# ------------------------------------------------------------------ dashboard: connected numbers
class NumberIn(BaseModel):
    phone_number_id: str = Field(..., pattern=r"^\d{5,32}$")  # from Meta: WhatsApp Manager / API Setup
    display_phone: str = Field("", max_length=32)


def _number_view(n: WhatsAppNumber) -> dict:
    return {"id": n.id, "phone_number_id": n.phone_number_id, "display_phone": n.display_phone,
            "created_at": n.created_at}


@router.get("/api/admin/whatsapp/numbers", tags=["dashboard"])
def list_numbers(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    return [_number_view(n) for n in db.query(WhatsAppNumber).filter_by(business_id=admin.business_id)]


@router.post("/api/admin/whatsapp/numbers", tags=["dashboard"])
def connect_number(body: NumberIn, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(WhatsAppNumber).filter_by(phone_number_id=body.phone_number_id).first():
        raise HTTPException(409, "That WhatsApp number is already connected")
    number = WhatsAppNumber(business_id=admin.business_id, phone_number_id=body.phone_number_id,
                            display_phone=body.display_phone.strip())
    db.add(number)
    db.commit()
    return _number_view(number)


@router.delete("/api/admin/whatsapp/numbers/{number_id}", tags=["dashboard"])
def disconnect_number(number_id: int, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    number = db.get(WhatsAppNumber, number_id)
    if not number or number.business_id != admin.business_id:
        raise HTTPException(404, "Number not found")
    db.delete(number)
    db.commit()
    return {"ok": True}

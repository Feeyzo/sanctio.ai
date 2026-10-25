"""FastAPI application: integration API, business dashboard API and the website."""
import json
import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import agent, connectors, llm, policy
from .channels import whatsapp
from .channels.whatsapp_api import WhatsAppError, normalise_phone
from .config import LLM_PROVIDER
from .db import Base, engine, get_db
from .models import (Action, ActionLog, AdminUser, Business, Conversation, Customer, CustomerSession, Handoff,
                     KnowledgeArticle, Message, SecurityEvent, now)
from .security import (hash_password, issue_session, make_admin_token, new_api_key, new_webhook_secret,
                       require_admin, require_business, require_session, sha256, verify_password)

log = logging.getLogger("agent.main")
STATIC = Path(__file__).resolve().parent / "static"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    _wake_demo_business()
    yield


def _wake_demo_business() -> None:
    """On free hosting both services sleep when idle. When Sanctio wakes up, nudge the demo business
    awake too, so the first action call during a demo doesn't time out."""
    url = os.getenv("DEMO_BUSINESS_URL", "").rstrip("/")
    if not url:
        return

    def ping():
        try:
            httpx.get(f"{url}/health", timeout=90)
        except httpx.HTTPError as exc:
            log.info("Demo business at %s did not answer the wake-up call: %s", url, exc)
    threading.Thread(target=ping, daemon=True).start()


app = FastAPI(title="Sanctio — Secure AI Customer Service Agent API", version="2.0.0", lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json",
              description="Customer-service agent with verified action execution and sentiment-aware human handoff.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(whatsapp.router)  # before the website's catch-all route


@app.exception_handler(agent.AgentError)
async def agent_error(_, exc: agent.AgentError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail})


# ------------------------------------------------------------------ schemas
class SignupIn(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=120)
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., max_length=160)
    password: str = Field(..., min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: str
    password: str


class SessionIn(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=64)
    customer_name: str = Field("", max_length=120)
    customer_email: str = Field("", max_length=160)
    # the customer's verified mobile number, international format; links their WhatsApp messages
    customer_phone: str = Field("", max_length=32)


class ChatIn(BaseModel):
    message: str = Field(..., max_length=2000)
    conversation_id: int | None = None


class HumanReplyIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class BusinessIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    description: str = Field("", max_length=2000)


class ParamIn(BaseModel):
    name: str = Field(..., max_length=48)
    type: Literal["string", "number", "integer", "boolean"] = "string"
    description: str = Field("", max_length=200)
    required: bool = True
    pattern: str = Field("", max_length=80)


class ActionIn(BaseModel):
    name: str = Field(..., max_length=48)
    description: str = Field(..., min_length=3, max_length=500)
    url: str = Field(..., max_length=500)
    params: list[ParamIn] = Field(default_factory=list, max_length=8)
    mutates: bool = False
    risk: Literal["low", "medium", "high"] = "low"
    approval: Literal["never", "always", "over_amount"] = "never"
    approval_amount: float | None = Field(None, ge=0)
    enabled: bool = True


class ActionTestIn(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=64)
    params: dict = Field(default_factory=dict)


class ArticleIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=160)
    content: str = Field(..., min_length=5, max_length=6000)


# ------------------------------------------------------- integration API (v1)
@app.get("/api/health")
def health():
    return {"status": "ok", "llm_provider": LLM_PROVIDER}


@app.post("/api/v1/sessions", tags=["integration"])
def create_session(body: SessionIn, business: Business = Depends(require_business), db: Session = Depends(get_db)):
    """Called by the business's own backend after it has authenticated its customer."""
    external_id = body.customer_id.strip()
    phone = None
    if body.customer_phone.strip():
        phone = normalise_phone(body.customer_phone)
        if not phone:
            raise HTTPException(422, "customer_phone must be in international format, e.g. +2348030000001")
    customer = db.query(Customer).filter_by(business_id=business.id, external_id=external_id).first()
    if not customer:
        customer = Customer(business_id=business.id, external_id=external_id)
        db.add(customer)
    customer.name = body.customer_name.strip() or customer.name or ""
    customer.email = body.customer_email.strip() or customer.email or ""
    if phone and phone != customer.phone:
        # a number identifies one customer: the business's latest assertion wins
        for other in db.query(Customer).filter(Customer.business_id == business.id, Customer.phone == phone):
            log.info("Phone number moved from customer %s to %s", other.external_id, external_id)
            other.phone = ""
        customer.phone = phone
    db.flush()
    return {"session_token": issue_session(db, business.id, customer.id), "customer_id": external_id}


@app.delete("/api/v1/sessions", tags=["integration"])
def revoke_session(sess: CustomerSession = Depends(require_session), db: Session = Depends(get_db)):
    sess.revoked = True
    db.commit()
    return {"revoked": True}


@app.post("/api/v1/chat", tags=["integration"])
def chat(body: ChatIn, sess: CustomerSession = Depends(require_session), db: Session = Depends(get_db)):
    return agent.handle_message(db, db.get(Business, sess.business_id), sess, body.message, body.conversation_id)


@app.get("/api/v1/conversations/{conv_id}", tags=["integration"])
def get_conversation(conv_id: int, sess: CustomerSession = Depends(require_session), db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv or conv.customer_id != sess.customer_id:
        raise HTTPException(404, "Conversation not found")
    return {"id": conv.id, "status": conv.status,
            "messages": [{"sender": m.sender, "content": m.content, "at": m.created_at} for m in conv.messages]}


@app.get("/widget.js", include_in_schema=False)
def widget():
    return FileResponse(STATIC / "widget.js", media_type="application/javascript")


# ------------------------------------------------------- accounts
@app.post("/api/auth/signup", tags=["account"])
def signup(body: SignupIn, db: Session = Depends(get_db)):
    """Create a business and its first team member. The API key is returned once, here."""
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address")
    if db.query(AdminUser).filter_by(email=email).first():
        raise HTTPException(409, "An account with that email already exists")
    api_key = new_api_key()
    business = Business(name=body.business_name.strip(), api_key_hash=sha256(api_key), api_key_prefix=api_key[:12],
                        webhook_secret=new_webhook_secret())
    db.add(business)
    db.flush()
    admin = AdminUser(business_id=business.id, email=email, password_hash=hash_password(body.password),
                      name=body.name.strip())
    db.add(admin)
    db.commit()
    return {"token": make_admin_token(admin.id), "name": admin.name, "business": business.name, "api_key": api_key}


@app.post("/api/auth/login", tags=["account"])
def login(body: LoginIn, db: Session = Depends(get_db)):
    admin = db.query(AdminUser).filter_by(email=body.email.strip().lower()).first()
    if not admin or not verify_password(body.password, admin.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"token": make_admin_token(admin.id), "name": admin.name, "business": db.get(Business, admin.business_id).name}


# ------------------------------------------------------- dashboard: setup
def _llm_status() -> dict:
    """Which engine answers, and whether the last Gemini call worked (a bad key otherwise fails silently)."""
    s = llm.status
    return {"provider": LLM_PROVIDER, "models": llm.configured_models(), "last_call_ok": s["ok"], "last_error": s["error"],
            "seconds_ago": round(time.time() - s["at"]) if s["at"] else None}


def _business_view(b: Business) -> dict:
    return {"name": b.name, "description": b.description, "api_key_prefix": b.api_key_prefix,
            "webhook_secret": b.webhook_secret, "llm_provider": LLM_PROVIDER, "llm_status": _llm_status()}


@app.get("/api/admin/business", tags=["dashboard"])
def get_business(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    return {**_business_view(db.get(Business, admin.business_id)), "is_demo": _is_demo_admin(admin)}


def _is_demo_admin(admin: AdminUser) -> bool:
    return admin.email == os.getenv("DEMO_ADMIN_EMAIL", "demo@swiftship.test").strip().lower()


@app.post("/api/admin/demo/reset", tags=["dashboard"])
def reset_demo(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Wipe and recreate the SwiftShip demo (conversations, handoffs, logs) and reset its shipments.
    Only the demo account can do this; it replaces `python -m scripts.seed_demo` where there is no shell."""
    if not _is_demo_admin(admin):
        raise HTTPException(403, "Only the demo account can be reset")
    from scripts import seed_demo  # the seed script lives next to the app; imported here to avoid a cycle
    settings = seed_demo.Settings.from_env()
    if settings.missing():
        raise HTTPException(409, "Demo settings missing on the server: " + ", ".join(settings.missing()))
    seed_demo.seed(db, settings)
    return {"ok": True, "shipments": seed_demo.reset_demo_business(settings)}


@app.put("/api/admin/business", tags=["dashboard"])
def update_business(body: BusinessIn, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    business = db.get(Business, admin.business_id)
    business.name, business.description = body.name.strip(), body.description.strip()
    db.commit()
    return _business_view(business)


@app.post("/api/admin/llm/test", tags=["dashboard"])
def test_llm(admin: AdminUser = Depends(require_admin)):
    """Send one message to Gemini and report whether it answered (and the error if not)."""
    return llm.check()


@app.post("/api/admin/business/rotate-api-key", tags=["dashboard"])
def rotate_api_key(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Replaces the API key. The old key stops working immediately; the new one is shown once."""
    business = db.get(Business, admin.business_id)
    api_key = new_api_key()
    business.api_key_hash, business.api_key_prefix = sha256(api_key), api_key[:12]
    db.commit()
    return {"api_key": api_key}


@app.post("/api/admin/business/rotate-webhook-secret", tags=["dashboard"])
def rotate_webhook_secret(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    business = db.get(Business, admin.business_id)
    business.webhook_secret = new_webhook_secret()
    db.commit()
    return _business_view(business)


# ------------------------------------------------------- dashboard: actions
def _action_view(a: Action) -> dict:
    return {"id": a.id, "name": a.name, "description": a.description, "url": a.url, "params": json.loads(a.params),
            "mutates": a.mutates, "risk": a.risk, "approval": a.approval, "approval_amount": a.approval_amount,
            "enabled": a.enabled}


def _own_action(db: Session, admin: AdminUser, action_id: int) -> Action:
    action = db.get(Action, action_id)
    if not action or action.business_id != admin.business_id:
        raise HTTPException(404, "Action not found")
    return action


def _apply_action(db: Session, admin: AdminUser, action: Action, body: ActionIn):
    name = body.name.strip()
    if not policy.NAME_RE.match(name):
        raise HTTPException(422, "Action name must be lowercase letters, digits and underscores, e.g. track_shipment")
    clash = db.query(Action).filter_by(business_id=admin.business_id, name=name).first()
    if clash and clash.id != action.id:
        raise HTTPException(409, "You already have an action with that name")
    params = [p.model_dump() for p in body.params]
    problem = policy.validate_spec(params) or connectors.check_url(body.url.strip())
    # patterns run against customer text, so refuse the nested-quantifier shapes that can hang a regex engine
    if not problem and any(re.search(r"[)\]][+*}][+*{?]|\)[+*{]", p["pattern"]) for p in params):
        problem = "Parameter patterns may not use repeated groups"
    if not problem and body.approval != "never" and not body.mutates:
        problem = "Only data-changing actions can require approval"
    if not problem and body.approval == "over_amount" and body.approval_amount is None:
        problem = "Set the amount above which a human must approve"
    if problem:
        raise HTTPException(422, problem)
    action.name, action.description, action.url = name, body.description.strip(), body.url.strip()
    action.params, action.mutates, action.risk = json.dumps(params), body.mutates, body.risk
    action.approval, action.enabled = body.approval, body.enabled
    action.approval_amount = body.approval_amount if body.approval == "over_amount" else None
    db.commit()
    return _action_view(action)


@app.get("/api/admin/actions", tags=["dashboard"])
def list_actions(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    return [_action_view(a) for a in db.query(Action).filter_by(business_id=admin.business_id).order_by(Action.id)]


@app.post("/api/admin/actions", tags=["dashboard"])
def create_action(body: ActionIn, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(Action).filter_by(business_id=admin.business_id).count() >= 30:
        raise HTTPException(422, "Action limit reached (30)")
    action = Action(business_id=admin.business_id)
    db.add(action)
    return _apply_action(db, admin, action, body)


@app.put("/api/admin/actions/{action_id}", tags=["dashboard"])
def update_action(action_id: int, body: ActionIn, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    return _apply_action(db, admin, _own_action(db, admin, action_id), body)


@app.delete("/api/admin/actions/{action_id}", tags=["dashboard"])
def delete_action(action_id: int, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    db.delete(_own_action(db, admin, action_id))
    db.commit()
    return {"ok": True}


@app.post("/api/admin/actions/{action_id}/test", tags=["dashboard"])
def test_action(action_id: int, body: ActionTestIn, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Sends a signed request to the action's endpoint so an integration can be checked.
    Data-changing actions are only ever sent as a dry run from here."""
    action = _own_action(db, admin, action_id)
    clean, problem = policy.check_params(json.loads(action.params), body.params)
    if clean is None:
        raise HTTPException(422, problem)
    r = connectors.call_action(db.get(Business, admin.business_id), action, body.customer_id.strip(), clean,
                               dry_run=action.mutates)
    warnings = []
    if action.mutates and r.ok and not r.dry_run_echoed:
        warnings.append('The response did not include "dry_run": true. Your endpoint must not change anything '
                        "when dry_run is true, and must echo it back, or the agent will refuse to use this action.")
    if action.approval == "over_amount" and r.ok and r.amount is None:
        warnings.append('The response has no numeric "amount", so every request will be sent for human approval.')
    return {"ok": r.ok, "unreachable": r.unreachable, "error": r.error, "summary": r.summary, "amount": r.amount,
            "data": r.data, "dry_run": action.mutates, "warnings": warnings}


# ------------------------------------------------------- dashboard: knowledge base
def _own_article(db: Session, admin: AdminUser, article_id: int) -> KnowledgeArticle:
    article = db.get(KnowledgeArticle, article_id)
    if not article or article.business_id != admin.business_id:
        raise HTTPException(404, "Article not found")
    return article


@app.get("/api/admin/knowledge", tags=["dashboard"])
def list_articles(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(KnowledgeArticle).filter_by(business_id=admin.business_id).order_by(KnowledgeArticle.id)
    return [{"id": k.id, "title": k.title, "content": k.content} for k in rows]


@app.post("/api/admin/knowledge", tags=["dashboard"])
def create_article(body: ArticleIn, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(KnowledgeArticle).filter_by(business_id=admin.business_id).count() >= 30:
        raise HTTPException(422, "Article limit reached (30)")
    article = KnowledgeArticle(business_id=admin.business_id, title=body.title.strip(), content=body.content.strip())
    db.add(article)
    db.commit()
    return {"id": article.id, "title": article.title, "content": article.content}


@app.put("/api/admin/knowledge/{article_id}", tags=["dashboard"])
def update_article(article_id: int, body: ArticleIn, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    article = _own_article(db, admin, article_id)
    article.title, article.content = body.title.strip(), body.content.strip()
    db.commit()
    return {"id": article.id, "title": article.title, "content": article.content}


@app.delete("/api/admin/knowledge/{article_id}", tags=["dashboard"])
def delete_article(article_id: int, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    db.delete(_own_article(db, admin, article_id))
    db.commit()
    return {"ok": True}


@app.post("/api/admin/playground/session", tags=["dashboard"])
def playground_session(body: SessionIn, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Lets a team member chat with their own agent as one of their customers, from the dashboard."""
    return create_session(body, db.get(Business, admin.business_id), db)


# ------------------------------------------------------- dashboard: operations
@app.get("/api/admin/stats", tags=["dashboard"])
def stats(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    convs = db.query(Conversation).filter_by(business_id=admin.business_id)
    total = convs.count()
    handed = convs.filter(Conversation.status == "handed_off").count()
    ai_resolved = convs.filter(Conversation.resolved_by_ai.is_(True)).count()
    ids = [c.id for c in convs.all()]
    actions = db.query(ActionLog).filter(ActionLog.conversation_id.in_(ids)) if ids else None
    by_decision = dict(actions.with_entities(ActionLog.decision, func.count()).group_by(ActionLog.decision).all()) if ids else {}
    by_category = dict(convs.with_entities(Conversation.category, func.count()).group_by(Conversation.category).all())
    reasons: dict[str, int] = {}
    for h in db.query(Handoff).filter(Handoff.conversation_id.in_(ids)).all() if ids else []:
        for r in h.reasons.split(","):
            reasons[r] = reasons.get(r, 0) + 1
    avg_sent = db.query(func.avg(Message.sentiment)).filter(Message.conversation_id.in_(ids),
                                                            Message.sender == "customer").scalar() if ids else None
    return {
        "total_conversations": total, "active": convs.filter(Conversation.status == "active").count(),
        "handed_off": handed, "resolved": convs.filter(Conversation.status == "resolved").count(),
        "ai_resolution_rate": round(ai_resolved / total * 100, 1) if total else 0,
        "handoff_rate": round(db.query(Handoff).filter(Handoff.conversation_id.in_(ids)).count() / total * 100, 1) if total else 0,
        "open_handoffs": db.query(Handoff).filter(Handoff.conversation_id.in_(ids), Handoff.status != "resolved").count() if ids else 0,
        "pending_approvals": by_decision.get("pending_approval", 0),
        "actions_by_decision": by_decision, "conversations_by_category": by_category,
        "handoff_reasons": reasons, "average_sentiment": round(avg_sent or 0, 3),
        "security_events": db.query(SecurityEvent).filter(SecurityEvent.conversation_id.in_(ids)).count() if ids else 0,
        "actions_configured": db.query(Action).filter_by(business_id=admin.business_id).count(),
        "articles_configured": db.query(KnowledgeArticle).filter_by(business_id=admin.business_id).count(),
    }


def _customer_label(conv: Conversation) -> str:
    c = conv.customer
    if c is None:
        return f"Unlinked {conv.contact}" if conv.contact else "Unknown"
    return c.name or c.external_id


def _conv_summary(c: Conversation) -> dict:
    last = c.messages[-1].content if c.messages else ""
    return {"id": c.id, "customer": _customer_label(c), "channel": c.channel, "contact": c.contact,
            "status": c.status, "category": c.category,
            "sentiment": c.last_sentiment, "failed_attempts": c.failed_attempts, "resolved_by_ai": c.resolved_by_ai,
            "messages": len(c.messages), "last_message": last[:120], "updated_at": c.updated_at}


def _own_conversation(db: Session, admin: AdminUser, conv_id: int) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if not conv or conv.business_id != admin.business_id:
        raise HTTPException(404, "Conversation not found")
    return conv


@app.get("/api/admin/conversations", tags=["dashboard"])
def list_conversations(status: str | None = None, channel: str | None = None,
                       admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(Conversation).filter_by(business_id=admin.business_id)
    if status:
        q = q.filter_by(status=status)
    if channel:
        q = q.filter_by(channel=channel)
    return [_conv_summary(c) for c in q.order_by(Conversation.updated_at.desc()).limit(100).all()]


@app.get("/api/admin/conversations/{conv_id}", tags=["dashboard"])
def conversation_detail(conv_id: int, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    conv = _own_conversation(db, admin, conv_id)
    customer = conv.customer
    return {**_conv_summary(conv), "customer_email": customer.email if customer else "",
            "customer_id": customer.external_id if customer else "",
            "whatsapp_window_open": whatsapp.window_open(db, conv) if conv.channel == "whatsapp" else None,
            "messages": [{"id": m.id, "sender": m.sender, "content": m.content, "sentiment": m.sentiment,
                          "intent": m.intent, "confidence": m.confidence, "at": m.created_at} for m in conv.messages],
            "actions": [{"id": a.id, "action": a.action, "params": json.loads(a.params), "decision": a.decision,
                         "reason": a.reason, "summary": a.summary, "at": a.created_at}
                        for a in db.query(ActionLog).filter_by(conversation_id=conv.id).order_by(ActionLog.id)],
            "handoffs": [{"id": h.id, "reasons": h.reasons.split(","), "summary": h.summary, "status": h.status,
                          "priority": h.priority} for h in db.query(Handoff).filter_by(conversation_id=conv.id)]}


@app.post("/api/admin/conversations/{conv_id}/reply", tags=["dashboard"])
def human_reply(conv_id: int, body: HumanReplyIn, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    conv = _own_conversation(db, admin, conv_id)
    content = f"{body.message}\n— {admin.name}"
    if conv.channel == "whatsapp":
        # deliver first: a message the customer never received is not saved as sent
        try:
            whatsapp.send_to_conversation(db, conv, content)
        except WhatsAppError as exc:
            if str(exc) == whatsapp.WINDOW_CLOSED:
                raise HTTPException(409, whatsapp.WINDOW_CLOSED)
            raise HTTPException(502, f"WhatsApp delivery failed: {exc}")
    db.add(Message(conversation_id=conv.id, sender="human", content=content))
    conv.updated_at = now()
    db.commit()
    return {"ok": True}


@app.post("/api/admin/conversations/{conv_id}/resolve", tags=["dashboard"])
def resolve_conversation(conv_id: int, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    conv = _own_conversation(db, admin, conv_id)
    conv.status = "resolved"
    for h in db.query(Handoff).filter_by(conversation_id=conv.id).filter(Handoff.status != "resolved"):
        h.status = "resolved"
    db.commit()
    return {"ok": True}


@app.get("/api/admin/handoffs", tags=["dashboard"])
def list_handoffs(channel: str | None = None, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(Handoff).join(Conversation).filter(Conversation.business_id == admin.business_id)
    if channel:
        q = q.filter(Conversation.channel == channel)
    rows = (q.order_by(Handoff.status != "open", Handoff.priority != "high", Handoff.id.desc()).limit(100).all())
    return [{"id": h.id, "conversation_id": h.conversation_id, "customer": _customer_label(h.conversation),
             "channel": h.conversation.channel,
             "reasons": h.reasons.split(","), "priority": h.priority, "status": h.status,
             "assigned_to": h.assigned_to, "summary": h.summary, "created_at": h.created_at} for h in rows]


@app.post("/api/admin/handoffs/{handoff_id}/claim", tags=["dashboard"])
def claim_handoff(handoff_id: int, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    h = db.get(Handoff, handoff_id)
    if not h or h.conversation.business_id != admin.business_id:
        raise HTTPException(404, "Handoff not found")
    h.status, h.assigned_to = "claimed", admin.name
    db.commit()
    return {"ok": True}


@app.get("/api/admin/approvals", tags=["dashboard"])
def pending_approvals(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    rows = (db.query(ActionLog).join(Conversation, ActionLog.conversation_id == Conversation.id)
            .filter(Conversation.business_id == admin.business_id, ActionLog.decision == "pending_approval").all())
    return [{"id": a.id, "conversation_id": a.conversation_id, "action": a.action, "params": json.loads(a.params),
             "reason": a.reason, "summary": a.summary, "at": a.created_at} for a in rows]


@app.post("/api/admin/approvals/{action_id}/{verdict}", tags=["dashboard"])
def decide_approval(action_id: int, verdict: str, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    if verdict not in ("approve", "reject"):
        raise HTTPException(400, "Verdict must be approve or reject")
    entry = db.get(ActionLog, action_id)
    if not entry or entry.decision != "pending_approval":
        raise HTTPException(404, "No pending approval with that id")
    conv = _own_conversation(db, admin, entry.conversation_id)
    label = entry.action.replace("_", " ")
    if verdict == "reject":
        entry.decision, entry.reason = "rejected", f"Rejected by {admin.name}"
        text = f"After review, our team could not approve your {label} request."
    else:
        business = db.get(Business, admin.business_id)
        action = policy.get_action(db, business, entry.action)
        clean, problem = policy.check_params(json.loads(action.params), json.loads(entry.params)) if action else (None, "")
        if clean is None:
            raise HTTPException(409, problem or "This action is no longer available")
        # check it is still valid for this customer, then run it with the customer id from the conversation
        customer_id = conv.customer.external_id
        result = connectors.call_action(business, action, customer_id, clean, dry_run=True, conversation_id=conv.id)
        if result.ok and result.dry_run_echoed:
            result = connectors.call_action(business, action, customer_id, clean, dry_run=False, conversation_id=conv.id)
        elif result.ok:
            raise HTTPException(409, "The business endpoint did not acknowledge the dry run")
        if not result.ok:
            raise HTTPException(409, result.error)
        entry.decision, entry.reason = "approved", f"Approved by {admin.name}"
        entry.result = agent.to_json({"summary": result.summary, "data": result.data})
        text = f"Good news — your {label} request has been approved and processed."
        if result.summary:
            text += f" {result.summary}"
    content = f"{text}\n— {admin.name}"
    db.add(Message(conversation_id=conv.id, sender="human", content=content))
    db.commit()
    delivered = None
    if conv.channel == "whatsapp":  # the decision is already made; delivery is best effort
        try:
            whatsapp.send_to_conversation(db, conv, content)
            delivered = True
        except WhatsAppError as exc:
            log.warning("Approval result for conversation %s not delivered on WhatsApp: %s", conv.id, exc)
            delivered = False
    return {"ok": True, "decision": entry.decision, "whatsapp_delivered": delivered}


@app.get("/api/admin/security-events", tags=["dashboard"])
def security_events(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    rows = (db.query(SecurityEvent).join(Conversation).filter(Conversation.business_id == admin.business_id)
            .order_by(SecurityEvent.id.desc()).limit(100).all())
    return [{"id": e.id, "conversation_id": e.conversation_id, "type": e.event_type, "detail": json.loads(e.detail),
             "at": e.created_at} for e in rows]


# -------------------------------------------------------------- website
FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        return FileResponse(FRONTEND / "index.html")

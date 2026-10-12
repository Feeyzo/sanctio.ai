"""FastAPI application: integration API, admin API and the demo front-end."""
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import agent
from .config import DEMO_API_KEY, LLM_PROVIDER
from .db import SessionLocal, get_db
from .models import (ActionLog, AdminUser, Business, Conversation, Customer, CustomerSession, Handoff,
                     Message, Order, SecurityEvent, now)
from .security import (issue_session, make_admin_token, require_admin, require_business, require_session,
                       verify_password)
from .seed import init_db
from .tools import REGISTRY, to_json

DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    with SessionLocal() as db:
        init_db(db)
    yield


app = FastAPI(title="Secure AI Customer Service Agent API", version="1.0.0", lifespan=lifespan,
              description="Customer-service agent with verified action execution and sentiment-aware human handoff.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(agent.AgentError)
async def agent_error(_, exc: agent.AgentError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail})


# ------------------------------------------------------------------ schemas
class SessionIn(BaseModel):
    customer_external_id: str = Field(..., max_length=64)


class ChatIn(BaseModel):
    message: str = Field(..., max_length=2000)
    conversation_id: int | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class HumanReplyIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


# ------------------------------------------------------- integration API (v1)
@app.get("/api/health")
def health():
    return {"status": "ok", "llm_provider": LLM_PROVIDER}


@app.post("/api/v1/sessions", tags=["integration"])
def create_session(body: SessionIn, business: Business = Depends(require_business), db: Session = Depends(get_db)):
    """Called by the business's own backend after it has authenticated its customer."""
    customer = db.query(Customer).filter_by(business_id=business.id, external_id=body.customer_external_id).first()
    if not customer:
        raise HTTPException(404, "Customer not found")
    return {"session_token": issue_session(db, business.id, customer.id), "customer_name": customer.name}


@app.delete("/api/v1/sessions", tags=["integration"])
def revoke_session(sess: CustomerSession = Depends(require_session), db: Session = Depends(get_db)):
    sess.revoked = True
    db.commit()
    return {"revoked": True}


@app.post("/api/v1/chat", tags=["integration"])
def chat(body: ChatIn, business: Business = Depends(require_business),
         sess: CustomerSession = Depends(require_session), db: Session = Depends(get_db)):
    return agent.handle_message(db, business, sess, body.message, body.conversation_id)


@app.get("/api/v1/conversations/{conv_id}", tags=["integration"])
def get_conversation(conv_id: int, sess: CustomerSession = Depends(require_session), db: Session = Depends(get_db)):
    conv = db.get(Conversation, conv_id)
    if not conv or conv.customer_id != sess.customer_id:
        raise HTTPException(404, "Conversation not found")
    return {"id": conv.id, "status": conv.status,
            "messages": [{"sender": m.sender, "content": m.content, "at": m.created_at} for m in conv.messages]}


# --------------------------------------------------------------- admin API
@app.post("/api/admin/login", tags=["admin"])
def admin_login(body: LoginIn, db: Session = Depends(get_db)):
    admin = db.query(AdminUser).filter_by(email=body.email.strip().lower()).first()
    if not admin or not verify_password(body.password, admin.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"token": make_admin_token(admin.id), "name": admin.name}


@app.get("/api/admin/stats", tags=["admin"])
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
    }


def _conv_summary(c: Conversation) -> dict:
    last = c.messages[-1].content if c.messages else ""
    return {"id": c.id, "customer": c.customer.name, "status": c.status, "category": c.category,
            "sentiment": c.last_sentiment, "failed_attempts": c.failed_attempts, "resolved_by_ai": c.resolved_by_ai,
            "messages": len(c.messages), "last_message": last[:120], "updated_at": c.updated_at}


def _own_conversation(db: Session, admin: AdminUser, conv_id: int) -> Conversation:
    conv = db.get(Conversation, conv_id)
    if not conv or conv.business_id != admin.business_id:
        raise HTTPException(404, "Conversation not found")
    return conv


@app.get("/api/admin/conversations", tags=["admin"])
def list_conversations(status: str | None = None, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(Conversation).filter_by(business_id=admin.business_id)
    if status:
        q = q.filter_by(status=status)
    return [_conv_summary(c) for c in q.order_by(Conversation.updated_at.desc()).limit(100).all()]


@app.get("/api/admin/conversations/{conv_id}", tags=["admin"])
def conversation_detail(conv_id: int, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    conv = _own_conversation(db, admin, conv_id)
    return {**_conv_summary(conv), "customer_email": conv.customer.email,
            "messages": [{"id": m.id, "sender": m.sender, "content": m.content, "sentiment": m.sentiment,
                          "intent": m.intent, "confidence": m.confidence, "at": m.created_at} for m in conv.messages],
            "actions": [{"id": a.id, "action": a.action, "params": json.loads(a.params), "decision": a.decision,
                         "reason": a.reason, "at": a.created_at}
                        for a in db.query(ActionLog).filter_by(conversation_id=conv.id).order_by(ActionLog.id)],
            "handoffs": [{"id": h.id, "reasons": h.reasons.split(","), "summary": h.summary, "status": h.status,
                          "priority": h.priority} for h in db.query(Handoff).filter_by(conversation_id=conv.id)]}


@app.post("/api/admin/conversations/{conv_id}/reply", tags=["admin"])
def human_reply(conv_id: int, body: HumanReplyIn, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    conv = _own_conversation(db, admin, conv_id)
    db.add(Message(conversation_id=conv.id, sender="human", content=f"{body.message}\n— {admin.name}"))
    conv.updated_at = now()
    db.commit()
    return {"ok": True}


@app.post("/api/admin/conversations/{conv_id}/resolve", tags=["admin"])
def resolve_conversation(conv_id: int, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    conv = _own_conversation(db, admin, conv_id)
    conv.status = "resolved"
    for h in db.query(Handoff).filter_by(conversation_id=conv.id).filter(Handoff.status != "resolved"):
        h.status = "resolved"
    db.commit()
    return {"ok": True}


@app.get("/api/admin/handoffs", tags=["admin"])
def list_handoffs(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    rows = (db.query(Handoff).join(Conversation).filter(Conversation.business_id == admin.business_id)
            .order_by(Handoff.status != "open", Handoff.priority != "high", Handoff.id.desc()).limit(100).all())
    return [{"id": h.id, "conversation_id": h.conversation_id, "customer": h.conversation.customer.name,
             "reasons": h.reasons.split(","), "priority": h.priority, "status": h.status,
             "assigned_to": h.assigned_to, "summary": h.summary, "created_at": h.created_at} for h in rows]


@app.post("/api/admin/handoffs/{handoff_id}/claim", tags=["admin"])
def claim_handoff(handoff_id: int, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    h = db.get(Handoff, handoff_id)
    if not h or h.conversation.business_id != admin.business_id:
        raise HTTPException(404, "Handoff not found")
    h.status, h.assigned_to = "claimed", admin.name
    db.commit()
    return {"ok": True}


@app.get("/api/admin/approvals", tags=["admin"])
def pending_approvals(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    rows = (db.query(ActionLog).join(Conversation, ActionLog.conversation_id == Conversation.id)
            .filter(Conversation.business_id == admin.business_id, ActionLog.decision == "pending_approval").all())
    return [{"id": a.id, "conversation_id": a.conversation_id, "action": a.action, "params": json.loads(a.params),
             "reason": a.reason, "at": a.created_at} for a in rows]


@app.post("/api/admin/approvals/{action_id}/{verdict}", tags=["admin"])
def decide_approval(action_id: int, verdict: str, admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    if verdict not in ("approve", "reject"):
        raise HTTPException(400, "Verdict must be approve or reject")
    log = db.get(ActionLog, action_id)
    if not log or log.decision != "pending_approval":
        raise HTTPException(404, "No pending approval with that id")
    conv = _own_conversation(db, admin, log.conversation_id)
    params = json.loads(log.params)
    if verdict == "reject":
        log.decision, log.reason = "rejected", f"Rejected by {admin.name}"
        text = f"After review, our team could not approve the {log.action.replace('_', ' ')} for {params.get('order_ref')}."
    else:
        order = db.query(Order).filter_by(order_ref=params.get("order_ref"), customer_id=conv.customer_id).first()
        if not order:
            raise HTTPException(409, "Order no longer valid for this customer")
        kwargs = {k: v for k, v in params.items() if k != "order_ref"}
        result = REGISTRY[log.action].handler(db, conv.customer_id, order=order, **kwargs)
        log.decision, log.reason, log.result = "approved", f"Approved by {admin.name}", to_json(result)
        text = f"Good news — your {log.action.replace('_', ' ')} for {params.get('order_ref')} has been approved and processed."
    db.add(Message(conversation_id=conv.id, sender="human", content=f"{text}\n— {admin.name}"))
    db.commit()
    return {"ok": True, "decision": log.decision}


@app.get("/api/admin/security-events", tags=["admin"])
def security_events(admin: AdminUser = Depends(require_admin), db: Session = Depends(get_db)):
    rows = (db.query(SecurityEvent).join(Conversation).filter(Conversation.business_id == admin.business_id)
            .order_by(SecurityEvent.id.desc()).limit(100).all())
    return [{"id": e.id, "conversation_id": e.conversation_id, "type": e.event_type, "detail": json.loads(e.detail),
             "at": e.created_at} for e in rows]


# ------------------------------------------------------------- demo helpers
if DEMO_MODE:
    @app.get("/api/demo/customers", tags=["demo"])
    def demo_customers(db: Session = Depends(get_db)):
        return [{"external_id": c.external_id, "name": c.name,
                 "orders": [o.order_ref for o in db.query(Order).filter_by(customer_id=c.id)]}
                for c in db.query(Customer).all()]

    @app.post("/api/demo/start", tags=["demo"])
    def demo_start(body: SessionIn, db: Session = Depends(get_db)):
        """Simulates the store's backend: signs a demo customer in and returns a session."""
        biz = db.query(Business).first()
        customer = db.query(Customer).filter_by(business_id=biz.id, external_id=body.customer_external_id).first()
        if not customer:
            raise HTTPException(404, "Customer not found")
        return {"session_token": issue_session(db, biz.id, customer.id), "api_key": DEMO_API_KEY,
                "customer_name": customer.name}


# -------------------------------------------------------------- front-end
FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if FRONTEND.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        return FileResponse(FRONTEND / "index.html")

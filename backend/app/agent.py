"""Agent orchestrator: the full pipeline for one customer message.

    validate input -> screen for injection -> sentiment -> confirmation handling
    -> LLM plan -> policy check -> execute / confirm / deny -> handoff decision -> audit log
"""
import json
import re

from sqlalchemy.orm import Session

from . import handoff as handoff_engine
from . import policy, sentiment
from .config import MAX_MESSAGE_LENGTH
from .llm import get_engine
from .models import (ActionLog, Business, Conversation, CustomerSession, Handoff, Message,
                     SecurityEvent, now)
from .security import detect_injection, sanitize_output
from .tools import REGISTRY, describe_tools, to_json

CONFIRM_RE = re.compile(r"^\s*(yes|y|confirm|confirmed|proceed|go ahead|ok(ay)?,? (do it|go ahead))\b", re.IGNORECASE)
REJECT_RE = re.compile(r"^\s*(no|n|stop|don'?t|cancel that|never ?mind)\b", re.IGNORECASE)


class AgentError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


def _get_conversation(db: Session, session: CustomerSession, conversation_id: int | None) -> Conversation:
    if conversation_id:
        conv = db.get(Conversation, conversation_id)
        # a customer may only continue their own conversation
        if not conv or conv.customer_id != session.customer_id or conv.business_id != session.business_id:
            raise AgentError(404, "Conversation not found")
        if conv.status == "resolved":
            conv.status = "active"
        return conv
    conv = Conversation(business_id=session.business_id, customer_id=session.customer_id)
    db.add(conv)
    db.flush()
    return conv


def _execute(db: Session, session: CustomerSession, action: str, params: dict, order) -> dict:
    spec = REGISTRY[action]
    kwargs = {k: v for k, v in params.items() if k != "order_ref"}
    if order is not None:
        kwargs["order"] = order
    result = spec.handler(db, session.customer_id, **kwargs)
    if spec.mutates:
        session.action_count += 1
    return result


def _summary(conv: Conversation, reasons: list[str], last_action: str | None) -> str:
    msgs = [m for m in conv.messages if m.sender == "customer"][-4:]
    quoted = " | ".join(m.content[:140] for m in msgs)
    return (f"Customer: {conv.customer.name} ({conv.customer.email}). Category: {conv.category}. "
            f"Triggers: {', '.join(reasons)}. Last action: {last_action or 'none'}. "
            f"Failed attempts: {conv.failed_attempts}. Recent customer messages: {quoted}")


def handle_message(db: Session, business: Business, session: CustomerSession, text: str,
                   conversation_id: int | None = None) -> dict:
    text = (text or "").strip()
    if not text:
        raise AgentError(422, "Message cannot be empty")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise AgentError(422, f"Message longer than {MAX_MESSAGE_LENGTH} characters")

    conv = _get_conversation(db, session, conversation_id)
    score = sentiment.analyse(text)
    injections = detect_injection(text)
    customer_msg = Message(conversation_id=conv.id, sender="customer", content=text, sentiment=score)
    db.add(customer_msg)
    conv.last_sentiment = score
    if injections:
        db.add(SecurityEvent(conversation_id=conv.id, event_type="prompt_injection_suspected",
                             detail=json.dumps({"message": text[:300], "patterns": injections})))
    db.flush()

    response = {"conversation_id": conv.id, "sentiment": score, "sentiment_label": sentiment.label(score),
                "intent": None, "confidence": None, "action": None, "handoff": None, "engine": None}

    # Conversation already with a human: the AI stays out of it
    if conv.status == "handed_off":
        reply = "Your conversation is with our support team. A team member will reply here shortly."
        db.add(Message(conversation_id=conv.id, sender="agent", content=reply))
        db.commit()
        return {**response, "reply": reply, "status": conv.status}

    engine = get_engine()
    response["engine"] = engine.name
    action_info, needs_approval, last_action = None, False, None

    # ---- 1. pending confirmation from the previous turn ----
    pending = (db.query(ActionLog).filter_by(conversation_id=conv.id, decision="awaiting_confirmation")
               .order_by(ActionLog.id.desc()).first())
    reply = None
    if pending and (CONFIRM_RE.match(text) or REJECT_RE.match(text)):
        params = json.loads(pending.params)
        if REJECT_RE.match(text):
            pending.decision, pending.reason = "declined_by_customer", "Customer declined"
            reply = "Okay, I haven't made any changes. Anything else I can help with?"
            response.update(intent="decline_action", confidence=1.0)
        else:
            # re-validate: the order may have changed since the confirmation was requested
            decision = policy.validate(db, business, session, pending.action, params, bool(injections))
            if decision.status == "needs_confirmation":
                result = _execute(db, session, pending.action, params, decision.order)
                pending.decision, pending.result = "executed", to_json(result)
                reply = engine.compose(None, pending.action, "executed", result, "")
                conv.resolved_by_ai = True
            else:
                pending.decision, pending.reason = "denied", decision.reason
                reply = engine.compose(None, pending.action, "denied", None, decision.reason)
                conv.failed_attempts += 1
            response.update(intent="confirm_action", confidence=1.0)
        action_info = {"name": pending.action, "decision": pending.decision, "reason": pending.reason}
        last_action = pending.action
        plan = None
    else:
        if pending:  # customer moved on without confirming
            pending.decision, pending.reason = "expired", "Customer did not confirm"

        # ---- 2. ask the model for a plan ----
        history = [{"sender": m.sender, "content": m.content} for m in conv.messages if m.id != customer_msg.id]
        allowed = [a.strip() for a in business.allowed_actions.split(",")]
        plan = engine.plan(text, history, business.name, describe_tools(allowed))
        response.update(intent=plan.intent, confidence=plan.confidence, engine=plan.engine)
        customer_msg.intent, customer_msg.confidence = plan.intent, plan.confidence
        if plan.category != "general" or conv.category == "general":
            conv.category = plan.category
        if plan.not_resolved:
            conv.failed_attempts += 1
        if plan.resolved:
            conv.status = "resolved"
        reply = plan.reply

        # ---- 3. policy check on any requested action ----
        if plan.action and not plan.wants_human:
            last_action = plan.action
            decision = policy.validate(db, business, session, plan.action, plan.params, bool(injections))
            log = ActionLog(conversation_id=conv.id, action=plan.action, params=json.dumps(plan.params),
                            decision="", reason=decision.reason)
            db.add(log)
            order_view = None
            if decision.order is not None:
                o = decision.order
                order_view = {"order_ref": o.order_ref, "item": o.item, "amount": o.amount, "status": o.status}

            if decision.status == "allowed":
                result = _execute(db, session, plan.action, plan.params, decision.order)
                log.decision, log.result = "executed", to_json(result)
                reply = engine.compose(plan, plan.action, "executed", result, "")
            elif decision.status == "needs_confirmation":
                log.decision = "awaiting_confirmation"
                reply = engine.compose(plan, plan.action, "needs_confirmation", order_view, "")
            elif decision.status == "needs_approval":
                log.decision = "pending_approval"
                needs_approval = True
                reply = engine.compose(plan, plan.action, "needs_approval", order_view, decision.reason)
            else:
                log.decision = "denied"
                conv.failed_attempts += 1
                reply = engine.compose(plan, plan.action, "denied", None, decision.reason)
                if injections:
                    db.add(SecurityEvent(conversation_id=conv.id, event_type="action_blocked",
                                         detail=json.dumps({"action": plan.action, "reason": decision.reason})))
            action_info = {"name": plan.action, "decision": log.decision, "reason": decision.reason}
        elif plan.confidence < 0.55 and not plan.not_resolved:
            conv.failed_attempts += 1

    response["action"] = action_info

    # ---- 4. human handoff decision ----
    db.flush()
    recent = [m.sentiment for m in conv.messages if m.sender == "customer" and m.sentiment is not None]
    injection_events = db.query(SecurityEvent).filter_by(conversation_id=conv.id,
                                                         event_type="prompt_injection_suspected").count()
    decision = handoff_engine.evaluate(
        sentiment=score, recent_sentiments=recent,
        confidence=response["confidence"] if response["confidence"] is not None else 1.0,
        failed_attempts=conv.failed_attempts,
        customer_asked_for_human=bool(plan and plan.wants_human),
        needs_approval=needs_approval, repeated_injection=injection_events >= 2)
    if decision.handoff and conv.status != "resolved":
        conv.status = "handed_off"
        conv.resolved_by_ai = False
        h = Handoff(conversation_id=conv.id, reasons=",".join(decision.reasons),
                    summary=_summary(conv, decision.reasons, last_action), priority=decision.priority)
        db.add(h)
        db.flush()
        if not needs_approval:
            # keep the AI's reply only if it delivered something useful (e.g. an action result)
            useful = action_info is not None and action_info["decision"] in ("executed", "denied")
            prefix = reply + "\n\n" if useful and reply else ""
            if {"strong_negative_sentiment", "sustained_negative_sentiment"} & set(decision.reasons):
                prefix += "I'm really sorry about this experience. "
            reply = prefix + "I'm transferring you to a member of our support team, who can see this " \
                             "conversation, so you won't need to repeat yourself."
        response["handoff"] = {"id": h.id, "reasons": decision.reasons, "priority": decision.priority}
    elif plan and plan.resolved:
        conv.resolved_by_ai = True

    reply = sanitize_output(reply or "How can I help?")
    db.add(Message(conversation_id=conv.id, sender="agent", content=reply))
    conv.updated_at = now()
    db.commit()
    return {**response, "reply": reply, "status": conv.status}

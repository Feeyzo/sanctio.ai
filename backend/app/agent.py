"""Agent orchestrator: the full pipeline for one customer message.

    validate input -> screen for injection -> sentiment -> confirmation handling
    -> LLM plan -> policy check -> execute / confirm / deny -> handoff decision -> audit log
"""
import json
import re

from sqlalchemy.orm import Session

from . import connectors
from . import handoff as handoff_engine
from . import policy, sentiment
from .config import LOW_CONFIDENCE_THRESHOLD, MAX_AGENT_STEPS, MAX_MESSAGE_LENGTH
from .llm import Context, get_engine
from .models import (Action, ActionLog, Business, Conversation, CustomerSession, Handoff, KnowledgeArticle,
                     Message, SecurityEvent, now)
from .security import detect_injection, sanitize_output

CONFIRM_RE = re.compile(r"^\s*(yes|y|confirm|confirmed|proceed|go ahead|ok(ay)?,? (do it|go ahead))\b", re.IGNORECASE)
REJECT_RE = re.compile(r"^\s*(no|n|stop|don'?t|cancel that|never ?mind)\b", re.IGNORECASE)


class AgentError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


def to_json(data) -> str:
    return json.dumps(data, default=str)


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


def _context(db: Session, business: Business, conv: Conversation) -> Context:
    actions = db.query(Action).filter_by(business_id=business.id, enabled=True).order_by(Action.id).all()
    articles = db.query(KnowledgeArticle).filter_by(business_id=business.id).order_by(KnowledgeArticle.id).limit(30).all()
    return Context(
        business=business.name, description=business.description,
        actions=[{"name": a.name, "description": a.description, "params": json.loads(a.params), "mutates": a.mutates}
                 for a in actions],
        articles=[{"title": k.title, "content": k.content} for k in articles],
        state=json.loads(conv.state or "{}"))


def execute(db: Session, business: Business, session: CustomerSession, decision: policy.Decision,
            conversation_id: int) -> connectors.ActionResult:
    """Run an action the policy engine has cleared, with the customer id from the verified session."""
    result = connectors.call_action(business, decision.action, session.customer.external_id, decision.params,
                                    dry_run=False, conversation_id=conversation_id)
    if result.ok and decision.action.mutates:
        session.action_count += 1
    return result


def _record_result(log: ActionLog, result: connectors.ActionResult) -> str:
    """Store the outcome of a call on the audit log and return the outcome name."""
    if result.ok:
        log.decision, log.result = "executed", to_json({"summary": result.summary, "data": result.data})
    elif result.unreachable:
        log.decision, log.reason = "failed", result.error
    else:
        log.decision, log.reason = "denied", result.error
    return log.decision


def _summary(db: Session, conv: Conversation, reasons: list[str]) -> str:
    msgs = [m for m in conv.messages if m.sender == "customer"][-4:]
    quoted = " | ".join(m.content[:140] for m in msgs)
    logs = db.query(ActionLog).filter_by(conversation_id=conv.id).order_by(ActionLog.id.desc()).limit(4).all()
    actions = "; ".join(f"{a.action} ({a.decision})" for a in reversed(logs)) or "none"
    who = conv.customer.name or conv.customer.external_id
    return (f"Customer: {who} ({conv.customer.email or conv.customer.external_id}). Category: {conv.category}. "
            f"Triggers: {', '.join(reasons)}. Actions: {actions}. "
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
    action_info, needs_approval = None, False

    def blocked(action: str, reason: str):
        conv.failed_attempts += 1
        if injections:
            db.add(SecurityEvent(conversation_id=conv.id, event_type="action_blocked",
                                 detail=json.dumps({"action": action, "reason": reason})))

    def settle(log: ActionLog, decision: policy.Decision, confirmed: bool) -> str:
        """Apply a policy decision to an audit-log row and return the reply for it."""
        nonlocal needs_approval
        log.reason = decision.reason
        if decision.preview:
            log.summary = decision.preview.summary
        params = decision.params or json.loads(log.params)
        if decision.status == "allowed" or (decision.status == "needs_confirmation" and confirmed):
            result = execute(db, business, session, decision, conv.id)
            outcome = _record_result(log, result)
            if outcome != "executed":
                blocked(log.action, log.reason)
            elif decision.action.mutates:
                conv.resolved_by_ai = True
            return engine.compose(log.action, outcome, result, log.reason, params)
        if decision.status == "needs_confirmation":
            log.decision = "awaiting_confirmation"
            return engine.compose(log.action, "needs_confirmation", decision.preview, "", params)
        if decision.status == "needs_approval":
            log.decision = "pending_approval"
            needs_approval = True
            return engine.compose(log.action, "needs_approval", decision.preview, decision.reason, params)
        log.decision = decision.status  # denied | failed
        blocked(log.action, decision.reason)
        return engine.compose(log.action, decision.status, None, decision.reason, params)

    # ---- 1. pending confirmation from the previous turn ----
    pending = (db.query(ActionLog).filter_by(conversation_id=conv.id, decision="awaiting_confirmation")
               .order_by(ActionLog.id.desc()).first())
    plan = None
    if pending and (CONFIRM_RE.match(text) or REJECT_RE.match(text)):
        if REJECT_RE.match(text):
            pending.decision, pending.reason = "declined_by_customer", "Customer declined"
            reply = "Okay, I haven't made any changes. Anything else I can help with?"
            response.update(intent="decline_action", confidence=1.0)
        else:
            # re-validate: things may have changed since the confirmation was requested
            decision = policy.validate(db, business, session, pending.action, json.loads(pending.params),
                                       bool(injections), conv.id)
            reply = settle(pending, decision, confirmed=True)
            response.update(intent="confirm_action", confidence=1.0)
        action_info = {"name": pending.action, "decision": pending.decision, "reason": pending.reason}
    else:
        if pending:  # customer moved on without confirming
            pending.decision, pending.reason = "expired", "Customer did not confirm"

        # ---- 2. ask the model for a plan; read-only lookups feed back into it ----
        history = [{"sender": m.sender, "content": m.content} for m in conv.messages if m.id != customer_msg.id]
        ctx = _context(db, business, conv)
        steps, reply = [], None
        for _ in range(MAX_AGENT_STEPS + 1):
            plan = engine.plan(text, history, ctx, steps)
            reply = plan.reply or reply
            if not plan.action or plan.wants_human:
                break
            if any(s["action"] == plan.action and s["params"] == plan.params for s in steps) \
                    or len(steps) >= MAX_AGENT_STEPS:
                break  # the model is repeating itself; answer with what we have

            # ---- 3. policy check on the requested action ----
            decision = policy.validate(db, business, session, plan.action, plan.params, bool(injections), conv.id)
            log = ActionLog(conversation_id=conv.id, action=str(plan.action)[:48], params=to_json(plan.params),
                            decision="")
            db.add(log)
            reply = settle(log, decision, confirmed=False)
            action_info = {"name": log.action, "decision": log.decision, "reason": log.reason}
            if decision.status != "allowed" or log.decision != "executed":
                break
            result = json.loads(log.result)
            steps.append({"action": plan.action, "params": plan.params, "summary": result["summary"],
                          "result": result["data"]})

        conv.state = json.dumps(ctx.state)
        response.update(intent=plan.intent, confidence=plan.confidence, engine=plan.engine)
        customer_msg.intent, customer_msg.confidence = plan.intent, plan.confidence
        if plan.category != "general" or conv.category == "general":
            conv.category = plan.category
        if plan.not_resolved:
            conv.failed_attempts += 1
        if plan.resolved:
            conv.status = "resolved"
        if not action_info and plan.confidence < LOW_CONFIDENCE_THRESHOLD and not plan.not_resolved:
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
                    summary=_summary(db, conv, decision.reasons), priority=decision.priority)
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

"""Database models (see the ER diagram in Chapter 3)."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Business(Base):
    """An organisation that integrates the agent API (a tenant)."""
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")  # what the business does; given to the agent
    api_key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    api_key_prefix: Mapped[str] = mapped_column(String(16), default="")  # shown in the dashboard to identify the key
    webhook_secret: Mapped[str] = mapped_column(String(80))  # signs requests sent to the business's backend
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Action(Base):
    """Something the agent may do in the business's app, executed by calling the business's own endpoint."""
    __tablename__ = "actions"
    __table_args__ = (UniqueConstraint("business_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    name: Mapped[str] = mapped_column(String(48))
    description: Mapped[str] = mapped_column(Text)
    params: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of {name, type, description, required, pattern}
    url: Mapped[str] = mapped_column(String(500))
    mutates: Mapped[bool] = mapped_column(Boolean, default=False)  # changes data -> preview + customer confirmation
    risk: Mapped[str] = mapped_column(String(8), default="low")  # low|medium|high
    approval: Mapped[str] = mapped_column(String(16), default="never")  # never|always|over_amount
    approval_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class KnowledgeArticle(Base):
    """Troubleshooting guides, FAQs and policies the agent answers from."""
    __tablename__ = "knowledge_articles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    title: Mapped[str] = mapped_column(String(160))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Customer(Base):
    """A business's customer, created the first time the business opens a session for them."""
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("business_id", "external_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    external_id: Mapped[str] = mapped_column(String(64))  # customer id in the business's own system
    name: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    # E.164 (e.g. +2348030000001), set by the business when it opens a session; links WhatsApp messages
    phone: Mapped[str] = mapped_column(String(20), default="", index=True)


class CustomerSession(Base):
    """A verified customer session issued by the business backend."""
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    action_count: Mapped[int] = mapped_column(Integer, default=0)
    channel: Mapped[str] = mapped_column(String(16), default="web")  # web|whatsapp (whatsapp: issued internally)
    customer: Mapped[Customer] = relationship()


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    # empty for a WhatsApp number not linked to any customer: no session, so no actions
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), default="web")  # web|whatsapp
    contact: Mapped[str] = mapped_column(String(20), default="")  # WhatsApp: the customer's number (E.164)
    wa_phone_number_id: Mapped[str] = mapped_column(String(32), default="")  # WhatsApp: the business number used
    status: Mapped[str] = mapped_column(String(24), default="active")  # active|handed_off|resolved
    category: Mapped[str] = mapped_column(String(48), default="general")
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    resolved_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[str] = mapped_column(Text, default="{}")  # JSON scratch space for the rule-based engine
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    customer: Mapped[Customer | None] = relationship()
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    sender: Mapped[str] = mapped_column(String(16))  # customer|agent|human
    content: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(48), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ActionLog(Base):
    """Audit record of every action the AI requested and what the policy engine decided."""
    __tablename__ = "action_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    action: Mapped[str] = mapped_column(String(48))
    params: Mapped[str] = mapped_column(Text)
    # awaiting_confirmation|executed|denied|failed|pending_approval|approved|rejected|declined_by_customer|expired
    decision: Mapped[str] = mapped_column(String(24))
    summary: Mapped[str] = mapped_column(Text, default="")  # what the business said the action would do
    reason: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Handoff(Base):
    __tablename__ = "handoffs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    reasons: Mapped[str] = mapped_column(Text)  # comma-separated triggers
    summary: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(12), default="normal")  # normal|high
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|claimed|resolved
    assigned_to: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    conversation: Mapped[Conversation] = relationship()


class SecurityEvent(Base):
    __tablename__ = "security_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(48))
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    email: Mapped[str] = mapped_column(String(160), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    name: Mapped[str] = mapped_column(String(120))


class WhatsAppNumber(Base):
    """A WhatsApp Business phone number connected by a business (Meta's phone_number_id routes webhooks)."""
    __tablename__ = "whatsapp_numbers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    phone_number_id: Mapped[str] = mapped_column(String(32), unique=True)
    display_phone: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class WhatsAppInbound(Base):
    """Every inbound WhatsApp message id seen. The unique id makes Meta's webhook retries idempotent,
    and sent_at tells whether the 24-hour customer-service window is open."""
    __tablename__ = "whatsapp_inbound"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wa_message_id: Mapped[str] = mapped_column(String(128), unique=True)
    phone_number_id: Mapped[str] = mapped_column(String(32), index=True)
    sender: Mapped[str] = mapped_column(String(20), index=True)  # E.164
    msg_type: Mapped[str] = mapped_column(String(24))
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=now)

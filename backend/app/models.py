"""Database models (see the ER diagram in Chapter 3)."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Business(Base):
    """An organisation that integrates the agent API (a tenant)."""
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    api_key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    allowed_actions: Mapped[str] = mapped_column(Text)  # comma-separated allowlist
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    external_id: Mapped[str] = mapped_column(String(64))  # customer id in the business's own system
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(32), default="")


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
    customer: Mapped[Customer] = relationship()


class Order(Base):
    """Simulated business data the agent can act on."""
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_ref: Mapped[str] = mapped_column(String(32), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    item: Mapped[str] = mapped_column(String(160))
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))  # pending|processing|shipped|delivered|cancelled|refunded
    payment_status: Mapped[str] = mapped_column(String(32), default="paid")
    shipping_address: Mapped[str] = mapped_column(String(255))
    expected_delivery: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(String(24), default="active")  # active|handed_off|resolved
    category: Mapped[str] = mapped_column(String(48), default="general")
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    resolved_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sentiment: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    customer: Mapped[Customer] = relationship()
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
    decision: Mapped[str] = mapped_column(String(24))  # executed|denied|pending_approval|approved|rejected|failed
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

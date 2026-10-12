"""Deterministic policy engine.

This is the security core of the system. The language model may *propose* an
action, but only this module decides whether it runs. Identity always comes
from the verified session — never from the model or the customer's text.
"""
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .config import MAX_ACTIONS_PER_SESSION, REFUND_AUTO_LIMIT
from .models import Business, CustomerSession, Order
from .tools import REGISTRY, TROUBLESHOOTING_GUIDES

ORDER_REF = re.compile(r"^ORD-\d{4,8}$")


@dataclass
class Decision:
    status: str  # allowed | denied | needs_confirmation | needs_approval
    reason: str
    order: Order | None = None


def validate(db: Session, business: Business, session: CustomerSession, action: str, params: dict,
             injection_detected: bool = False) -> Decision:
    # 1. The action must exist and be on this business's allowlist (least privilege)
    spec = REGISTRY.get(action)
    if spec is None:
        return Decision("denied", f"Unknown action '{action}'")
    allowed = [a.strip() for a in business.allowed_actions.split(",")]
    if action not in allowed:
        return Decision("denied", f"Action '{action}' is not enabled for this business")

    # 2. Parameters must match the declared schema exactly — no extra fields such as customer_id
    if not isinstance(params, dict):
        return Decision("denied", "Parameters must be an object")
    extra = set(params) - set(spec.params)
    if extra:
        return Decision("denied", f"Unexpected parameters: {', '.join(sorted(extra))}")
    missing = set(spec.params) - set(params)
    if missing:
        return Decision("denied", f"Missing parameters: {', '.join(sorted(missing))}")
    for key, typ in spec.params.items():
        if not isinstance(params[key], typ) or len(str(params[key])) > 200:
            return Decision("denied", f"Invalid value for '{key}'")

    # 3. Suspected prompt injection blocks every data-changing action in that turn
    if injection_detected and spec.mutates:
        return Decision("denied", "Possible prompt injection detected; data-changing actions are blocked")

    # 4. Rate limit on data-changing actions per session
    if spec.mutates and session.action_count >= MAX_ACTIONS_PER_SESSION:
        return Decision("denied", "Action limit for this session reached")

    # 5. Action-specific checks
    if "issue" in spec.params and params["issue"] not in TROUBLESHOOTING_GUIDES:
        return Decision("denied", "Unsupported troubleshooting issue")

    order = None
    if "order_ref" in spec.params:
        ref = params["order_ref"].strip().upper()
        if not ORDER_REF.match(ref):
            return Decision("denied", "Invalid order reference format")
        order = db.query(Order).filter_by(order_ref=ref).first()
        # Ownership check. The same message is used for "not found" and "not yours"
        # so the agent cannot be used to discover other customers' orders.
        if order is None or order.customer_id != session.customer_id:
            return Decision("denied", "Order not found on this account")

    if action == "cancel_order" and order.status not in ("pending", "processing"):
        return Decision("denied", f"Order is already {order.status} and cannot be cancelled", order)
    if action == "update_shipping_address":
        if order.status not in ("pending", "processing"):
            return Decision("denied", f"Address cannot be changed because the order is {order.status}", order)
        if len(params["new_address"].strip()) < 10:
            return Decision("denied", "New address is too short", order)
    if action == "request_refund":
        if order.status != "delivered":
            return Decision("denied", f"Refunds apply to delivered orders only (this order is {order.status})", order)
        if order.amount > REFUND_AUTO_LIMIT:
            return Decision("needs_approval",
                            f"Refund of NGN {order.amount:,.0f} exceeds the automatic limit of "
                            f"NGN {REFUND_AUTO_LIMIT:,.0f}; a human must approve it", order)

    # 6. Data-changing actions need explicit confirmation from the customer
    if spec.mutates:
        return Decision("needs_confirmation", "Customer confirmation required", order)
    return Decision("allowed", "Read-only action permitted", order)

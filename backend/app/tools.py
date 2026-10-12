"""Simulated business API (an e-commerce order system) and the action registry.

Each action declares: its parameters, a risk level and whether it changes data.
The AI can only *request* these actions; the policy engine decides whether they run.
"""
import json
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy.orm import Session

from .models import Order


@dataclass
class ActionSpec:
    name: str
    description: str
    params: dict[str, type]
    risk: str  # low|medium|high
    mutates: bool
    handler: Callable = field(repr=False)


# ---------- handlers (the "business API") ----------
def _order_view(o: Order) -> dict:
    return {"order_ref": o.order_ref, "item": o.item, "amount": o.amount, "status": o.status,
            "payment_status": o.payment_status, "expected_delivery": o.expected_delivery,
            "shipping_address": o.shipping_address}


def list_orders(db: Session, customer_id: int) -> dict:
    orders = db.query(Order).filter_by(customer_id=customer_id).order_by(Order.id.desc()).limit(10).all()
    return {"orders": [_order_view(o) for o in orders]}


def get_order_status(db: Session, customer_id: int, order: Order) -> dict:
    return _order_view(order)


def cancel_order(db: Session, customer_id: int, order: Order) -> dict:
    order.status = "cancelled"
    order.payment_status = "refund_initiated" if order.payment_status == "paid" else order.payment_status
    db.commit()
    return {"order_ref": order.order_ref, "status": order.status, "payment_status": order.payment_status}


def request_refund(db: Session, customer_id: int, order: Order, reason: str) -> dict:
    order.status = "refunded"
    order.payment_status = "refund_initiated"
    db.commit()
    return {"order_ref": order.order_ref, "refund_amount": order.amount, "reason": reason,
            "status": "refund_initiated", "eta": "3-5 working days"}


def update_shipping_address(db: Session, customer_id: int, order: Order, new_address: str) -> dict:
    order.shipping_address = new_address
    db.commit()
    return {"order_ref": order.order_ref, "shipping_address": order.shipping_address}


TROUBLESHOOTING_GUIDES = {
    "payment_deducted_no_order": [
        "Debits without an order are usually reversed automatically by the bank within 24 hours.",
        "Check if you received an order confirmation email or SMS.",
        "If 24 hours have passed, share the transaction date and amount so we can trace it.",
    ],
    "late_delivery": [
        "Check the expected delivery date on your order.",
        "Make sure your phone is reachable — riders call before delivery.",
        "If the date has passed by more than 2 days, we can escalate to the logistics team.",
    ],
    "wrong_or_damaged_item": [
        "Do not discard the item or packaging.",
        "Take clear photos of the item and the label.",
        "You can request a refund or replacement within 7 days of delivery.",
    ],
    "login_problem": [
        "Use 'Forgot password' on the sign-in page to reset your password.",
        "Check your spam folder for the reset email.",
        "Clear your browser cache or update the app, then try again.",
    ],
}


def get_troubleshooting_steps(db: Session, customer_id: int, issue: str) -> dict:
    steps = TROUBLESHOOTING_GUIDES.get(issue)
    if not steps:
        return {"issue": issue, "steps": [], "note": "No guide available for this issue"}
    return {"issue": issue, "steps": steps}


REGISTRY: dict[str, ActionSpec] = {
    "list_orders": ActionSpec("list_orders", "List the customer's recent orders", {}, "low", False, list_orders),
    "get_order_status": ActionSpec("get_order_status", "Get status and details of one order",
                                   {"order_ref": str}, "low", False, get_order_status),
    "get_troubleshooting_steps": ActionSpec(
        "get_troubleshooting_steps",
        "Guided troubleshooting. issue one of: " + ", ".join(TROUBLESHOOTING_GUIDES),
        {"issue": str}, "low", False, get_troubleshooting_steps),
    "cancel_order": ActionSpec("cancel_order", "Cancel an order that has not shipped",
                               {"order_ref": str}, "medium", True, cancel_order),
    "update_shipping_address": ActionSpec("update_shipping_address", "Change delivery address before shipping",
                                          {"order_ref": str, "new_address": str}, "medium", True,
                                          update_shipping_address),
    "request_refund": ActionSpec("request_refund", "Refund a delivered order (wrong/damaged item)",
                                 {"order_ref": str, "reason": str}, "high", True, request_refund),
}


def describe_tools(allowed: list[str]) -> str:
    lines = []
    for name in allowed:
        spec = REGISTRY.get(name)
        if spec:
            params = ", ".join(f"{k}: string" for k in spec.params) or "none"
            lines.append(f"- {spec.name}({params}): {spec.description}")
    return "\n".join(lines)


def to_json(data) -> str:
    return json.dumps(data, default=str)

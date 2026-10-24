"""Deterministic policy engine.

This is the security core of the system. The language model may *propose* an
action, but only this module decides whether it runs. Identity always comes
from the verified session — never from the model or the customer's text.
"""
import json
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from . import connectors
from .config import MAX_ACTIONS_PER_SESSION
from .models import Action, Business, CustomerSession

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
PARAM_TYPES = ("string", "number", "integer", "boolean")
# Identity is supplied by the platform from the session, so an action may not take it as a parameter
RESERVED_PARAMS = {"customer_id", "customer", "user_id", "account_id", "dry_run"}
MAX_PARAM_LENGTH = 500


@dataclass
class Decision:
    status: str  # allowed | denied | needs_confirmation | needs_approval | failed
    reason: str
    action: Action | None = None
    params: dict | None = None  # validated, type-coerced parameters
    preview: connectors.ActionResult | None = None


def get_action(db: Session, business: Business, name: str) -> Action | None:
    return db.query(Action).filter_by(business_id=business.id, name=name, enabled=True).first()


def validate_spec(params: list) -> str | None:
    """Check a parameter schema when a business creates or edits an action."""
    seen = set()
    for p in params:
        name = p.get("name", "")
        if not NAME_RE.match(name):
            return f"Parameter name '{name}' must be lowercase letters, digits and underscores"
        if name in RESERVED_PARAMS:
            return f"'{name}' is reserved: the customer's identity always comes from the verified session"
        if name in seen:
            return f"Duplicate parameter '{name}'"
        seen.add(name)
        if p.get("type", "string") not in PARAM_TYPES:
            return f"Parameter '{name}' has an unknown type"
        if p.get("pattern"):
            try:
                re.compile(p["pattern"])
            except re.error:
                return f"Parameter '{name}' has an invalid pattern"
    return None


def _coerce(value, typ: str):
    """Return the value as the declared type, or None if it does not fit."""
    if isinstance(value, bool):
        return value if typ == "boolean" else None
    if typ == "string":
        return value.strip() if isinstance(value, str) else str(value) if isinstance(value, (int, float)) else None
    if typ == "boolean":
        return {"true": True, "false": False}.get(value.strip().lower()) if isinstance(value, str) else None
    try:
        number = float(value) if isinstance(value, (int, float, str)) else None
    except ValueError:
        return None
    if number is None or number != number or number in (float("inf"), float("-inf")):
        return None
    if typ == "integer":
        return int(number) if number == int(number) else None
    return number


def check_params(spec: list, params) -> tuple[dict | None, str]:
    """Parameters must match the declared schema exactly — no extra fields such as customer_id."""
    if not isinstance(params, dict):
        return None, "Parameters must be an object"
    declared = {p["name"]: p for p in spec}
    extra = set(params) - set(declared)
    if extra:
        return None, f"Unexpected parameters: {', '.join(sorted(extra))}"
    missing = {n for n, p in declared.items() if p.get("required", True) and n not in params}
    if missing:
        return None, f"Missing parameters: {', '.join(sorted(missing))}"
    clean = {}
    for name, value in params.items():
        p = declared[name]
        coerced = _coerce(value, p.get("type", "string"))
        if coerced is None or coerced == "" or len(str(coerced)) > MAX_PARAM_LENGTH:
            return None, f"Invalid value for '{name}'"
        if p.get("pattern") and not re.fullmatch(p["pattern"], str(coerced), re.IGNORECASE):
            return None, f"Invalid format for '{name}'"
        clean[name] = coerced
    return clean, ""


def validate(db: Session, business: Business, session: CustomerSession, action_name: str, params: dict,
             injection_detected: bool = False, conversation_id: int | None = None) -> Decision:
    # 1. The action must be one this business has registered and enabled (least privilege)
    action = get_action(db, business, action_name) if isinstance(action_name, str) else None
    if action is None:
        return Decision("denied", "That action is not available")

    # 2. Parameters must match the declared schema exactly
    clean, problem = check_params(json.loads(action.params), params)
    if clean is None:
        return Decision("denied", problem, action)

    if not action.mutates:
        return Decision("allowed", "Read-only action permitted", action, clean)

    # 3. Suspected prompt injection blocks every data-changing action in that turn
    if injection_detected:
        return Decision("denied", "Possible prompt injection detected; data-changing actions are blocked", action, clean)

    # 4. Rate limit on data-changing actions per session
    if session.action_count >= MAX_ACTIONS_PER_SESSION:
        return Decision("denied", "Action limit for this session reached", action, clean)

    # 5. Ask the business what this would do for *this* customer, without doing it. The business
    #    checks ownership and eligibility against the customer id from the verified session.
    preview = connectors.call_action(business, action, session.customer.external_id, clean, dry_run=True,
                                     conversation_id=conversation_id)
    if preview.unreachable:
        return Decision("failed", preview.error, action, clean, preview)
    if not preview.ok:
        return Decision("denied", preview.error, action, clean, preview)
    if not preview.dry_run_echoed:
        # the endpoint ignored dry_run, so it cannot be trusted to preview safely
        return Decision("failed", "The business endpoint did not acknowledge the dry run", action, clean, preview)

    # 6. Risky cases go to a human. The amount comes from the business's system, not from the chat.
    if action.approval == "always":
        return Decision("needs_approval", "This request needs to be approved by a member of the team",
                        action, clean, preview)
    if action.approval == "over_amount":
        limit = action.approval_amount or 0
        if preview.amount is None:
            return Decision("needs_approval", "The amount could not be verified, so a human must approve it",
                            action, clean, preview)
        if preview.amount > limit:
            return Decision("needs_approval", f"The amount of {preview.amount:,.0f} is above the automatic limit of "
                                              f"{limit:,.0f}, so a human must approve it", action, clean, preview)

    # 7. Data-changing actions need explicit confirmation from the customer
    return Decision("needs_confirmation", "Customer confirmation required", action, clean, preview)

"""Connector layer: runs an action by calling the business's own backend.

Every request is signed with the business's webhook secret and carries the
customer id from the verified session, so the business can enforce ownership
on its side. Data-changing actions are first sent with `dry_run: true` — the
business describes what would happen without doing it — and only executed
after the policy engine and the customer have agreed.
"""
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from .config import ALLOW_PRIVATE_WEBHOOK_URLS, WEBHOOK_TIMEOUT_SECONDS
from .models import Action, Business

log = logging.getLogger("agent.connectors")

MAX_RESPONSE_BYTES = 64_000
transport: httpx.BaseTransport | None = None  # tests replace this with an in-process fake business


@dataclass
class ActionResult:
    ok: bool
    data: dict = field(default_factory=dict)
    summary: str = ""            # human-readable description supplied by the business
    amount: float | None = None  # money involved, used for approval thresholds
    error: str = ""              # why the business refused (safe to show the customer)
    unreachable: bool = False    # the call itself failed (timeout, 5xx, bad response)
    dry_run_echoed: bool = False


def check_url(url: str) -> str | None:
    """Return an error message if `url` is not an acceptable action endpoint."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "URL is not valid"
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "URL must start with http:// or https://"
    if ALLOW_PRIVATE_WEBHOOK_URLS:
        return None
    if parsed.scheme != "https":
        return "URL must use https"
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except OSError:
        return "URL host could not be resolved"
    if any(not ipaddress.ip_address(a).is_global for a in addresses):
        return "URL must point to a public address"
    return None


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def call_action(business: Business, action: Action, customer_id: str, params: dict, dry_run: bool,
                conversation_id: int | None = None) -> ActionResult:
    problem = check_url(action.url)
    if problem:
        return ActionResult(False, error=problem, unreachable=True)
    body = json.dumps({"action": action.name, "customer_id": customer_id, "params": params, "dry_run": dry_run,
                       "conversation_id": conversation_id, "request_id": uuid.uuid4().hex}).encode()
    timestamp = str(int(time.time()))
    headers = {"Content-Type": "application/json", "User-Agent": "Sanctio-Agent/1.0",
               "X-Sanctio-Timestamp": timestamp,
               "X-Sanctio-Signature": sign(business.webhook_secret, timestamp, body)}
    try:
        with httpx.Client(transport=transport, timeout=WEBHOOK_TIMEOUT_SECONDS, follow_redirects=False) as client:
            r = client.post(action.url, content=body, headers=headers)
    except httpx.HTTPError as exc:
        log.warning("Action %s for business %s unreachable: %s", action.name, business.id, exc)
        return ActionResult(False, error="The business system could not be reached", unreachable=True)
    if r.status_code >= 500 or 300 <= r.status_code < 400 or len(r.content) > MAX_RESPONSE_BYTES:
        return ActionResult(False, error=f"The business system returned an unusable response ({r.status_code})",
                            unreachable=True)
    try:
        payload = r.json()
        if not isinstance(payload, dict):
            raise ValueError
    except ValueError:
        return ActionResult(False, error="The business system did not return a JSON object", unreachable=True)

    ok = r.status_code < 300 and payload.get("ok", True) is True
    data = payload.get("data")
    amount = payload.get("amount")
    return ActionResult(
        ok=ok,
        data=data if isinstance(data, dict) else {},
        summary=str(payload.get("summary") or "")[:500],
        amount=float(amount) if isinstance(amount, (int, float)) and not isinstance(amount, bool) else None,
        error="" if ok else str(payload.get("error") or "The request could not be completed")[:300],
        dry_run_echoed=payload.get("dry_run") is True,
    )

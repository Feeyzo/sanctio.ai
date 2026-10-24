"""Client for Meta's WhatsApp Cloud API (Graph API), plus reply formatting for WhatsApp.

    POST https://graph.facebook.com/{version}/{phone_number_id}/messages
    Authorization: Bearer {WHATSAPP_ACCESS_TOKEN}
"""
import logging
import re
import time

import httpx

from .. import config

log = logging.getLogger("agent.whatsapp")

GRAPH_URL = "https://graph.facebook.com/{version}/{phone_number_id}/messages"
MAX_TEXT = 4096          # WhatsApp text message limit
MAX_BUTTON_BODY = 1024   # interactive message body limit
MAX_BUTTON_TITLE = 20
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.5  # doubled after each failed attempt
transport: httpx.BaseTransport | None = None  # tests replace this with a fake Graph API


class WhatsAppError(Exception):
    def __init__(self, message: str, status: int | None = None, code: int | None = None):
        super().__init__(message)
        self.status, self.code = status, code


# ------------------------------------------------------------------ phone numbers
E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def normalise_phone(value: str) -> str | None:
    """Return the number in E.164 (+2348030000001), or None. WhatsApp sends wa_id as bare digits
    (2348030000001); other inputs must already be international (+234... or 00234...)."""
    digits = re.sub(r"[\s\-().]", "", value or "")
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    elif digits.isdigit():
        digits = "+" + digits
    return digits if E164_RE.match(digits) else None


# ------------------------------------------------------------------ formatting
def to_whatsapp(text: str) -> str:
    """Convert Markdown-style replies to WhatsApp formatting: *bold*, _italic_, ~strike~, no tables."""
    out = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?", stripped):
            continue  # table separator row
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            line = " — ".join(c for c in cells if c)
        heading = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if heading:
            line = f"*{heading.group(1).strip()}*"
        line = re.sub(r"^(\s*)[-*+]\s+", r"\1• ", line)  # bullets (before * is used for bold)
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"*{m.group(1) or m.group(2)}*", text)
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", text)
    return text.strip()


def split_text(text: str, limit: int = MAX_TEXT) -> list[str]:
    """Split on paragraph, line or word boundaries so each part fits in one message."""
    parts, text = [], text.strip()
    while len(text) > limit:
        window = text[:limit]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
        if cut < limit // 2:
            cut = limit  # no good boundary: hard split
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


# ------------------------------------------------------------------ client
class WhatsAppClient:
    def __init__(self, phone_number_id: str | None = None):
        self.phone_number_id = phone_number_id or config.WHATSAPP_PHONE_NUMBER_ID

    def _post(self, payload: dict) -> dict:
        # checked when sending, so a missing token loses only the reply, never the inbound message
        if not self.phone_number_id or not config.WHATSAPP_ACCESS_TOKEN:
            raise WhatsAppError("WhatsApp is not configured (access token or phone number id missing)")
        url = GRAPH_URL.format(version=config.WHATSAPP_API_VERSION, phone_number_id=self.phone_number_id)
        headers = {"Authorization": f"Bearer {config.WHATSAPP_ACCESS_TOKEN}"}
        delay, last = RETRY_BACKOFF_SECONDS, None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with httpx.Client(transport=transport, timeout=15) as client:
                    r = client.post(url, json={"messaging_product": "whatsapp", **payload}, headers=headers)
            except httpx.HTTPError as exc:
                last = WhatsAppError(f"Graph API unreachable: {exc}")
            else:
                if r.status_code < 300:
                    return r.json()
                try:
                    err = r.json().get("error", {})
                except ValueError:
                    err = {}
                last = WhatsAppError(err.get("message") or f"Graph API returned {r.status_code}",
                                     r.status_code, err.get("code"))
                if r.status_code < 500 and r.status_code != 429:
                    raise last  # 4xx is our fault (bad token, closed window...): retrying will not help
            if attempt < MAX_ATTEMPTS:
                log.warning("WhatsApp send attempt %s failed (%s); retrying in %.1fs", attempt, last, delay)
                time.sleep(delay)
                delay *= 2
        raise last

    @staticmethod
    def _to(phone: str) -> str:
        return phone.lstrip("+")

    def send_text(self, to: str, text: str) -> list[str]:
        """Send a reply (converted to WhatsApp formatting, split if long). Returns the message ids."""
        ids = []
        for part in split_text(to_whatsapp(text)):
            data = self._post({"recipient_type": "individual", "to": self._to(to), "type": "text",
                               "text": {"preview_url": False, "body": part}})
            ids += [m.get("id", "") for m in data.get("messages", [])]
        return ids

    def send_buttons(self, to: str, text: str, buttons: list[tuple[str, str]]) -> list[str]:
        """Interactive reply-button message. `buttons` is up to three (id, title) pairs."""
        body, ids = to_whatsapp(text), []
        if len(body) > MAX_BUTTON_BODY:  # too long for an interactive body: send the text first
            ids += self.send_text(to, body)
            body = "Please choose an option:"
        data = self._post({
            "recipient_type": "individual", "to": self._to(to), "type": "interactive",
            "interactive": {"type": "button", "body": {"text": body}, "action": {"buttons": [
                {"type": "reply", "reply": {"id": bid[:256], "title": title[:MAX_BUTTON_TITLE]}}
                for bid, title in buttons[:3]]}}})
        return ids + [m.get("id", "") for m in data.get("messages", [])]

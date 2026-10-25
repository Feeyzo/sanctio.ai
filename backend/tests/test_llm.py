"""Conversation quality: small talk on the rule-based engine, and the Gemini engine against a fake Gemini API."""
import json

import httpx
import pytest

from app import llm


# ---------------------------------------------------------------- rule-based engine
@pytest.mark.parametrize("text, intent", [
    ("hi", "greeting"),
    ("Hello there!", "greeting"),
    ("Good morning", "greeting"),
    ("Hi, how are you?", "small_talk"),
    ("how are you doing", "small_talk"),
    ("hey what's up", "small_talk"),
    ("Who are you?", "about_assistant"),
    ("what can you do", "about_assistant"),
    ("Are you a bot?", "about_assistant"),
    ("ok bye", "acknowledge"),
    ("what is the meaning of life", "unknown"),  # off-topic: the rule-based engine says what it can do
    ("bye", "acknowledge"),
])
def test_rule_based_small_talk(chat, text, intent):
    r = chat.say(text)
    assert r["intent"] == intent, r
    assert "not sure I understood" not in r["reply"] or intent == "unknown"


def test_greeting_followed_by_a_request_handles_the_request(chat, logistics):
    r = chat.say("Hello, please cancel SHP-1002")
    assert r["action"]["name"] == "cancel_shipment" and r["action"]["decision"] == "awaiting_confirmation"


def test_how_can_you_help_me_with_a_request_is_not_small_talk(chat, logistics):
    r = chat.say("How can you help me cancel SHP-1002")
    assert r["action"] and r["action"]["name"] == "cancel_shipment"


# ---------------------------------------------------------------- Gemini engine (fake API)
class FakeGemini:
    def __init__(self):
        self.requests, self.error, self.urls = [], None, []
        self.busy = []  # status codes to answer first, one per request (e.g. [503, 503])

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "test-gemini-key"
        assert "key=" not in str(request.url)  # never in the URL
        body = json.loads(request.content)
        self.requests.append(body)
        self.urls.append(str(request.url))
        if self.busy:
            return httpx.Response(self.busy.pop(0), json={"error": {"message": "This model is currently "
                                                                    "experiencing high demand."}})
        if self.error:
            return httpx.Response(self.error[0], json={"error": {"message": self.error[1]}})
        roles = [c["role"] for c in body["contents"]]
        assert roles[0] == "user" and all(a != b for a, b in zip(roles, roles[1:])), roles  # strict alternation
        last = body["contents"][-1]["parts"][0]["text"]
        if "responseSchema" not in body["generationConfig"]:
            return self.text("All done, your shipment has been cancelled.")
        if "<action_results>" in last:
            plan = {"intent": "track", "category": "tracking", "confidence": 0.9, "action": None,
                    "reply": "Your parcel SHP-1001 is in transit to Kano.", "wants_human": False,
                    "not_resolved": False, "resolved": False}
        elif "cancel" in last.lower():
            plan = {"intent": "cancel", "category": "cancellation", "confidence": 0.95, "action": "cancel_shipment",
                    "params": {"tracking_number": "SHP-1002"}, "reply": "", "wants_human": False,
                    "not_resolved": False, "resolved": False}
        elif "where" in last.lower():
            plan = {"intent": "track", "category": "tracking", "confidence": 0.9, "action": "track_shipment",
                    "params": {"tracking_number": "SHP-1001"}, "reply": "", "wants_human": False,
                    "not_resolved": False, "resolved": False}
        else:
            plan = {"intent": "small_talk", "category": "general", "confidence": 0.95, "action": None,
                    "reply": "I'm doing great, thanks for asking! How can I help with your shipments today?",
                    "wants_human": False, "not_resolved": False, "resolved": False}
        return self.text(json.dumps(plan))

    @staticmethod
    def text(t):
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": t}]},
                                                         "finishReason": "STOP"}]})


@pytest.fixture()
def gemini(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setattr(llm, "transport", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(llm, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(llm, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(llm, "status", {"ok": None, "error": "", "at": None})
    monkeypatch.setattr(llm, "RETRY_DELAYS", [0.0, 0.0])  # retry without waiting
    monkeypatch.setattr(llm, "GEMINI_FALLBACK_MODEL", "")
    monkeypatch.setattr(llm, "GROQ_API_KEY", "")
    return fake


class FakeGroq:
    """Groq's OpenAI-compatible API; answers with the same plans as FakeGemini."""
    def __init__(self, gemini: FakeGemini):
        self.gemini, self.requests, self.busy = gemini, [], []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-groq-key"
        body = json.loads(request.content)
        self.requests.append(body)
        if self.busy:
            return httpx.Response(self.busy.pop(0), json={"error": {"message": "Rate limit reached"}})
        msgs = body["messages"]
        assert msgs[0]["role"] == "system" and msgs[-1]["role"] == "user"
        if "response_format" in body:
            assert "Respond with ONLY a JSON object" in msgs[0]["content"]
        # ask the Gemini fake for the same answer, then reshape it the OpenAI way
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                    for m in msgs[1:]]
        config = {"responseSchema": {}} if "response_format" in body else {}
        g = FakeGemini().handler(httpx.Request("POST", "https://g.test", headers={"x-goog-api-key": "test-gemini-key"},
                                               json={"contents": contents, "generationConfig": config}))
        text = g.json()["candidates"][0]["content"]["parts"][0]["text"]
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": text}}]})


@pytest.fixture()
def groq(gemini, monkeypatch):
    fake = FakeGroq(gemini)
    route = lambda r: (fake.handler if r.url.host == "api.groq.com" else gemini.handler)(r)
    monkeypatch.setattr(llm, "transport", httpx.MockTransport(route))
    monkeypatch.setattr(llm, "GROQ_API_KEY", "test-groq-key")
    return fake


def test_gemini_handles_small_talk(chat, gemini):
    r = chat.say("Hi, how are you?")
    assert r["engine"] == "gemini" and r["reply"].startswith("I'm doing great")
    req = gemini.requests[0]
    assert "HOW TO TALK" in req["systemInstruction"]["parts"][0]["text"]
    assert req["generationConfig"] == {"thinkingConfig": {"thinkingLevel": "low"},
                                       "responseMimeType": "application/json",
                                       "responseSchema": req["generationConfig"]["responseSchema"]}
    assert "gemini-3.8-flash" in gemini.urls[0]


@pytest.mark.parametrize("model, expected", [
    ("gemini-3.8-flash", {"thinkingConfig": {"thinkingLevel": "low"}}),
    ("gemini-4-pro", {"thinkingConfig": {"thinkingLevel": "low"}}),
    ("gemini-2.5-flash", {"temperature": 0.3, "thinkingConfig": {"thinkingBudget": 0}}),
    ("gemini-2.5-pro", {"temperature": 0.3}),
])
def test_generation_config_matches_the_model(model, expected):
    assert llm.GeminiEngine.generation_config(model) == expected


def test_gemini_looks_up_then_answers(chat, gemini):
    r = chat.say("Where is my parcel?")
    assert r["engine"] == "gemini" and r["action"]["decision"] == "executed"
    assert r["reply"] == "Your parcel SHP-1001 is in transit to Kano."


def test_gemini_action_still_needs_policy_and_confirmation(chat, gemini, logistics):
    r = chat.say("Please cancel my textbooks shipment")
    assert r["action"]["decision"] == "awaiting_confirmation"
    assert logistics.shipments["SHP-1002"]["status"] == "pending_pickup"
    r = chat.say("yes")
    assert r["action"]["decision"] == "executed" and logistics.shipments["SHP-1002"]["status"] == "cancelled"
    assert r["reply"] == "All done, your shipment has been cancelled."


def test_history_with_support_team_messages_alternates(chat, gemini, client, admin):
    chat.say("Hi, how are you?")
    assert client.post(f"/api/admin/conversations/{chat.conv}/reply", json={"message": "Hello from the team"},
                       headers=admin).status_code == 200
    chat.say("thanks, how are you?")  # the fake API asserts strict user/model alternation
    texts = [p["parts"][0]["text"] for p in gemini.requests[-1]["contents"]]
    assert any("[Support team member]: Hello from the team" in t for t in texts)


def test_gemini_failure_falls_back_and_is_visible(chat, gemini, client, admin):
    gemini.error = (400, "API key not valid. Please pass a valid API key.")
    r = chat.say("Hi, how are you?")
    assert r["engine"] == "rule-based" and r["intent"] == "small_talk"  # still a sensible answer
    status = client.get("/api/admin/business", headers=admin).json()["llm_status"]
    assert status["last_call_ok"] is False and "API key not valid" in status["last_error"]
    test = client.post("/api/admin/llm/test", headers=admin).json()
    assert test["ok"] is False and "API key not valid" in test["error"]
    gemini.error = None
    test = client.post("/api/admin/llm/test", headers=admin).json()
    assert test["ok"] is True and test["reply"]


# ---- Gemini busy (503 "high demand") ----
def test_busy_gemini_is_retried(chat, gemini):
    gemini.busy = [503, 503]
    r = chat.say("Hi, how are you?")
    assert r["engine"] == "gemini" and r["reply"].startswith("I'm doing great")
    assert len(gemini.requests) == 3


def test_still_busy_uses_the_fallback_model(chat, gemini, monkeypatch):
    monkeypatch.setattr(llm, "GEMINI_FALLBACK_MODEL", "gemini-3.8-flash-lite")
    gemini.busy = [503, 429, 503]
    r = chat.say("Hi, how are you?")
    assert r["engine"] == "gemini"
    assert "gemini-3.8-flash-lite" in gemini.urls[-1] and "gemini-3.8-flash:" in gemini.urls[0]


def test_still_busy_without_fallback_uses_rule_based(chat, gemini, client, admin):
    gemini.busy = [503, 503, 503]
    r = chat.say("Hi, how are you?")
    assert r["engine"] == "rule-based" and r["intent"] == "small_talk"
    assert len(gemini.requests) == 3
    assert "503" in client.get("/api/admin/business", headers=admin).json()["llm_status"]["last_error"]


def test_bad_key_is_not_retried(chat, gemini):
    gemini.error = (400, "API key not valid.")
    chat.say("Hi, how are you?")
    assert len(gemini.requests) == 1


# ---- Groq as the backup provider ----
def test_busy_gemini_hands_over_to_groq(chat, gemini, groq):
    gemini.busy = [503, 503, 503]
    r = chat.say("Hi, how are you?")
    assert r["engine"] == "groq" and r["reply"].startswith("I'm doing great")
    assert len(gemini.requests) == 3 and len(groq.requests) == 1
    assert groq.requests[0]["model"] == "llama-3.3-70b-versatile"


def test_broken_gemini_goes_straight_to_groq(chat, gemini, groq, client, admin):
    gemini.error = (404, "This model is no longer available.")
    r = chat.say("Where is my parcel?")
    assert r["engine"] == "groq" and r["action"]["decision"] == "executed"
    assert r["reply"] == "Your parcel SHP-1001 is in transit to Kano."
    test = client.post("/api/admin/llm/test", headers=admin).json()
    assert test["ok"] is True and test["model"].startswith("groq")


def test_groq_actions_still_need_policy_and_confirmation(chat, gemini, groq, logistics, monkeypatch):
    monkeypatch.setattr(llm, "GEMINI_API_KEY", "")  # Groq only
    r = chat.say("Please cancel my textbooks shipment")
    assert r["action"]["decision"] == "awaiting_confirmation" and gemini.requests == []
    assert logistics.shipments["SHP-1002"]["status"] == "pending_pickup"
    r = chat.say("yes")
    assert r["action"]["decision"] == "executed" and logistics.shipments["SHP-1002"]["status"] == "cancelled"


def test_both_providers_down_uses_rule_based(chat, gemini, groq):
    gemini.busy, groq.busy = [503] * 3, [429] * 3
    r = chat.say("Hi, how are you?")
    assert r["engine"] == "rule-based" and r["intent"] == "small_talk"

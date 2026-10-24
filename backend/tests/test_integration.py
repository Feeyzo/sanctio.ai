"""Integration and system tests through the HTTP API, against a fake logistics backend."""
from .conftest import Chat, signup


# ---- accounts & authentication ----
def test_it01_chat_requires_a_session(client):
    assert client.post("/api/v1/chat", json={"message": "hi"}).status_code == 401
    assert client.post("/api/v1/chat", json={"message": "hi"}, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/api/v1/sessions", json={"customer_id": "C-1"}, headers={"X-API-Key": "wrong"}).status_code == 401


def test_it02_revoked_session_rejected(client, chat):
    chat.say("hi")
    client.delete("/api/v1/sessions", headers=chat.headers)
    r = client.post("/api/v1/chat", json={"message": "hi"}, headers=chat.headers)
    assert r.status_code == 401


def test_it03_signup_and_login(client):
    account = signup(client)
    assert account["api_key"].startswith("sk_live_")
    assert client.post("/api/auth/signup", json={"business_name": "Again", "name": "X", "email": "ops@swiftship.test",
                                                 "password": "Passw0rd!23"}).status_code == 409
    assert client.post("/api/auth/login", json={"email": "OPS@swiftship.test", "password": "Passw0rd!23"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "ops@swiftship.test", "password": "bad"}).status_code == 401
    business = client.get("/api/admin/business", headers={"Authorization": f"Bearer {account['token']}"}).json()
    assert "api_key" not in business and account["api_key"].startswith(business["api_key_prefix"])


# ---- answering & troubleshooting ----
def test_it04_track_shipment(chat):
    r = chat.say("Where is my shipment SHP-1001?")
    assert r["action"] == {"name": "track_shipment", "decision": "executed", "reason": "Read-only action permitted"}
    assert "in transit" in r["reply"]


def test_it05_troubleshooting_from_knowledge_base(chat):
    r = chat.say("Money was deducted from my account but no shipment was created")
    assert r["action"] is None and "24 hours" in r["reply"]


def test_it06_troubleshooting_combines_live_data_with_a_guide(chat):
    r = chat.say("My package SHP-1001 is late")
    assert r["action"]["name"] == "track_shipment"
    assert "in transit" in r["reply"] and "riders call before delivery" in r["reply"]


def test_it07_asks_for_a_missing_detail_then_acts(chat):
    r = chat.say("I want to track my package")
    assert r["action"] is None and "tracking number" in r["reply"]
    r = chat.say("SHP-1002")
    assert r["action"]["name"] == "track_shipment" and "pending pickup" in r["reply"]


def test_it08_lists_shipments(chat):
    r = chat.say("Show me my shipments")
    assert r["action"]["name"] == "list_shipments" and "SHP-1003" in r["reply"] and "SHP-2001" not in r["reply"]


# ---- verified action execution with confirmation ----
def test_it09_cancel_with_confirmation(chat, logistics):
    r = chat.say("Please cancel shipment SHP-1002")
    assert r["action"]["decision"] == "awaiting_confirmation" and "SHP-1002" in r["reply"]
    assert logistics.shipments["SHP-1002"]["status"] == "pending_pickup"  # nothing changed yet
    r = chat.say("yes")
    assert r["action"]["decision"] == "executed"
    assert logistics.shipments["SHP-1002"]["status"] == "cancelled"


def test_it10_customer_can_decline(chat, logistics):
    chat.say("cancel SHP-1002")
    r = chat.say("no")
    assert r["action"]["decision"] == "declined_by_customer"
    assert logistics.shipments["SHP-1002"]["status"] == "pending_pickup"


def test_it11_address_change(chat, logistics):
    chat.say("Change the address for SHP-1002 to 4 Murtala Mohammed Way, Kano")
    chat.say("yes")
    assert logistics.shipments["SHP-1002"]["address"] == "4 Murtala Mohammed Way, Kano"


def test_it12_small_refund_executes(chat, logistics):
    r = chat.say("I want a refund for SHP-1003")
    assert "reason" in r["reply"]
    chat.say("The package arrived damaged")
    r = chat.say("confirm")
    assert r["action"]["decision"] == "executed" and logistics.shipments["SHP-1003"]["status"] == "refunded"


def test_it13_business_rule_stops_the_action(chat, logistics):
    r = chat.say("cancel SHP-1001")  # already in transit
    assert r["action"]["decision"] == "denied" and "cannot be cancelled" in r["reply"]


# ---- human handoff ----
def test_it14_large_refund_goes_to_human_and_admin_approves(client, admin, api_key, logistics):
    c = Chat(client, api_key, "C-1003")
    r = c.say("Refund SHP-3001 because it arrived broken")
    assert r["action"]["decision"] == "pending_approval"
    assert "action_requires_human_approval" in r["handoff"]["reasons"]
    assert logistics.shipments["SHP-3001"]["status"] == "delivered"
    pending = client.get("/api/admin/approvals", headers=admin).json()
    assert len(pending) == 1 and "95,000" in pending[0]["summary"]
    assert client.post(f"/api/admin/approvals/{pending[0]['id']}/approve", headers=admin).status_code == 200
    assert logistics.shipments["SHP-3001"]["status"] == "refunded"
    assert logistics.calls[-1]["customer_id"] == "C-1003"


def test_it15_angry_customer_handed_off(chat, logistics):
    r = chat.say("This is TERRIBLE!!! You people are useless, I am so angry")
    assert r["handoff"] and "strong_negative_sentiment" in r["handoff"]["reasons"]
    assert r["status"] == "handed_off"
    # after handoff the AI no longer acts
    r = chat.say("cancel SHP-1002")
    assert r["action"] is None and logistics.shipments["SHP-1002"]["status"] == "pending_pickup"


def test_it16_explicit_human_request(chat):
    r = chat.say("I want to speak to a human")
    assert "customer_requested_human" in r["handoff"]["reasons"]


def test_it17_repeated_failure_handoff(chat):
    chat.say("My delivery is late")
    r = chat.say("That didn't help, still not working")
    assert r["handoff"] is None
    r = chat.say("Still not working, same problem")
    assert r["handoff"] and "unsuccessful_resolution" in r["handoff"]["reasons"]


def test_it18_handoff_summary_and_human_reply(client, admin, chat):
    chat.say("Where is SHP-1001?")
    chat.say("I want to speak to a human")
    h = client.get("/api/admin/handoffs", headers=admin).json()[0]
    assert "Amina Yusuf" in h["summary"] and "track_shipment (executed)" in h["summary"] and h["status"] == "open"
    client.post(f"/api/admin/conversations/{chat.conv}/reply", json={"message": "Hello, I'm on it."}, headers=admin)
    seen = client.get(f"/api/v1/conversations/{chat.conv}", headers=chat.headers).json()
    assert seen["messages"][-1]["sender"] == "human"


# ---- dashboard ----
def test_it19_dashboard_requires_login(client):
    assert client.get("/api/admin/stats").status_code == 401
    assert client.get("/api/admin/actions").status_code == 401


def test_it20_dashboard_stats(client, admin, chat):
    chat.say("Where is SHP-1001")
    chat.say("thank you")
    s = client.get("/api/admin/stats", headers=admin).json()
    assert s["total_conversations"] == 1 and s["ai_resolution_rate"] == 100.0 and s["actions_configured"] == 5


def test_it21_action_test_tool_uses_dry_run(client, admin, logistics):
    actions = {a["name"]: a for a in client.get("/api/admin/actions", headers=admin).json()}
    r = client.post(f"/api/admin/actions/{actions['cancel_shipment']['id']}/test", headers=admin,
                    json={"customer_id": "C-1001", "params": {"tracking_number": "SHP-1002"}}).json()
    assert r["ok"] and r["dry_run"] and not r["warnings"]
    assert logistics.shipments["SHP-1002"]["status"] == "pending_pickup"


def test_it22_knowledge_base_crud(client, admin, logistics):
    rows = client.get("/api/admin/knowledge", headers=admin).json()
    assert len(rows) == 3
    client.put(f"/api/admin/knowledge/{rows[0]['id']}", json={"title": "Late delivery", "content": "Call dispatch."}, headers=admin)
    client.delete(f"/api/admin/knowledge/{rows[1]['id']}", headers=admin)
    rows = client.get("/api/admin/knowledge", headers=admin).json()
    assert len(rows) == 2 and rows[0]["content"] == "Call dispatch."


def test_it23_widget_is_served(client):
    r = client.get("/widget.js")
    assert r.status_code == 200 and "Sanctio" in r.text

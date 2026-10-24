import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["GEMINI_API_KEY"] = ""
os.environ["WHATSAPP_ACCESS_TOKEN"] = "test-access-token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "100000000000001"
os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-verify-token"
os.environ["WHATSAPP_APP_SECRET"] = "test-app-secret"
os.environ["WHATSAPP_API_VERSION"] = "v23.0"

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import connectors  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

from .fake_business import ACTIONS, ARTICLES, FakeLogistics  # noqa: E402

CUSTOMERS = {"C-1001": "Amina Yusuf", "C-1002": "Chinedu Okafor", "C-1003": "Fatima Bello"}


def signup(client, business="SwiftShip Logistics", email="ops@swiftship.test"):
    r = client.post("/api/auth/signup", json={"business_name": business, "name": "Support Admin", "email": email,
                                              "password": "Passw0rd!23"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:  # lifespan creates a fresh, empty database
        yield c
    connectors.transport = None


@pytest.fixture()
def account(client):
    """A signed-up business: dashboard token plus the API key from the one-time signup response."""
    return signup(client)


@pytest.fixture()
def admin(account):
    return {"Authorization": f"Bearer {account['token']}"}


@pytest.fixture()
def api_key(account):
    return account["api_key"]


@pytest.fixture()
def logistics(client, admin):
    """The business's backend, with its actions and knowledge base registered on the platform."""
    fake = FakeLogistics()
    fake.secret = client.get("/api/admin/business", headers=admin).json()["webhook_secret"]
    connectors.transport = httpx.MockTransport(fake.handler)
    for a in ACTIONS:
        assert client.post("/api/admin/actions", json=a, headers=admin).status_code == 200
    for k in ARTICLES:
        assert client.post("/api/admin/knowledge", json=k, headers=admin).status_code == 200
    return fake


def start(client, api_key, customer_id="C-1001"):
    r = client.post("/api/v1/sessions", json={"customer_id": customer_id, "customer_name": CUSTOMERS.get(customer_id, "")},
                    headers={"X-API-Key": api_key})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['session_token']}"}


class Chat:
    def __init__(self, client, api_key, customer_id="C-1001"):
        self.client, self.headers, self.conv = client, start(client, api_key, customer_id), None

    def say(self, text):
        r = self.client.post("/api/v1/chat", json={"message": text, "conversation_id": self.conv}, headers=self.headers)
        assert r.status_code == 200, r.text
        data = r.json()
        self.conv = data["conversation_id"]
        return data


@pytest.fixture()
def chat(client, api_key, logistics):
    return Chat(client, api_key)

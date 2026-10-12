import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["GEMINI_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import ADMIN_EMAIL, ADMIN_PASSWORD, DEMO_API_KEY  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:  # lifespan re-seeds a fresh database
        yield c


@pytest.fixture()
def api_key():
    return DEMO_API_KEY


def start(client, external_id="C-1001"):
    r = client.post("/api/v1/sessions", json={"customer_external_id": external_id}, headers={"X-API-Key": DEMO_API_KEY})
    assert r.status_code == 200, r.text
    return {"X-API-Key": DEMO_API_KEY, "Authorization": f"Bearer {r.json()['session_token']}"}


class Chat:
    def __init__(self, client, external_id="C-1001"):
        self.client, self.headers, self.conv = client, start(client, external_id), None

    def say(self, text):
        r = self.client.post("/api/v1/chat", json={"message": text, "conversation_id": self.conv}, headers=self.headers)
        assert r.status_code == 200, r.text
        data = r.json()
        self.conv = data["conversation_id"]
        return data


@pytest.fixture()
def chat(client):
    return Chat(client)


@pytest.fixture()
def admin(client):
    r = client.post("/api/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['token']}"}

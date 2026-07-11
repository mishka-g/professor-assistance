import os

os.environ["MODEL_BACKEND"] = "mock"

from fastapi.testclient import TestClient

from professor_assistant.api import app

client = TestClient(app)


def test_status_ok():
    r = client.get("/api/status")
    assert r.status_code == 200
    assert r.json()["backend"] == "mock"

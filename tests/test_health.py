from fastapi.testclient import TestClient

from app.main import app


def test_healthz():
    with TestClient(app) as client:
        response = client.get("/status")
    assert response.status_code == 200
    assert response.text == "ok"

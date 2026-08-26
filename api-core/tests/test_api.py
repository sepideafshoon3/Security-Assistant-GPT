from fastapi.testclient import TestClient
from src.api.http import app

client = TestClient(app)


def test_health_like_behavior():
    # No explicit /health route, just ensure root exists or 404 is graceful
    response = client.get("/")
    assert response.status_code in (404, 200)

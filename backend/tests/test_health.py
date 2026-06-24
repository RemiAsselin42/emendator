from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["profile"]


def test_runner_docker_status() -> None:
    # The daemon may or may not be up in CI, so only the shape is asserted.
    res = client.get("/runner/docker")
    assert res.status_code == 200
    assert isinstance(res.json()["available"], bool)

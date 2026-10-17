import importlib
import time

import pytest
from fastapi.testclient import TestClient

from conftest import SCHOLARS_MATE, needs_stockfish

pytestmark = needs_stockfish


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SECOND_LLM_BACKEND", "none")
    monkeypatch.setenv("SECOND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECOND_ENGINE_DEPTH", "8")
    import second.web

    web = importlib.reload(second.web)
    return TestClient(web.app)


def test_home_and_status(client):
    assert "Review the games" in client.get("/").text
    status = client.get("/api/status").json()
    assert status["stockfish"] is True
    assert client.get("/healthz").json()["ok"] is True


def test_review_flow(client):
    response = client.post(
        "/review",
        data={"source": "pgn", "pgn_text": SCHOLARS_MATE, "student_name": "Riya", "student_color": "auto"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    job_id = response.headers["location"].rsplit("/", 1)[-1]
    deadline = time.time() + 60
    state = {}
    while time.time() < deadline:
        state = client.get(f"/api/jobs/{job_id}").json()
        if state["status"] in ("done", "error"):
            break
        time.sleep(0.3)
    assert state["status"] == "done", state
    review_id = state["review_ids"][0]
    page = client.get(f"/reviews/{review_id}").text
    assert "Riya lost the game" in page
    assert "Note for parents" in page
    pgn = client.get(f"/reviews/{review_id}/pgn")
    assert pgn.status_code == 200 and "$4" in pgn.text
    assert "Riya" in client.get("/reviews").text


def test_unknown_side_is_a_friendly_error(client):
    response = client.post("/review", data={"source": "pgn", "pgn_text": SCHOLARS_MATE, "student_name": "Nobody"})
    job_id = response.url.path.rsplit("/", 1)[-1]
    deadline = time.time() + 60
    state = {}
    while time.time() < deadline:
        state = client.get(f"/api/jobs/{job_id}").json()
        if state["status"] in ("done", "error"):
            break
        time.sleep(0.3)
    assert state["status"] == "error"
    assert "Choose White or Black" in state["message"]

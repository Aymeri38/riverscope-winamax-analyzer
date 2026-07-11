from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.api import AnalyzerSettings
from app.services.importer import import_pair
from app.services.settings import save_settings


FIXTURES = Path(__file__).parents[2] / "fixtures"


def test_empty_database_dashboard_and_health() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["host_policy"] == "loopback-only"
        assert health.json()["process_guard"] == {
            "enabled": True,
            "blocked": False,
            "reason": None,
        }
        import_status = client.get("/api/import/status")
        assert import_status.status_code == 200
        assert import_status.json()["watcher_running"] is False
        response = client.get("/api/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["games"] == 0
        assert data["summary"]["hands"] == 0
        assert data["summary"]["roi"] is None
        assert data["ev_curve"] == []


def test_local_http_security_headers_and_browser_origin_guard(db) -> None:
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]

        rejected = client.post(
            "/api/import/rescan",
            headers={"Origin": "https://malicious.example"},
        )
        assert rejected.status_code == 403
        assert rejected.headers["x-frame-options"] == "DENY"

        fetch_metadata_rejected = client.post(
            "/api/import/rescan",
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert fetch_metadata_rejected.status_code == 403

        allowed = client.post(
            "/api/import/rescan",
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        assert allowed.status_code == 200


def test_dashboard_tournaments_hands_sessions_and_replayer(db) -> None:
    settings = AnalyzerSettings(history_paths=[], hero_name="HERO")
    save_settings(db, settings)
    result = import_pair(
        db,
        FIXTURES / "expresso_synthetic_hands.txt",
        FIXTURES / "expresso_synthetic_summary.txt",
        settings,
        datetime(2030, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert result == "imported"
    with TestClient(app) as client:
        dashboard = client.get("/api/dashboard").json()
        assert dashboard["summary"]["games"] == 1
        assert dashboard["summary"]["hands"] == 8
        assert dashboard["summary"]["roi"] == 100
        tournaments = client.get("/api/tournaments").json()
        assert tournaments["total"] == 1
        hands = client.get("/api/hands?all_in=true").json()
        assert hands["total"] >= 1
        all_hands = client.get("/api/hands").json()
        hand_id = all_hands["items"][0]["id"]
        replay = client.get(f"/api/hands/{hand_id}/replay")
        assert replay.status_code == 200
        assert replay.json()["post_session_only"] is True
        assert all(player["name"] == "HERO" or player["name"].startswith("VILLAIN_") for player in replay.json()["players"])
        sessions = client.get("/api/sessions").json()
        assert sessions["total"] == 1
        leaks = client.get("/api/leaks")
        assert leaks.status_code == 200
        assert "items" in leaks.json()

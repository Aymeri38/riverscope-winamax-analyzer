from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.core.community_secret import (
    CommunitySecretError,
    CommunitySecrets,
    DpapiCommunitySecretStore,
    MemoryCommunitySecretStore,
)
from app.core.process_guard import AnalysisInterlock
from app.main import app
from app.database.session import Base
from app.models import (
    CommunityOpponentSyncRecord,
    CommunitySyncRecord,
    Player,
    Setting,
    Tournament,
)
from app.schemas.api import AnalyzerSettings
from app.schemas.community import (
    CommunityConsentRequest,
    CommunityJoinRequest,
    CommunityLocalConfig,
    CommunitySyncResponse,
)
from app.services.community_client import (
    CommunityAlreadyConfiguredError,
    CommunityConfigurationError,
    CommunityClient,
    CommunityPendingError,
    CommunityRemoteError,
    serialize_completed_tournament,
    serialize_tournament_opponents,
    sync_community_after_rescan,
)
import app.services.community_client as community_client_module
from app.services.importer import import_pair
from app.services.settings import load_community_config, save_community_config, save_settings


FIXTURES = Path(__file__).parents[2] / "fixtures"
CLIENT_SECRET = b"synthetic-client-secret-for-tests"


def _import_completed(db) -> Tournament:
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
    tournament = db.scalar(select(Tournament))
    assert tournament is not None
    return tournament


def _configured_client(db, handler) -> tuple[CommunityClient, MemoryCommunitySecretStore]:
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))
    store = MemoryCommunitySecretStore()
    store.save(CommunitySecrets(access_token="DEVICE_TOKEN_CANARY", client_secret=CLIENT_SECRET))
    save_community_config(
        db,
        CommunityLocalConfig(
            enabled=True,
            hub_url="https://community.example.test",
            consent_version="1",
            enrolled_at=datetime(2026, 7, 11),
            last_contact_at=datetime(2026, 7, 11),
        ),
    )
    return CommunityClient(secret_store=store, transport=httpx.MockTransport(handler)), store


@pytest.mark.parametrize(
    ("url", "valid"),
    [
        ("https://hub.example.test", True),
        ("http://127.0.0.1:9000", True),
        ("http://localhost:9000/base/", True),
        ("http://[::1]:9000", True),
        ("http://hub.example.test", False),
        ("ftp://hub.example.test", False),
        ("https://user:secret@hub.example.test", False),
        ("https://hub.example.test/?token=secret", False),
    ],
)
def test_join_url_is_https_except_loopback(url: str, valid: bool) -> None:
    values = {
        "hub_url": url,
        "invite": "INVITE_" + "x" * 32,
        "display_name": "Alice",
        "consent": True,
        "consent_version": "1",
    }
    if valid:
        CommunityJoinRequest.model_validate(values)
    else:
        with pytest.raises(ValidationError):
            CommunityJoinRequest.model_validate(values)


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_dpapi_secret_store_roundtrip_is_encrypted_at_rest(tmp_path) -> None:
    path = tmp_path / "secrets" / "community.dpapi"
    store = DpapiCommunitySecretStore(path)
    value = CommunitySecrets(
        access_token="DPAPI_TOKEN_CANARY_NEVER_PLAINTEXT",
        client_secret=b"DPAPI_CLIENT_SECRET_CANARY_123456",
    )
    store.save(value)
    ciphertext = path.read_bytes()
    assert value.access_token.encode() not in ciphertext
    assert value.client_secret not in ciphertext
    assert store.load() == value
    store.delete()
    assert not path.exists()


def test_completed_serializer_is_strict_allowlist_and_removes_canaries(db) -> None:
    tournament = _import_completed(db)
    tournament.external_id = "RAW_TOURNAMENT_ID_CANARY"
    tournament.name = "HERO_NAME_CANARY"
    tournament.hero_name = "HERO_NAME_CANARY"
    tournament.source_path = r"C:\Users\Private\history\PATH_CANARY.txt"
    tournament.ticket = "TICKET_CANARY"
    tournament.notes = "FREE_TEXT_NOTE_CANARY"
    tournament.tags_json = '["TAG_CANARY"]'
    for player_entry in tournament.players:
        player_entry.player.display_name = "PLAYER_NAME_CANARY"
        player_entry.player.name_key = f"PLAYER_HASH_CANARY_{player_entry.player.id}"
    for import_file in tournament.import_files:
        import_file.path = rf"C:\Private\IMPORT_PATH_CANARY_{import_file.id}.txt"
        import_file.file_hash = "FILE_HASH_CANARY"
    raw_hand_number = 987654321
    for hand in tournament.hands:
        hand.external_id = f"RAW_HAND_ID_CANARY_{hand.id}"
        hand.hand_number = raw_hand_number
        raw_hand_number += 1
        hand.notes = "HAND_NOTE_CANARY"
        hand.tags_json = '["HAND_TAG_CANARY"]'
        hand.action_text = "ACTION_TEXT_CANARY"
    db.commit()

    payload = serialize_completed_tournament(tournament, CLIENT_SECRET)
    encoded = payload.model_dump_json(exclude_none=True)
    decoded = json.loads(encoded)

    for canary in (
        "RAW_TOURNAMENT_ID_CANARY",
        "RAW_HAND_ID_CANARY",
        "987654321",
        "HERO_NAME_CANARY",
        "PLAYER_NAME_CANARY",
        "PLAYER_HASH_CANARY",
        "PATH_CANARY",
        "IMPORT_PATH_CANARY",
        "FILE_HASH_CANARY",
        "TICKET_CANARY",
        "FREE_TEXT_NOTE_CANARY",
        "TAG_CANARY",
        "HAND_NOTE_CANARY",
        "HAND_TAG_CANARY",
        "ACTION_TEXT_CANARY",
    ):
        assert canary not in encoded

    assert set(decoded) == {"schema_version", "client_key", "tournament"}
    assert set(decoded["tournament"]) == {
        "started_at",
        "ended_at",
        "format",
        "is_nitro",
        "currency",
        "total_buyin",
        "multiplier",
        "prize_pool",
        "reward",
        "final_rank",
        "duration_seconds",
        "total_hands",
        "registered_players",
        "initial_stack",
        "final_stack",
        "chip_delta",
        "hands",
    }
    assert len(decoded["client_key"]) == 64
    assert [hand["hand_number"] for hand in decoded["tournament"]["hands"]] == list(
        range(1, len(tournament.hands) + 1)
    )
    assert decoded["tournament"]["started_at"].endswith("Z")
    assert decoded["tournament"]["started_at"] == tournament.started_at.replace(
        tzinfo=UTC
    ).isoformat().replace("+00:00", "Z")
    for hand in decoded["tournament"]["hands"]:
        assert set(hand) == {
            "hand_number",
            "played_at",
            "level",
            "small_blind",
            "big_blind",
            "ante",
            "button_seat",
            "max_players",
            "active_players",
            "total_pot",
            "hero_net",
            "is_all_in",
            "reached_showdown",
            "hero_cards",
            "board",
            "players",
            "actions",
        }
        assert hand["played_at"].endswith("Z")
        assert all(
            player["alias"] == "HERO" or player["alias"].startswith("OPPONENT_")
            for player in hand["players"]
        )
        assert all(player["position"] in {"BTN", "SB", "BB", "UTG", "CO", "MP", "UNKNOWN"} for player in hand["players"])
        assert all(action["sequence"] == index for index, action in enumerate(hand["actions"], 1))
        assert all(
            action["action_type"]
            in {
                "POST_SB",
                "POST_BB",
                "POST_ANTE",
                "FOLD",
                "CHECK",
                "CALL",
                "BET",
                "RAISE",
                "ALL_IN",
                "COLLECT",
                "SHOW",
                "MUCK",
                "UNCALLED_RETURN",
            }
            for action in hand["actions"]
        )


def test_sync_is_idempotent_and_uses_bearer_without_raw_ids(db) -> None:
    tournament = _import_completed(db)
    raw_external_id = tournament.external_id
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer DEVICE_TOKEN_CANARY"
        if request.method == "GET":
            assert request.url.path == "/v1/me"
            return httpx.Response(
                200,
                json={
                    "member_id": "member-1",
                    "display_name": "Alice",
                    "has_contribution": True,
                },
            )
        assert request.url.path == "/v1/sync/tournaments"
        assert raw_external_id.encode() not in request.content
        return httpx.Response(
            201,
            json={"status": "created", "public_id": "public-tournament-1", "hand_count": 8},
        )

    client, _store = _configured_client(db, handler)
    first = client.sync(db)
    second = client.sync(db)

    assert first.synced == 1
    assert first.pending == 0
    assert first.available is True
    assert second.synced == 0
    assert second.pending == 0
    assert len([request for request in requests if request.method == "POST"]) == 1
    record = db.scalar(select(CommunitySyncRecord))
    assert record is not None
    assert record.state == "synced"
    assert record.remote_public_id == "public-tournament-1"


def test_offline_sync_keeps_pending_queue_and_blocks_shared_views(db) -> None:
    _import_completed(db)

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic offline", request=request)

    client, _store = _configured_client(db, offline)
    result = client.sync(db)
    assert result.online is False
    assert result.available is False
    assert result.pending == 1
    assert result.error_code == "hub_offline"
    with pytest.raises(CommunityPendingError):
        client.proxy_get(db, "/v1/contributors")
    public_status = client.status(db).model_dump(mode="json")
    serialized = json.dumps(public_status)
    assert public_status["blocked_reason"] == "pending_sync"
    assert "community.example.test" not in serialized
    assert "DEVICE_TOKEN_CANARY" not in serialized


def test_remote_contribution_probe_requires_a_strict_boolean(db) -> None:
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))

    def invalid_me(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/me"
        return httpx.Response(
            200,
            json={
                "member_id": "member-1",
                "display_name": "Alice",
                "has_contribution": "yes",
            },
        )

    client, _store = _configured_client(db, invalid_me)
    result = client.sync(db)
    assert result.available is False
    assert result.error_code == "invalid_me_response"
    assert client.status(db).available is False


def test_status_does_not_reserialize_synced_history(db, monkeypatch) -> None:
    _import_completed(db)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(
            201,
            json={"status": "created", "public_id": "public-1", "hand_count": 8},
        )

    client, _store = _configured_client(db, handler)
    assert client.sync(db).synced == 1

    def forbidden_serializer(*_args, **_kwargs):
        raise AssertionError("synced tournaments must not be loaded/serialized by status polling")

    monkeypatch.setattr(
        community_client_module,
        "serialize_completed_tournament",
        forbidden_serializer,
    )
    status_result = client.status(db)
    assert status_result.available is True


def test_join_refuses_to_overwrite_existing_dpapi_pairing(db) -> None:
    def unexpected_network(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("re-pairing must fail before network access")

    client, store = _configured_client(db, unexpected_network)
    original = store.load()
    with pytest.raises(CommunityAlreadyConfiguredError):
        client.join(
            db,
            CommunityJoinRequest(
                hub_url="https://new-hub.example.test",
                invite="wxa_inv_" + "x" * 40,
                display_name="Alice",
                consent=True,
                consent_version="1",
            ),
        )
    assert store.load() == original


def test_enrollment_response_is_streamed_through_hard_size_cap(db) -> None:
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))

    def oversized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            headers={"Content-Length": "4096"},
            content=b"x" * 4096,
        )

    store = MemoryCommunitySecretStore()
    client = CommunityClient(
        secret_store=store,
        transport=httpx.MockTransport(oversized),
        max_response_bytes=1024,
    )
    with pytest.raises(CommunityRemoteError, match="response_too_large"):
        client.join(
            db,
            CommunityJoinRequest(
                hub_url="https://hub.example.test",
                invite="wxa_inv_" + "x" * 40,
                display_name="Alice",
                consent=True,
                consent_version="1",
            ),
        )
    assert store.load() is None


def test_response_has_a_total_deadline_in_addition_to_per_read_timeout(db) -> None:
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))
    ticks = iter((0.0, 31.0))

    def enrollment(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={})

    client = CommunityClient(
        secret_store=MemoryCommunitySecretStore(),
        transport=httpx.MockTransport(enrollment),
        total_response_timeout_seconds=30,
        clock=lambda: next(ticks),
    )
    with pytest.raises(CommunityRemoteError, match="response_deadline_exceeded"):
        client.join(
            db,
            CommunityJoinRequest(
                hub_url="https://hub.example.test",
                invite="wxa_inv_" + "x" * 40,
                display_name="Alice",
                consent=True,
                consent_version="1",
            ),
        )


def test_explicit_private_ca_path_is_required_to_exist(db, tmp_path) -> None:
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))
    client = CommunityClient(
        secret_store=MemoryCommunitySecretStore(),
        ca_cert_path=tmp_path / "missing-ca.pem",
    )
    with pytest.raises(CommunityConfigurationError, match="community_ca_not_found"):
        client.join(
            db,
            CommunityJoinRequest(
                hub_url="https://hub.example.test",
                invite="wxa_inv_" + "x" * 40,
                display_name="Alice",
                consent=True,
                consent_version="1",
            ),
        )


@pytest.mark.parametrize("online", [True, False])
def test_leave_always_deletes_local_secret_and_reports_remote_revoke(db, online: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/v1/device"
        if not online:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(204)

    client, store = _configured_client(db, handler)
    assert client.leave(db) is online
    assert store.load() is None
    assert client.status(db).configured is False


def test_corrupt_local_secret_is_a_sanitized_no_store_503(db) -> None:
    class BrokenStore(MemoryCommunitySecretStore):
        def load(self):
            raise CommunitySecretError("SECRET_BLOB_CANARY")

    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))
    original = app.state.community_client
    app.state.community_client = CommunityClient(secret_store=BrokenStore())
    try:
        with TestClient(app) as client:
            response = client.get("/api/community/status")
    finally:
        app.state.community_client = original
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert "SECRET_BLOB_CANARY" not in response.text


def test_leave_force_forgets_corrupt_dpapi_blob(db) -> None:
    class RecoverableBrokenStore(MemoryCommunitySecretStore):
        deleted = False

        def load(self):
            if not self.deleted:
                raise CommunitySecretError("corrupt")
            return None

        def delete(self) -> None:
            self.deleted = True

    store = RecoverableBrokenStore()
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))
    save_community_config(
        db,
        CommunityLocalConfig(enabled=True, hub_url="https://hub.example.test", consent_version="1"),
    )
    client = CommunityClient(secret_store=store)
    assert client.leave(db) is False
    assert store.deleted is True
    assert client.status(db).configured is False


def test_leave_force_forgets_when_private_ca_configuration_is_broken(db, tmp_path) -> None:
    store = MemoryCommunitySecretStore()
    store.save(CommunitySecrets("DEVICE", CLIENT_SECRET))
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))
    save_community_config(
        db,
        CommunityLocalConfig(enabled=True, hub_url="https://hub.example.test", consent_version="1"),
    )
    client = CommunityClient(
        secret_store=store,
        ca_cert_path=tmp_path / "missing-ca.pem",
    )
    assert client.leave(db) is False
    assert store.load() is None
    assert client.status(db).configured is False


def test_community_cli_monitor_wraps_the_entire_command(monkeypatch) -> None:
    import app.community_cli as community_cli

    events: list[str] = []

    class FakeMonitor:
        def start(self) -> None:
            events.append("monitor_started")

        def stop(self) -> None:
            events.append("monitor_stopped")

    monkeypatch.setattr(community_cli, "require_winamax_absent", lambda: events.append("preflight"))
    monkeypatch.setattr(community_cli, "ProcessGuardMonitor", FakeMonitor)
    monkeypatch.setattr(
        community_cli,
        "_run_command",
        lambda _args: events.append("command") or 0,
    )
    assert community_cli.main(["status"]) == 0
    assert events == ["preflight", "monitor_started", "command", "monitor_stopped"]


def test_join_api_never_returns_secret_or_url_and_is_no_store(db) -> None:
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))
    seen: list[dict[str, object]] = []
    invite = "INVITE_CANARY_" + "x" * 32

    def enroll(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(
            201,
            json={
                "member_id": "member-public-id",
                "device_id": "device-public-id",
                "device_token": "ONE_TIME_DEVICE_TOKEN_CANARY",
                "display_name": "Alice",
                "policy_version": "1",
            },
        )

    store = MemoryCommunitySecretStore()
    community_client = CommunityClient(
        secret_store=store,
        transport=httpx.MockTransport(enroll),
    )
    original = app.state.community_client
    app.state.community_client = community_client
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/community/join",
                json={
                    "hub_url": "https://community.example.test",
                    "invite": invite,
                    "display_name": "Alice",
                    "consent": True,
                    "consent_version": "1",
                },
            )
    finally:
        app.state.community_client = original

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert seen == [
        {
            "invite_token": invite,
            "display_name": "Alice",
            "device_label": "Windows PC",
            "policy_version": "1",
            "consent": True,
        }
    ]
    public = response.text
    assert "community.example.test" not in public
    assert "INVITE_CANARY" not in public
    assert "ONE_TIME_DEVICE_TOKEN_CANARY" not in public
    assert store.load() is not None
    assert store.load().access_token == "ONE_TIME_DEVICE_TOKEN_CANARY"


def test_contributor_profile_local_proxy_uses_scoped_path_and_preserves_404(db) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/missing/profile"):
            return httpx.Response(404)
        assert request.url.path == "/v1/contributors/alice-public/profile"
        return httpx.Response(
            200,
            json={
                "contributor": {
                    "public_id": "alice-public",
                    "display_name": "Alice",
                    "joined_at": "2026-07-11T00:00:00Z",
                },
                "summary": {"games": 2},
                "by_currency": [],
                "by_limit": [],
                "by_multiplier": [],
                "trend": [],
                "recent_tournaments": [],
            },
        )

    community, _store = _configured_client(db, handler)
    save_community_config(
        db,
        CommunityLocalConfig(
            enabled=True,
            hub_url="https://community.example.test",
            consent_version="1",
            enrolled_at=datetime(2026, 7, 11),
            last_contact_at=datetime(2026, 7, 11),
            remote_has_contribution=True,
        ),
    )
    original = app.state.community_client
    app.state.community_client = community
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/community/contributors/alice-public/profile"
            )
            missing = client.get("/api/community/contributors/missing/profile")
    finally:
        app.state.community_client = original

    assert response.status_code == 200
    assert response.json()["contributor"]["public_id"] == "alice-public"
    assert response.headers["Cache-Control"] == "no-store"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Ressource communautaire introuvable."
    assert seen == [
        "/v1/contributors/alice-public/profile",
        "/v1/contributors/missing/profile",
    ]


def test_every_community_route_is_blocked_by_active_file_guard(db, tmp_path) -> None:
    active = tmp_path / "active-Expresso.txt"
    active.write_text("Winamax Poker - active", encoding="utf-8")
    save_settings(db, AnalyzerSettings(history_paths=[str(tmp_path)], hero_name="HERO"))
    original = app.state.community_client
    app.state.community_client = CommunityClient(secret_store=MemoryCommunitySecretStore())
    try:
        with TestClient(app) as client:
            response = client.get("/api/community/status")
    finally:
        app.state.community_client = original
    assert response.status_code == 423
    assert response.headers["Cache-Control"] == "no-store"
    assert "token" not in response.text.casefold()


def test_invalid_join_never_echoes_invite_or_hub_url(db) -> None:
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))
    with TestClient(app) as client:
        response = client.post(
            "/api/community/join",
            json={
                "hub_url": "http://insecure.example.test",
                "invite": "SECRET_INVITE_VALIDATION_CANARY",
                "display_name": "Alice",
                "consent": True,
                "consent_version": "1",
            },
        )
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert "SECRET_INVITE_VALIDATION_CANARY" not in response.text
    assert "insecure.example.test" not in response.text


def test_community_routes_are_no_store_after_process_interlock_trip(db) -> None:
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))
    original = app.state.analysis_interlock
    local_interlock = AnalysisInterlock()
    try:
        with TestClient(app) as client:
            app.state.analysis_interlock = local_interlock
            local_interlock.trip("synthetic Winamax detection")
            response = client.get("/api/community/status")
    finally:
        app.state.analysis_interlock = original
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert "token" not in response.text.casefold()


def test_client_payload_is_accepted_by_real_local_hub_contract(db, tmp_path) -> None:
    from app.community_hub.admin import bootstrap_owner, create_invite
    from app.community_hub.api import create_hub_app
    from app.community_hub.database import HubDatabase
    from app.community_hub.models import SharedTournament

    _import_completed(db)
    hub_database = HubDatabase(tmp_path / "hub" / "community_hub.db")
    hub_database.initialize()
    hub_db = hub_database.session()
    bootstrap_owner(hub_db, display_name="Owner", device_label="Owner PC")
    _invite, invite_token = create_invite(hub_db, expires_hours=1)
    hub_db.close()
    hub_app = create_hub_app(
        hub_database,
        docs_enabled=False,
        trusted_hosts=("localhost",),
        interlock=AnalysisInterlock(),
    )
    store = MemoryCommunitySecretStore()

    with TestClient(hub_app, base_url="http://localhost") as hub_http:
        def bridge(request: httpx.Request) -> httpx.Response:
            target = request.url.path
            if request.url.query:
                target += "?" + request.url.query.decode("ascii")
            upstream = hub_http.request(
                request.method,
                target,
                headers=dict(request.headers),
                content=request.content,
            )
            return httpx.Response(
                upstream.status_code,
                headers=dict(upstream.headers),
                content=upstream.content,
            )

        community = CommunityClient(
            secret_store=store,
            transport=httpx.MockTransport(bridge),
        )
        joined = community.join(
            db,
            CommunityJoinRequest(
                hub_url="http://localhost",
                invite=invite_token,
                display_name="Alice",
                consent=True,
                consent_version="1",
            ),
        )
        assert joined["pending"] == 1
        assert joined["available"] is False
        synced = community.sync(db)
        assert synced.synced == 1
        assert synced.pending == 0
        assert synced.available is True
        contributors = community.proxy_get(db, "/v1/contributors")
        assert contributors["items"][0]["display_name"] == "Alice"
        alice_public_id = contributors["items"][0]["public_id"]
        device_token = store.load().access_token
        assert community.leave(db) is True
        revoked = hub_http.get(
            "/v1/contributors",
            headers={"Authorization": f"Bearer {device_token}"},
        )
        assert revoked.status_code == 401
        assert store.load() is None

        # A targeted re-enrollment rotates both bearer and local HMAC secret.
        # The hub must deduplicate the same payload rather than duplicate it.
        hub_db = hub_database.session()
        _targeted, targeted_token = create_invite(
            hub_db,
            expires_hours=1,
            for_member_public_id=alice_public_id,
        )
        hub_db.close()
        second_store = MemoryCommunitySecretStore()
        second = CommunityClient(
            secret_store=second_store,
            transport=httpx.MockTransport(bridge),
        )
        second_join = second.join(
            db,
            CommunityJoinRequest(
                hub_url="http://localhost",
                invite=targeted_token,
                display_name="Alice",
                consent=True,
                consent_version="1",
            ),
        )
        assert second_join["pending"] == 1
        assert second.sync(db).available is True
        hub_db = hub_database.session()
        assert hub_db.scalar(select(func.count()).select_from(SharedTournament)) == 1
        hub_db.close()
        assert second.leave(db) is True

        # A genuinely fresh local database has no SyncRecord. Membership-level
        # contribution confirmed by the hub must still unlock shared reads.
        db.execute(delete(Tournament))
        db.commit()
        hub_db = hub_database.session()
        _fresh, fresh_token = create_invite(
            hub_db,
            expires_hours=1,
            for_member_public_id=alice_public_id,
        )
        hub_db.close()
        fresh_store = MemoryCommunitySecretStore()
        fresh = CommunityClient(
            secret_store=fresh_store,
            transport=httpx.MockTransport(bridge),
        )
        fresh_join = fresh.join(
            db,
            CommunityJoinRequest(
                hub_url="http://localhost",
                invite=fresh_token,
                display_name="Alice",
                consent=True,
                consent_version="1",
            ),
        )
        assert fresh_join["pending"] == 0
        fresh_sync = fresh.sync(db)
        assert fresh_sync.synced == 0
        assert fresh_sync.available is True
        assert fresh.status(db).available is True
        assert fresh.proxy_get(db, "/v1/contributors")["items"]
        assert fresh.leave(db) is True

    hub_database.dispose()


def test_sync_delivers_core_then_mandatory_opponent_enrichment(db) -> None:
    tournament = _import_completed(db)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/sync/tournaments":
            return httpx.Response(
                201,
                json={
                    "status": "created",
                    "public_id": "remote-tournament-1",
                    "hand_count": tournament.total_hands,
                },
            )
        assert request.url.path == "/v1/sync/tournaments/remote-tournament-1/opponents"
        body = json.loads(request.content)
        assert [item["alias"] for item in body["opponents"]] == [
            "OPPONENT_1",
            "OPPONENT_2",
        ]
        assert all(item["display_name"] for item in body["opponents"])
        assert "HERO" not in {item["alias"] for item in body["opponents"]}
        return httpx.Response(
            201,
            json={
                "status": "created",
                "opponent_count": 2,
                "observation_count": tournament.total_hands * 2,
            },
        )

    community, _store = _configured_client(db, handler)
    save_community_config(
        db,
        CommunityLocalConfig(
            enabled=True,
            hub_url="https://community.example.test",
            consent_version="2",
            enrolled_at=datetime(2026, 7, 11),
            last_contact_at=datetime(2026, 7, 11),
            opponent_tracking_required=True,
        ),
    )
    result = community.sync(db)
    assert result.queued == 2
    assert result.synced == 2
    assert result.pending == 0
    assert result.available is True
    record = db.scalar(select(CommunityOpponentSyncRecord))
    assert record is not None
    assert record.state == "synced"
    assert record.tournament_id == tournament.id
    assert not hasattr(record, "payload")
    assert [request.url.path for request in requests] == [
        "/v1/sync/tournaments",
        "/v1/sync/tournaments/remote-tournament-1/opponents",
    ]


def test_retro_enrichment_is_queued_for_an_already_synced_tournament(db) -> None:
    tournament = _import_completed(db)
    db.add(
        CommunitySyncRecord(
            tournament_id=tournament.id,
            client_key="a" * 64,
            schema_version="1",
            payload_sha256="b" * 64,
            state="synced",
            remote_public_id="existing-remote-id",
        )
    )
    db.commit()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/me":
            return httpx.Response(
                200,
                json={
                    "member_id": "member-1",
                    "display_name": "Alice",
                    "has_contribution": True,
                    "policy_version": "2",
                    "opponent_tracking_required": True,
                },
            )
        assert request.url.path == "/v1/sync/tournaments/existing-remote-id/opponents"
        return httpx.Response(
            201,
            json={"status": "created", "opponent_count": 2, "observation_count": 16},
        )

    community, _store = _configured_client(db, handler)
    save_community_config(
        db,
        CommunityLocalConfig(
            enabled=True,
            hub_url="https://community.example.test",
            consent_version="2",
            enrolled_at=datetime(2026, 7, 11),
            last_contact_at=datetime(2026, 7, 11),
            remote_has_contribution=True,
            opponent_tracking_required=True,
        ),
    )
    result = community.sync(db)
    assert result.queued == 1
    assert result.synced == 1
    assert result.pending == 0
    assert requests == [
        "/v1/me",
        "/v1/sync/tournaments/existing-remote-id/opponents",
    ]


def test_opponent_pending_queue_blocks_views_and_survives_offline_retry(db) -> None:
    tournament = _import_completed(db)

    def offline_after_core(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/sync/tournaments":
            return httpx.Response(
                201,
                json={
                    "status": "created",
                    "public_id": "remote-offline-opponents",
                    "hand_count": tournament.total_hands,
                },
            )
        raise httpx.ConnectError("synthetic opponent offline", request=request)

    community, _store = _configured_client(db, offline_after_core)
    save_community_config(
        db,
        CommunityLocalConfig(
            enabled=True,
            hub_url="https://community.example.test",
            consent_version="2",
            enrolled_at=datetime(2026, 7, 11),
            last_contact_at=datetime(2026, 7, 11),
            opponent_tracking_required=True,
        ),
    )
    result = community.sync(db)
    assert result.online is False
    assert result.pending == 1
    pending = db.scalar(select(CommunityOpponentSyncRecord))
    assert pending is not None and pending.state == "pending"
    with pytest.raises(CommunityPendingError):
        community.proxy_get(db, "/v1/opponents")


def test_v1_consent_never_serializes_names_and_upgrade_creates_queue(db, monkeypatch) -> None:
    tournament = _import_completed(db)
    db.add(
        CommunitySyncRecord(
            tournament_id=tournament.id,
            client_key="c" * 64,
            schema_version="1",
            payload_sha256="d" * 64,
            state="synced",
            remote_public_id="legacy-remote",
        )
    )
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/consent"
        return httpx.Response(
            200,
            json={"policy_version": "2", "opponent_tracking_enabled": True},
        )

    community, _store = _configured_client(db, handler)
    save_community_config(
        db,
        CommunityLocalConfig(
            enabled=True,
            hub_url="https://community.example.test",
            consent_version="1",
            enrolled_at=datetime(2026, 7, 11),
            last_contact_at=datetime(2026, 7, 11),
            remote_has_contribution=True,
            opponent_tracking_required=True,
        ),
    )
    original = community_client_module.serialize_tournament_opponents
    monkeypatch.setattr(
        community_client_module,
        "serialize_tournament_opponents",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("names read before v2 consent")
        ),
    )
    status = community.status(db)
    assert status.available is False
    assert status.blocked_reason == "consent_upgrade_required"
    assert db.scalar(select(CommunityOpponentSyncRecord)) is None
    monkeypatch.setattr(
        community_client_module, "serialize_tournament_opponents", original
    )
    upgraded = community.upgrade_consent(
        db, CommunityConsentRequest(consent=True, policy_version="2")
    )
    assert upgraded.opponent_tracking_enabled is True
    queued = db.scalar(select(CommunityOpponentSyncRecord))
    assert queued is not None and queued.state == "pending"


def test_legacy_client_learns_v2_requirement_from_collective_403(db) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    community, _store = _configured_client(db, handler)
    save_community_config(
        db,
        CommunityLocalConfig(
            enabled=True,
            hub_url="https://community.example.test",
            consent_version="1",
            enrolled_at=datetime(2026, 7, 11),
            last_contact_at=datetime(2026, 7, 11),
            remote_has_contribution=True,
            opponent_tracking_required=False,
        ),
    )
    with pytest.raises(community_client_module.CommunityConsentRequiredError):
        community.proxy_get(db, "/v1/contributors")
    config = load_community_config(db)
    assert config.opponent_tracking_required is True
    assert config.last_error_code == "consent_upgrade_required"


def test_opponent_list_profile_and_consent_local_proxies(db) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/v1/consent":
            return httpx.Response(
                200,
                json={"policy_version": "2", "opponent_tracking_enabled": True},
            )
        if request.url.path == "/v1/opponents":
            assert dict(request.url.params) == {"limit": "25", "offset": "5"}
            return httpx.Response(
                200,
                json={"items": [], "total": 0, "limit": 25, "offset": 5},
            )
        assert request.url.path == "/v1/opponents/opponent-public/profile"
        return httpx.Response(200, json={"identity": {"public_id": "opponent-public"}})

    community, _store = _configured_client(db, handler)
    save_community_config(
        db,
        CommunityLocalConfig(
            enabled=True,
            hub_url="https://community.example.test",
            consent_version="1",
            enrolled_at=datetime(2026, 7, 11),
            last_contact_at=datetime(2026, 7, 11),
            remote_has_contribution=True,
            opponent_tracking_required=True,
        ),
    )
    original = app.state.community_client
    app.state.community_client = community
    try:
        with TestClient(app) as client:
            consent = client.post(
                "/api/community/consent",
                json={"consent": True, "policy_version": "2"},
            )
            listing = client.get("/api/community/opponents?limit=25&offset=5")
            profile = client.get(
                "/api/community/opponents/opponent-public/profile"
            )
    finally:
        app.state.community_client = original
    assert consent.status_code == 200
    assert listing.status_code == 200
    assert profile.status_code == 200
    assert seen == [
        ("POST", "/v1/consent"),
        ("GET", "/v1/opponents"),
        ("GET", "/v1/opponents/opponent-public/profile"),
    ]


def test_leave_deletes_both_delivery_queues(db) -> None:
    tournament = _import_completed(db)
    core = CommunitySyncRecord(
        tournament_id=tournament.id,
        client_key="e" * 64,
        schema_version="1",
        payload_sha256="f" * 64,
        state="synced",
        remote_public_id="remote-leave",
    )
    db.add(core)
    db.flush()
    db.add(
        CommunityOpponentSyncRecord(
            tournament_id=tournament.id,
            schema_version="1",
            payload_sha256="1" * 64,
            state="pending",
        )
    )
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(204)

    community, store = _configured_client(db, handler)
    assert community.leave(db) is True
    assert store.load() is None
    assert db.scalar(select(func.count()).select_from(CommunitySyncRecord)) == 0
    assert db.scalar(select(func.count()).select_from(CommunityOpponentSyncRecord)) == 0


def test_active_file_guard_runs_before_opponent_name_serialization(
    db, tmp_path, monkeypatch
) -> None:
    tournament = _import_completed(db)
    db.add(
        CommunitySyncRecord(
            tournament_id=tournament.id,
            client_key="2" * 64,
            schema_version="1",
            payload_sha256="3" * 64,
            state="synced",
            remote_public_id="remote-guard",
        )
    )
    db.commit()
    community, _store = _configured_client(
        db,
        lambda _request: (_ for _ in ()).throw(
            AssertionError("network called while active")
        ),
    )
    active = tmp_path / "active-Expresso.txt"
    active.write_text("Winamax Poker - active", encoding="utf-8")
    save_settings(
        db,
        AnalyzerSettings(history_paths=[str(tmp_path)], hero_name="HERO"),
    )
    save_community_config(
        db,
        CommunityLocalConfig(
            enabled=True,
            hub_url="https://community.example.test",
            consent_version="2",
            enrolled_at=datetime(2026, 7, 11),
            opponent_tracking_required=True,
        ),
    )
    monkeypatch.setattr(
        community_client_module,
        "serialize_tournament_opponents",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("names serialized while active")
        ),
    )
    with pytest.raises(community_client_module.CommunityActivityError):
        community.sync(db)
    assert db.scalar(select(CommunityOpponentSyncRecord)) is None


def test_local_opponent_queue_table_is_added_without_losing_v1_data(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy-local.db').as_posix()}")
    legacy_tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name != "community_opponent_sync_records"
    ]
    Base.metadata.create_all(engine, tables=legacy_tables)
    with Session(engine) as db:
        db.add(Setting(key="legacy-sentinel", value_json='{"preserved":true}'))
        db.commit()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        assert db.scalar(
            select(Setting.value_json).where(Setting.key == "legacy-sentinel")
        ) == '{"preserved":true}'
    with engine.connect() as connection:
        assert "community_opponent_sync_records" in set(
            engine.dialect.get_table_names(connection)
        )
    engine.dispose()


def test_manual_rescan_revalidates_changed_opponent_payload_without_status_rehash(
    db, monkeypatch
) -> None:
    tournament = _import_completed(db)
    db.add(
        CommunitySyncRecord(
            tournament_id=tournament.id,
            client_key="4" * 64,
            schema_version="1",
            payload_sha256="5" * 64,
            state="synced",
            remote_public_id="remote-revalidate",
        )
    )
    db.commit()
    community, _store = _configured_client(
        db,
        lambda _request: httpx.Response(
            409
        ),  # Changed remote identity is intentionally surfaced as a conflict.
    )
    save_community_config(
        db,
        CommunityLocalConfig(
            enabled=True,
            hub_url="https://community.example.test",
            consent_version="2",
            enrolled_at=datetime(2026, 7, 11),
            last_contact_at=datetime(2026, 7, 11),
            remote_has_contribution=True,
            opponent_tracking_required=True,
        ),
    )
    assert community.enqueue_opponents(db) == 1
    record = db.scalar(select(CommunityOpponentSyncRecord))
    assert record is not None
    original_digest = record.payload_sha256
    record.state = "synced"
    record.synced_at = datetime(2026, 7, 11)
    db.commit()
    opponent = db.scalar(select(Player).where(Player.is_hero.is_(False)).order_by(Player.id))
    assert opponent is not None
    opponent.display_name = "Corrected Opponent Name"
    db.commit()

    def forbidden_serializer(*_args, **_kwargs):
        raise AssertionError("ordinary status must not rehash delivered opponent payloads")

    original_serializer = community_client_module.serialize_tournament_opponents
    monkeypatch.setattr(
        community_client_module, "serialize_tournament_opponents", forbidden_serializer
    )
    assert community.status(db).pending == 0
    assert community.enqueue_opponents(db) == 0
    monkeypatch.setattr(
        community_client_module,
        "serialize_tournament_opponents",
        original_serializer,
    )
    assert community.enqueue_opponents(db, revalidate_existing=True) == 1
    db.refresh(record)
    assert record.state == "pending"
    assert record.synced_at is None
    assert record.payload_sha256 != original_digest


def test_post_rescan_helper_requests_existing_opponent_revalidation(db, monkeypatch) -> None:
    save_settings(db, AnalyzerSettings(history_paths=[], hero_name=""))
    save_community_config(
        db,
        CommunityLocalConfig(
            enabled=True,
            hub_url="https://community.example.test",
            consent_version="2",
            opponent_tracking_required=True,
        ),
    )
    community = CommunityClient(secret_store=MemoryCommunitySecretStore())
    seen: list[bool] = []

    def fake_sync(_db, *, revalidate_opponents: bool = False):
        seen.append(revalidate_opponents)
        return CommunitySyncResponse(
            queued=0,
            synced=0,
            pending=0,
            online=True,
            available=True,
        )

    monkeypatch.setattr(community, "sync", fake_sync)
    result = sync_community_after_rescan(db, community)
    assert result is not None
    assert seen == [True]

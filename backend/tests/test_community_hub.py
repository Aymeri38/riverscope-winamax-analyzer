from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import time

import pytest
import httpx
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import func, select

from app.community_hub.admin import (
    AdminError,
    bootstrap_owner,
    create_invite,
    delete_member,
    list_devices,
    list_members,
    revoke,
)
from app.community_hub.api import create_hub_app
from app.community_hub.config import MAX_BODY_BYTES, get_hub_config
from app.community_hub.database import HubBase, HubDatabase
from app.community_hub.models import Device, Invite, Member, SharedTournament
from app.community_hub.models import SharedHand, SyncReceipt
from app.community_hub.rate_limit import InMemoryRateLimiter
from app.community_hub.runner import run, validate_tls_binding
from app.community_hub.schemas import SyncTournamentRequest
from app.community_hub.service import sync_tournament
from app.core.process_guard import AnalysisInterlock, SAFETY_EXIT_CODE
from app.core.community_secret import MemoryCommunitySecretStore
from app.models import Tournament
from app.schemas.api import AnalyzerSettings
from app.services.community_client import serialize_completed_tournament
from app.services.community_client import CommunityClient
from app.schemas.community import CommunityJoinRequest
from app.services.importer import import_pair
from app.services.settings import save_settings


FIXTURES = Path(__file__).parents[2] / "fixtures"


APPROVAL_ENV = {
    "WXA_COMMUNITY_APPROVAL_ACK": "YES",
    "WXA_COMMUNITY_APPROVAL_REFERENCE": "written-approval-test-reference",
}


def tournament_payload(client_key: str = "a" * 64) -> dict:
    started = datetime(2025, 1, 2, 19, 0, tzinfo=UTC)
    ended = started + timedelta(minutes=10)
    return {
        "schema_version": "1",
        "client_key": client_key,
        "tournament": {
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
            "format": "EXPRESSO",
            "is_nitro": False,
            "currency": "EUR",
            "total_buyin": 2.0,
            "multiplier": 3.0,
            "prize_pool": 6.0,
            "reward": 6.0,
            "final_rank": 1,
            "duration_seconds": 600,
            "total_hands": 1,
            "registered_players": 3,
            "initial_stack": 500,
            "final_stack": 1500,
            "chip_delta": 1000,
            "hands": [
                {
                    "hand_number": 1,
                    "played_at": (started + timedelta(minutes=1)).isoformat(),
                    "level": 1,
                    "small_blind": 10,
                    "big_blind": 20,
                    "ante": 0,
                    "button_seat": 1,
                    "max_players": 3,
                    "active_players": 3,
                    "total_pot": 90,
                    "hero_net": 40,
                    "is_all_in": False,
                    "reached_showdown": False,
                    "hero_cards": ["As", "Kd"],
                    "board": ["2c", "7h", "Ts"],
                    "players": [
                        {
                            "alias": "HERO",
                            "seat": 1,
                            "position": "BTN",
                            "starting_stack": 500,
                            "ending_stack": 540,
                            "invested": 50,
                            "won": 90,
                            "net": 40,
                            "hole_cards": ["As", "Kd"],
                            "showed": False,
                            "is_winner": True,
                            "is_all_in": False,
                        },
                        {
                            "alias": "OPPONENT_1",
                            "seat": 2,
                            "position": "SB",
                            "starting_stack": 500,
                            "ending_stack": 480,
                            "invested": 20,
                            "won": 0,
                            "net": -20,
                            "hole_cards": None,
                            "showed": False,
                            "is_winner": False,
                            "is_all_in": False,
                        },
                        {
                            "alias": "OPPONENT_2",
                            "seat": 3,
                            "position": "BB",
                            "starting_stack": 500,
                            "ending_stack": 480,
                            "invested": 20,
                            "won": 0,
                            "net": -20,
                            "hole_cards": None,
                            "showed": False,
                            "is_winner": False,
                            "is_all_in": False,
                        },
                    ],
                    "actions": [
                        {
                            "sequence": 1,
                            "actor_alias": "OPPONENT_1",
                            "street": "PREFLOP",
                            "action_type": "POST_SB",
                            "amount": 10,
                            "to_amount": 10,
                            "pot_after": 10,
                            "is_all_in": False,
                        },
                        {
                            "sequence": 2,
                            "actor_alias": "OPPONENT_2",
                            "street": "PREFLOP",
                            "action_type": "POST_BB",
                            "amount": 20,
                            "to_amount": 20,
                            "pot_after": 30,
                            "is_all_in": False,
                        },
                        {
                            "sequence": 3,
                            "actor_alias": "HERO",
                            "street": "PREFLOP",
                            "action_type": "RAISE",
                            "amount": 50,
                            "to_amount": 50,
                            "pot_after": 80,
                            "is_all_in": False,
                        },
                        {
                            "sequence": 4,
                            "actor_alias": "HERO",
                            "street": "PREFLOP",
                            "action_type": "UNCALLED_RETURN",
                            "amount": 10,
                            "to_amount": None,
                            "pot_after": 90,
                            "is_all_in": False,
                        },
                        {
                            "sequence": 5,
                            "actor_alias": "OPPONENT_1",
                            "street": "SHOWDOWN",
                            "action_type": "MUCK",
                            "amount": None,
                            "to_amount": None,
                            "pot_after": 90,
                            "is_all_in": False,
                        },
                    ],
                }
            ],
        },
    }


@pytest.fixture
def hub(tmp_path):
    database = HubDatabase(tmp_path / "hub-data" / "community_hub.db")
    database.initialize()
    db = database.session()
    owner, owner_device, owner_token = bootstrap_owner(
        db, display_name="Owner", device_label="Owner PC"
    )
    invite, invite_token = create_invite(db, expires_hours=24)
    db.close()
    app = create_hub_app(
        database,
        docs_enabled=False,
        trusted_hosts=("testserver", "localhost"),
        interlock=AnalysisInterlock(),
    )
    with TestClient(app) as client:
        yield {
            "client": client,
            "database": database,
            "owner": owner,
            "owner_token": owner_token,
            "invite": invite,
            "invite_token": invite_token,
        }
    database.dispose()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def enroll_friend(hub, name: str = "Alice") -> dict:
    response = hub["client"].post(
        "/v1/enroll",
        json={
            "invite_token": hub["invite_token"],
            "display_name": name,
            "device_label": f"PC {name}",
            "policy_version": "1",
            "consent": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_hub_uses_separate_database_and_expected_tables(hub):
    assert hub["database"].database_path.name == "community_hub.db"
    assert set(HubBase.metadata.tables) == {
        "members",
        "invites",
        "devices",
        "shared_tournaments",
        "shared_hands",
        "sync_receipts",
    }


def test_auth_enrollment_invite_one_time_and_hash_storage(hub):
    client = hub["client"]
    unauthenticated = client.get("/v1/contributors")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["cache-control"] == "no-store"

    enrolled = enroll_friend(hub)
    assert enrolled["device_token"].startswith("wxa_dev_")
    db = hub["database"].session()
    stored_device = db.scalar(select(Device).where(Device.public_id == enrolled["device_id"]))
    stored_invite = db.scalar(select(Invite).where(Invite.public_id == hub["invite"].public_id))
    assert stored_device is not None
    assert stored_device.token_hash != enrolled["device_token"]
    assert len(stored_device.token_hash) == 64
    assert stored_invite is not None and stored_invite.used_at is not None
    db.close()

    repeated = client.post(
        "/v1/enroll",
        json={
            "invite_token": hub["invite_token"],
            "display_name": "Bob",
            "device_label": "PC Bob",
            "policy_version": "1",
            "consent": True,
        },
    )
    assert repeated.status_code == 400


def test_request_size_trusted_host_and_expired_device_guards(hub):
    oversized = hub["client"].post(
        "/v1/enroll",
        content=b"{}",
        headers={"Content-Length": str(MAX_BODY_BYTES + 1)},
    )
    assert oversized.status_code == 413
    assert oversized.headers["cache-control"] == "no-store"

    bad_host = hub["client"].get(
        "/v1/contributors", headers={"Host": "untrusted.example"}
    )
    assert bad_host.status_code == 400
    assert bad_host.headers["cache-control"] == "no-store"

    enrolled = enroll_friend(hub)
    db = hub["database"].session()
    device = db.scalar(select(Device).where(Device.public_id == enrolled["device_id"]))
    assert device is not None
    device.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    db.commit()
    db.close()
    expired = hub["client"].delete(
        "/v1/device", headers=auth(enrolled["device_token"])
    )
    assert expired.status_code == 401


def test_expired_invite_is_rejected(hub):
    db = hub["database"].session()
    invite, raw_token = create_invite(db, expires_hours=1)
    invite.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    db.commit()
    db.close()
    response = hub["client"].post(
        "/v1/enroll",
        json={
            "invite_token": raw_token,
            "display_name": "Late member",
            "device_label": "Late PC",
            "policy_version": "1",
            "consent": True,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invitation invalide ou expiree."


def test_display_names_are_normalized_unique_and_reject_bidi(hub):
    enroll_friend(hub, "Alice")
    db = hub["database"].session()
    _invite, second_token = create_invite(db, expires_hours=1)
    _invite, third_token = create_invite(db, expires_hours=1)
    db.close()
    duplicate = hub["client"].post(
        "/v1/enroll",
        json={
            "invite_token": second_token,
            "display_name": "  aLiCe  ",
            "device_label": "Second PC",
            "policy_version": "1",
            "consent": True,
        },
    )
    assert duplicate.status_code == 409
    bidi = hub["client"].post(
        "/v1/enroll",
        json={
            "invite_token": third_token,
            "display_name": "Mallory\u202eadmin",
            "device_label": "Third PC",
            "policy_version": "1",
            "consent": True,
        },
    )
    assert bidi.status_code == 422
    assert "Mallory" not in bidi.text


def test_consultation_requires_a_contribution(hub):
    enrolled = enroll_friend(hub)
    identity = hub["client"].get(
        "/v1/me", headers=auth(enrolled["device_token"])
    )
    assert identity.status_code == 200
    assert identity.json() == {
        "member_id": enrolled["member_id"],
        "display_name": "Alice",
        "has_contribution": False,
    }
    response = hub["client"].get(
        "/v1/dashboard", headers=auth(enrolled["device_token"])
    )
    assert response.status_code == 403
    assert "Synchronisez" in response.json()["detail"]
    assert hub["client"].post(
        "/v1/sync/tournaments",
        json=tournament_payload(),
        headers=auth(enrolled["device_token"]),
    ).status_code == 201
    assert hub["client"].get(
        "/v1/me", headers=auth(enrolled["device_token"])
    ).json()["has_contribution"] is True


def test_sync_is_idempotent_and_rejects_changed_reuse(hub):
    enrolled = enroll_friend(hub)
    headers = auth(enrolled["device_token"])
    payload = tournament_payload()
    created = hub["client"].post("/v1/sync/tournaments", json=payload, headers=headers)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "created"

    repeated = hub["client"].post("/v1/sync/tournaments", json=payload, headers=headers)
    assert repeated.status_code == 200
    assert repeated.json() == {**created.json(), "status": "existing"}
    new_device_namespace = deepcopy(payload)
    new_device_namespace["client_key"] = "e" * 64
    after_reenrollment = hub["client"].post(
        "/v1/sync/tournaments", json=new_device_namespace, headers=headers
    )
    assert after_reenrollment.status_code == 200
    assert after_reenrollment.json()["public_id"] == created.json()["public_id"]
    db = hub["database"].session()
    assert len(list(db.scalars(select(SharedTournament)))) == 1
    db.close()

    changed = deepcopy(payload)
    changed["tournament"]["reward"] = 0
    conflict = hub["client"].post("/v1/sync/tournaments", json=changed, headers=headers)
    assert conflict.status_code == 409


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("tournament", "external_id"), "raw-123"),
        (("tournament", "source_path"), "C:/private/history.txt"),
        (("tournament", "hero_name"), "SecretPseudo"),
        (("tournament", "notes"), "private note"),
        (("tournament", "tags"), ["private"]),
        (("tournament", "file_hash"), "b" * 64),
        (("tournament", "hands", 0, "action_text"), "SecretPseudo raises"),
    ],
)
def test_privacy_allowlist_rejects_sensitive_fields_without_echo(hub, path, value):
    enrolled = enroll_friend(hub)
    payload = tournament_payload()
    target = payload
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value
    response = hub["client"].post(
        "/v1/sync/tournaments",
        json=payload,
        headers=auth(enrolled["device_token"]),
    )
    assert response.status_code == 422
    assert str(value) not in response.text


def test_rejects_real_opponent_name(hub):
    enrolled = enroll_friend(hub)
    payload = tournament_payload()
    payload["tournament"]["hands"][0]["players"][1]["alias"] = "RealOpponent"
    response = hub["client"].post(
        "/v1/sync/tournaments",
        json=payload,
        headers=auth(enrolled["device_token"]),
    )
    assert response.status_code == 422
    assert "RealOpponent" not in response.text


def test_filter_dashboard_and_replay_contract(hub):
    enrolled = enroll_friend(hub)
    headers = auth(enrolled["device_token"])
    sync = hub["client"].post(
        "/v1/sync/tournaments", json=tournament_payload(), headers=headers
    )
    assert sync.status_code == 201
    contributor_id = enrolled["member_id"]

    contributors = hub["client"].get("/v1/contributors", headers=headers).json()["items"]
    assert any(item["public_id"] == contributor_id for item in contributors)
    assert all(item["public_id"] != hub["owner"].public_id for item in contributors)
    filtered = hub["client"].get(
        f"/v1/tournaments?contributor_id={contributor_id}", headers=headers
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["contributor_id"] == contributor_id
    tournament_public_id = filtered["items"][0]["public_id"]

    hands = hub["client"].get(
        f"/v1/hands?contributor_id={contributor_id}", headers=headers
    ).json()
    assert hands["total"] == 1
    assert hands["items"][0]["hero_cards"] == ["As", "Kd"]
    assert hands["items"][0]["board"] == ["2c", "7h", "Ts"]
    by_tournament = hub["client"].get(
        f"/v1/hands?tournament_id={tournament_public_id}", headers=headers
    ).json()
    assert by_tournament["total"] == 1
    assert by_tournament["items"][0]["tournament_id"] == tournament_public_id
    replay = hub["client"].get(
        f"/v1/hands/{hands['items'][0]['public_id']}/replay", headers=headers
    ).json()
    assert replay["replay"]["actions"][-2]["action_type"] == "UNCALLED_RETURN"
    assert replay["replay"]["actions"][-1]["action_type"] == "MUCK"
    assert all(
        player["alias"] == "HERO" or player["alias"].startswith("OPPONENT_")
        for player in replay["replay"]["players"]
    )
    dashboard = hub["client"].get(
        f"/v1/dashboard?contributor_id={contributor_id}", headers=headers
    ).json()
    assert dashboard["tournaments"] == 1
    assert dashboard["hands"] == 1
    assert dashboard["net_result"] == 4.0


def test_real_local_serializer_matches_hub_contract(db, hub):
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
    payload = serialize_completed_tournament(
        tournament, b"contract-test-client-secret-32b"
    ).model_dump(mode="json")
    enrolled = enroll_friend(hub)
    response = hub["client"].post(
        "/v1/sync/tournaments",
        json=payload,
        headers=auth(enrolled["device_token"]),
    )
    assert response.status_code == 201, response.text
    assert response.json()["hand_count"] == tournament.total_hands


def test_real_client_reenrollment_does_not_duplicate_history(db, hub):
    settings = AnalyzerSettings(history_paths=[], hero_name="HERO")
    save_settings(db, settings)
    assert import_pair(
        db,
        FIXTURES / "expresso_synthetic_hands.txt",
        FIXTURES / "expresso_synthetic_summary.txt",
        settings,
        datetime(2030, 1, 1, 12, 0, tzinfo=UTC),
    ) == "imported"

    def bridge(request: httpx.Request) -> httpx.Response:
        target = request.url.path
        if request.url.query:
            target += "?" + request.url.query.decode("ascii")
        upstream = hub["client"].request(
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

    store = MemoryCommunitySecretStore()
    community = CommunityClient(
        secret_store=store,
        transport=httpx.MockTransport(bridge),
    )
    join_request = CommunityJoinRequest(
        hub_url="http://localhost",
        invite=hub["invite_token"],
        display_name="Alice",
        consent=True,
        consent_version="1",
    )
    community.join(db, join_request)
    first_secret = store.load()
    assert first_secret is not None
    assert community.sync(db).synced == 1

    hub_db = hub["database"].session()
    member = hub_db.scalar(select(Member).where(Member.display_name == "Alice"))
    assert member is not None
    member_public_id = member.public_id
    hub_db.close()
    assert community.leave(db) is True

    hub_db = hub["database"].session()
    _invite, targeted_token = create_invite(
        hub_db,
        expires_hours=1,
        for_member_public_id=member_public_id,
    )
    hub_db.close()
    community.join(
        db,
        CommunityJoinRequest(
            hub_url="http://localhost",
            invite=targeted_token,
            display_name="Alice",
            consent=True,
            consent_version="1",
        ),
    )
    second_secret = store.load()
    assert second_secret is not None
    assert second_secret.client_secret != first_secret.client_secret
    result = community.sync(db)
    assert result.synced == 1
    assert result.pending == 0

    hub_db = hub["database"].session()
    assert int(hub_db.scalar(select(func.count(SharedTournament.id))) or 0) == 1
    assert int(hub_db.scalar(select(func.count(SharedHand.id))) or 0) == 8
    assert int(hub_db.scalar(select(func.count(SyncReceipt.id))) or 0) == 2
    same_member = hub_db.scalar(select(Member).where(Member.public_id == member_public_id))
    assert same_member is not None
    hub_db.close()


def test_server_rejects_recent_tournament_and_recent_hand(hub):
    enrolled = enroll_friend(hub)
    headers = auth(enrolled["device_token"])
    recent_tournament = tournament_payload()
    now = datetime.now(UTC)
    recent_tournament["tournament"]["started_at"] = (now - timedelta(minutes=5)).isoformat()
    recent_tournament["tournament"]["ended_at"] = (now - timedelta(seconds=30)).isoformat()
    recent_tournament["tournament"]["hands"][0]["played_at"] = (
        now - timedelta(minutes=2)
    ).isoformat()
    assert hub["client"].post(
        "/v1/sync/tournaments", json=recent_tournament, headers=headers
    ).status_code == 409

    recent_hand = tournament_payload("b" * 64)
    recent_hand["tournament"]["hands"][0]["played_at"] = (
        now - timedelta(seconds=30)
    ).isoformat()
    # Keep the hand within the declared tournament bounds to exercise the
    # independent server-time check rather than the tournament-range check.
    recent_hand["tournament"]["ended_at"] = (now - timedelta(minutes=2)).isoformat()
    recent_hand["tournament"]["started_at"] = (now - timedelta(minutes=12)).isoformat()
    assert hub["client"].post(
        "/v1/sync/tournaments", json=recent_hand, headers=headers
    ).status_code == 409


def test_revoked_member_is_retained_but_hidden_from_collective_views(hub):
    enrolled = enroll_friend(hub)
    friend_headers = auth(enrolled["device_token"])
    assert hub["client"].post(
        "/v1/sync/tournaments", json=tournament_payload(), headers=friend_headers
    ).status_code == 201
    owner_headers = auth(hub["owner_token"])
    assert hub["client"].post(
        "/v1/sync/tournaments", json=tournament_payload("c" * 64), headers=owner_headers
    ).status_code == 201

    db = hub["database"].session()
    revoke(db, kind="member", public_id=enrolled["member_id"])
    assert db.scalar(select(Member).where(Member.public_id == enrolled["member_id"])) is not None
    db.close()

    assert hub["client"].get("/v1/dashboard", headers=friend_headers).status_code == 401
    contributors = hub["client"].get("/v1/contributors", headers=owner_headers).json()["items"]
    assert all(item["public_id"] != enrolled["member_id"] for item in contributors)
    filtered = hub["client"].get(
        f"/v1/tournaments?contributor_id={enrolled['member_id']}", headers=owner_headers
    )
    assert filtered.status_code == 404
    assert hub["client"].get("/v1/tournaments", headers=owner_headers).json()["total"] == 1


def test_explicit_member_deletion_cascades_shared_data(hub):
    enrolled = enroll_friend(hub)
    assert hub["client"].post(
        "/v1/sync/tournaments",
        json=tournament_payload(),
        headers=auth(enrolled["device_token"]),
    ).status_code == 201
    db = hub["database"].session()
    with pytest.raises(AdminError, match="confirm"):
        delete_member(db, public_id=enrolled["member_id"], confirmation="NO")
    delete_member(db, public_id=enrolled["member_id"], confirmation="DELETE")
    assert db.scalar(select(Member).where(Member.public_id == enrolled["member_id"])) is None
    assert db.scalar(select(SharedTournament)) is None
    db.close()


def test_self_revoke_returns_204_and_invalidates_bearer(hub):
    enrolled = enroll_friend(hub)
    headers = auth(enrolled["device_token"])
    revoked = hub["client"].delete("/v1/device", headers=headers)
    assert revoked.status_code == 204
    assert revoked.content == b""
    assert revoked.headers["cache-control"] == "no-store"
    assert hub["client"].delete("/v1/device", headers=headers).status_code == 401


def test_targeted_invite_reenrolls_same_member_after_device_revoke(hub):
    enrolled = enroll_friend(hub)
    old_headers = auth(enrolled["device_token"])
    assert hub["client"].post(
        "/v1/sync/tournaments", json=tournament_payload(), headers=old_headers
    ).status_code == 201
    assert hub["client"].delete("/v1/device", headers=old_headers).status_code == 204
    db = hub["database"].session()
    _invite, reenroll_token = create_invite(
        db,
        expires_hours=1,
        for_member_public_id=enrolled["member_id"],
    )
    db.close()
    reenrolled = hub["client"].post(
        "/v1/enroll",
        json={
            "invite_token": reenroll_token,
            "display_name": "Alice",
            "device_label": "Replacement PC",
            "policy_version": "1",
            "consent": True,
        },
    )
    assert reenrolled.status_code == 201, reenrolled.text
    assert reenrolled.json()["member_id"] == enrolled["member_id"]
    assert reenrolled.json()["device_id"] != enrolled["device_id"]
    assert hub["client"].get(
        "/v1/contributors", headers=auth(reenrolled.json()["device_token"])
    ).status_code == 200


def test_admin_listings_expose_ids_but_never_tokens_or_hashes(hub):
    enrolled = enroll_friend(hub)
    db = hub["database"].session()
    members = list_members(db)
    devices = list_devices(db)
    db.close()
    assert any(item["public_id"] == enrolled["member_id"] for item in members)
    assert any(item["public_id"] == enrolled["device_id"] for item in devices)
    serialized = repr({"members": members, "devices": devices})
    assert enrolled["device_token"] not in serialized
    assert "token_hash" not in serialized


def test_sync_interlock_rolls_back_before_commit(hub):
    enrolled = enroll_friend(hub)
    db = hub["database"].session()
    member = db.scalar(select(Member).where(Member.public_id == enrolled["member_id"]))
    assert member is not None
    latch = AnalysisInterlock()
    checks = 0

    def trip_on_precommit() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            latch.trip("test runtime detection")
        latch.ensure_allowed()

    with pytest.raises(HTTPException) as caught:
        sync_tournament(
            db,
            member.id,
            SyncTournamentRequest.model_validate(tournament_payload()),
            ensure_allowed=trip_on_precommit,
        )
    assert caught.value.status_code == 503
    assert db.scalar(select(SharedTournament)) is None
    db.close()


def test_member_quota_rejects_new_key_but_allows_idempotent_retry(hub):
    enrolled = enroll_friend(hub)
    headers = auth(enrolled["device_token"])
    first = hub["client"].post(
        "/v1/sync/tournaments", json=tournament_payload(), headers=headers
    )
    assert first.status_code == 201
    low_quota = replace(get_hub_config(), max_tournaments_per_member=1)
    quota_app = create_hub_app(
        hub["database"],
        docs_enabled=False,
        trusted_hosts=("testserver",),
        interlock=AnalysisInterlock(),
        hub_config=low_quota,
    )
    with TestClient(quota_app) as quota_client:
        retry = quota_client.post(
            "/v1/sync/tournaments", json=tournament_payload(), headers=headers
        )
        assert retry.status_code == 200
        over_quota = quota_client.post(
            "/v1/sync/tournaments",
            json={
                **tournament_payload("d" * 64),
                "tournament": {
                    **tournament_payload("d" * 64)["tournament"],
                    "started_at": "2025-01-03T19:00:00+00:00",
                    "ended_at": "2025-01-03T19:10:00+00:00",
                    "hands": [
                        {
                            **tournament_payload("d" * 64)["tournament"]["hands"][0],
                            "played_at": "2025-01-03T19:01:00+00:00",
                        }
                    ],
                },
            },
            headers=headers,
        )
        assert over_quota.status_code == 507


def test_receipt_alias_quota_bounds_device_namespace_deduplication(hub):
    enrolled = enroll_friend(hub)
    headers = auth(enrolled["device_token"])
    assert hub["client"].post(
        "/v1/sync/tournaments", json=tournament_payload(), headers=headers
    ).status_code == 201
    low_receipt_quota = replace(get_hub_config(), max_receipts_per_tournament=1)
    quota_app = create_hub_app(
        hub["database"],
        docs_enabled=False,
        trusted_hosts=("testserver",),
        interlock=AnalysisInterlock(),
        hub_config=low_receipt_quota,
    )
    second_namespace = tournament_payload("f" * 64)
    with TestClient(quota_app) as quota_client:
        blocked = quota_client.post(
            "/v1/sync/tournaments", json=second_namespace, headers=headers
        )
    assert blocked.status_code == 507
    db = hub["database"].session()
    assert int(db.scalar(select(func.count(SyncReceipt.id))) or 0) == 1
    db.close()


def test_hub_data_directory_rejects_unc_and_onedrive():
    with pytest.raises(ValueError, match="UNC"):
        get_hub_config({"WXA_HUB_DATA_DIR": r"\\server\share\hub-data"})
    with pytest.raises(ValueError, match="OneDrive"):
        get_hub_config({"WXA_HUB_DATA_DIR": r"C:\Users\Alice\OneDrive\hub-data"})


def test_enrollment_rate_limit_uses_direct_peer_and_ignores_forwarded_ip(hub):
    limited_config = replace(get_hub_config(), rate_limit_enroll_per_minute=2)
    limited_app = create_hub_app(
        hub["database"],
        docs_enabled=False,
        trusted_hosts=("testserver",),
        interlock=AnalysisInterlock(),
        hub_config=limited_config,
    )
    with TestClient(limited_app) as client:
        first = client.post(
            "/v1/enroll", json={}, headers={"X-Forwarded-For": "198.51.100.1"}
        )
        second = client.post(
            "/v1/enroll", json={}, headers={"X-Forwarded-For": "198.51.100.2"}
        )
        blocked = client.post(
            "/v1/enroll", json={}, headers={"X-Forwarded-For": "198.51.100.3"}
        )
    assert first.status_code == 422
    assert second.status_code == 422
    assert blocked.status_code == 429
    assert blocked.headers["cache-control"] == "no-store"
    assert 1 <= int(blocked.headers["retry-after"]) <= 60


def test_sync_rate_limit_allows_normal_idempotent_retry_then_returns_429(hub):
    enrolled = enroll_friend(hub)
    headers = auth(enrolled["device_token"])
    limited_config = replace(get_hub_config(), rate_limit_sync_per_minute=2)
    limited_app = create_hub_app(
        hub["database"],
        docs_enabled=False,
        trusted_hosts=("testserver",),
        interlock=AnalysisInterlock(),
        hub_config=limited_config,
    )
    with TestClient(limited_app) as client:
        created = client.post("/v1/sync/tournaments", json=tournament_payload(), headers=headers)
        retry = client.post("/v1/sync/tournaments", json=tournament_payload(), headers=headers)
        blocked = client.post("/v1/sync/tournaments", json=tournament_payload(), headers=headers)
    assert created.status_code == 201
    assert retry.status_code == 200
    assert retry.json()["status"] == "existing"
    assert blocked.status_code == 429
    assert blocked.headers["cache-control"] == "no-store"
    assert blocked.headers["retry-after"]


def test_other_api_rate_limit_is_per_direct_peer(hub):
    enrolled = enroll_friend(hub)
    headers = {**auth(enrolled["device_token"]), "X-Forwarded-For": "203.0.113.1"}
    limited_config = replace(get_hub_config(), rate_limit_other_per_minute=1)
    limited_app = create_hub_app(
        hub["database"],
        docs_enabled=False,
        trusted_hosts=("testserver",),
        interlock=AnalysisInterlock(),
        hub_config=limited_config,
    )
    with TestClient(limited_app) as client:
        assert client.get("/v1/me", headers=headers).status_code == 200
        headers["X-Forwarded-For"] = "203.0.113.2"
        blocked = client.get("/v1/me", headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers["cache-control"] == "no-store"


def test_rate_limiter_bucket_storage_is_bounded_and_cleans_expired_entries():
    now = 100.0

    def clock() -> float:
        return now

    limiter = InMemoryRateLimiter(max_buckets=2, window_seconds=60, clock=clock)
    assert limiter.check("one", 10).allowed is True
    assert limiter.check("two", 10).allowed is True
    denied = limiter.check("three", 10)
    assert denied.allowed is False
    assert limiter.bucket_count == 2
    now += 61
    assert limiter.check("three", 10).allowed is True
    assert limiter.bucket_count == 1


def test_runner_guard_precedes_database_initialization(tmp_path):
    database_called = False

    def forbidden_database(_path):
        nonlocal database_called
        database_called = True
        raise AssertionError("database must not be constructed")

    exit_code = run(
        [],
        environ={
            **APPROVAL_ENV,
            "WXA_HUB_DATA_DIR": str(tmp_path / "must-not-exist"),
        },
        detector=lambda: True,
        database_factory=forbidden_database,
    )
    assert exit_code == SAFETY_EXIT_CODE
    assert not database_called
    assert not (tmp_path / "must-not-exist").exists()


def test_runtime_guard_requests_server_shutdown_without_restart(tmp_path):
    probe_results = iter((False, False, False, False, True))
    servers = []

    def detector() -> bool:
        return next(probe_results, True)

    class FakeServer:
        def __init__(self, _config) -> None:
            self.should_exit = False
            self.run_count = 0
            servers.append(self)

        def run(self) -> None:
            self.run_count += 1
            deadline = time.monotonic() + 2
            while not self.should_exit and time.monotonic() < deadline:
                time.sleep(0.01)

    exit_code = run(
        [],
        environ={
            **APPROVAL_ENV,
            "WXA_HUB_DATA_DIR": str(tmp_path / "runtime-hub"),
        },
        detector=detector,
        server_factory=FakeServer,
    )
    assert exit_code == SAFETY_EXIT_CODE
    assert len(servers) == 1
    assert servers[0].should_exit is True
    assert servers[0].run_count == 1


def test_non_loopback_binding_requires_tls():
    with pytest.raises(Exception, match="TLS"):
        validate_tls_binding("0.0.0.0", None, None)
    assert validate_tls_binding("127.0.0.1", None, None) == (None, None)

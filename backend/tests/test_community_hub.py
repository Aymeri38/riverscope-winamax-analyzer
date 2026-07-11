from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import base64
import json
from pathlib import Path
import time

import pytest
import httpx
from fastapi.testclient import TestClient
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from app.community_hub.admin import (
    AdminError,
    bootstrap_owner,
    create_invite,
    delete_member,
    list_devices,
    list_members,
    purge_opponents,
    revoke,
    suppress_opponent_by_public_id,
)
from app.community_hub.api import create_hub_app
from app.community_hub.config import MAX_BODY_BYTES, get_hub_config
from app.community_hub.database import HubBase, HubDatabase
from app.community_hub.models import (
    Device,
    Invite,
    Member,
    Opponent,
    OpponentSuppression,
    OpponentSyncReceipt,
    SharedHand,
    SharedOpponentObservation,
    SharedTournament,
    SharedTournamentOpponent,
    SyncReceipt,
)
from app.community_hub.opponent_identity import OpponentIdentityError, OpponentIdentityService
from app.community_hub.rate_limit import InMemoryRateLimiter
from app.community_hub.runner import run, validate_tls_binding
from app.community_hub.schemas import OpponentSyncRequest, SyncTournamentRequest
from app.community_hub.opponents import sync_tournament_opponents
from app.community_hub.service import sync_tournament
from app.core.process_guard import (
    AnalysisForbiddenError,
    AnalysisInterlock,
    SAFETY_EXIT_CODE,
)
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


def opponent_payload(
    first_name: str = "Opponent Alpha",
    second_name: str = "Opponent Beta",
) -> dict:
    return {
        "schema_version": "1",
        "opponents": [
            {
                "alias": "OPPONENT_1",
                "display_name": first_name,
                "final_rank": 2,
                "reward": 0,
                "starting_stack": 500,
                "final_stack": 480,
            },
            {
                "alias": "OPPONENT_2",
                "display_name": second_name,
                "final_rank": 3,
                "reward": 0,
                "starting_stack": 500,
                "final_stack": 480,
            },
        ],
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


@pytest.fixture
def tracking_hub(tmp_path):
    environment = {
        "WXA_HUB_DATA_DIR": str(tmp_path / "tracking-hub"),
        "WXA_HUB_OPPONENT_TRACKING": "YES",
        "WXA_HUB_OPPONENT_IDENTITY_KEY": base64.b64encode(b"i" * 32).decode(),
        "WXA_HUB_OPPONENT_ENCRYPTION_KEY": base64.b64encode(b"e" * 32).decode(),
    }
    config = get_hub_config(environment)
    database = HubDatabase(config.database_path)
    database.initialize()
    db = database.session()
    owner, _owner_device, owner_token = bootstrap_owner(
        db, display_name="Owner", device_label="Owner PC"
    )
    invite, invite_token = create_invite(db, expires_hours=24)
    db.close()
    app = create_hub_app(
        database,
        docs_enabled=False,
        trusted_hosts=("testserver", "localhost"),
        interlock=AnalysisInterlock(),
        hub_config=config,
    )
    with TestClient(app) as client:
        yield {
            "client": client,
            "database": database,
            "app": app,
            "config": config,
            "owner": owner,
            "owner_token": owner_token,
            "invite": invite,
            "invite_token": invite_token,
        }
    database.dispose()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def enroll_friend(hub, name: str = "Alice", policy_version: str = "1") -> dict:
    response = hub["client"].post(
        "/v1/enroll",
        json={
            "invite_token": hub["invite_token"],
            "display_name": name,
            "device_label": f"PC {name}",
            "policy_version": policy_version,
            "consent": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def enroll_additional_friend(hub, name: str, policy_version: str = "1") -> dict:
    db = hub["database"].session()
    _invite, invite_token = create_invite(db, expires_hours=24)
    db.close()
    response = hub["client"].post(
        "/v1/enroll",
        json={
            "invite_token": invite_token,
            "display_name": name,
            "device_label": f"PC {name}",
            "policy_version": policy_version,
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
        "opponents",
        "opponent_suppressions",
        "opponent_sync_receipts",
        "shared_tournament_opponents",
        "shared_opponent_observations",
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


def test_v2_enrollment_fails_without_server_tracking_before_invite_mutation(hub):
    response = hub["client"].post(
        "/v1/enroll",
        json={
            "invite_token": hub["invite_token"],
            "display_name": "V2 member",
            "device_label": "V2 PC",
            "policy_version": "2",
            "consent": True,
        },
    )
    assert response.status_code == 503
    db = hub["database"].session()
    invite = db.scalar(select(Invite).where(Invite.public_id == hub["invite"].public_id))
    assert invite is not None and invite.used_at is None
    assert db.scalar(select(Member.id).where(Member.display_name == "V2 member")) is None
    db.close()


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
        "policy_version": "1",
        "opponent_tracking_required": False,
    }
    response = hub["client"].get(
        "/v1/dashboard", headers=auth(enrolled["device_token"])
    )
    assert response.status_code == 403
    assert "Synchronisez" in response.json()["detail"]
    profile = hub["client"].get(
        f"/v1/contributors/{enrolled['member_id']}/profile",
        headers=auth(enrolled["device_token"]),
    )
    assert profile.status_code == 403
    assert "Synchronisez" in profile.json()["detail"]
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


def test_contributor_profile_is_complete_private_and_member_isolated(hub):
    alice = enroll_friend(hub)
    alice_headers = auth(alice["device_token"])
    first = tournament_payload("1" * 64)
    assert hub["client"].post(
        "/v1/sync/tournaments", json=first, headers=alice_headers
    ).status_code == 201

    second = tournament_payload("2" * 64)
    second_started = datetime(2025, 1, 3, 19, 0, tzinfo=UTC)
    second["tournament"].update(
        {
            "started_at": second_started.isoformat(),
            "ended_at": (second_started + timedelta(minutes=5)).isoformat(),
            "total_buyin": 5.0,
            "multiplier": 2.0,
            "prize_pool": 10.0,
            "reward": 0.0,
            "final_rank": 3,
            "duration_seconds": 300,
            "chip_delta": None,
        }
    )
    second["tournament"]["hands"][0]["played_at"] = (
        second_started + timedelta(minutes=1)
    ).isoformat()
    assert hub["client"].post(
        "/v1/sync/tournaments", json=second, headers=alice_headers
    ).status_code == 201

    bob = enroll_additional_friend(hub, "Bob")
    bob_payload = tournament_payload("3" * 64)
    bob_payload["tournament"].update(
        {
            "total_buyin": 100.0,
            "prize_pool": 300.0,
            "reward": 300.0,
        }
    )
    bob_headers = auth(bob["device_token"])
    assert hub["client"].post(
        "/v1/sync/tournaments", json=bob_payload, headers=bob_headers
    ).status_code == 201

    response = hub["client"].get(
        f"/v1/contributors/{alice['member_id']}/profile", headers=bob_headers
    )
    assert response.status_code == 200, response.text
    profile = response.json()
    assert profile["contributor"]["public_id"] == alice["member_id"]
    assert profile["contributor"]["display_name"] == "Alice"
    assert profile["summary"] == {
        "games": 2,
        "hands": 2,
        "currency": "EUR",
        "total_buyins": 7.0,
        "total_winnings": 6.0,
        "net_result": -1.0,
        "roi_percent": pytest.approx(-100 / 7),
        "wins": 1,
        "second_places": 0,
        "third_places": 1,
        "win_rate_percent": 50.0,
        "second_place_percent": 0.0,
        "third_place_percent": 50.0,
        "itm_count": 1,
        "itm_percent": 50.0,
        "average_buyin": 3.5,
        "average_winnings": 3.0,
        "average_net": -0.5,
        "average_duration_seconds": 450.0,
        "average_hands": 1.0,
        "chip_ev_per_game": 1000.0,
        "chip_ev_games": 1,
        "chip_ev_coverage_percent": 50.0,
        "first_game_at": "2025-01-02T19:00:00Z",
        "last_game_at": "2025-01-03T19:00:00Z",
    }
    assert [(row["buyin"], row["games"]) for row in profile["by_limit"]] == [
        (2.0, 1),
        (5.0, 1),
    ]
    assert [row["multiplier"] for row in profile["by_multiplier"]] == [2.0, 3.0]
    assert [row["net_result"] for row in profile["trend"]] == [4.0, -5.0]
    assert [row["cumulative_net"] for row in profile["trend"]] == [4.0, -1.0]
    assert [row["total_buyin"] for row in profile["recent_tournaments"]] == [5.0, 2.0]

    serialized = json.dumps(profile)
    assert bob["member_id"] not in serialized
    assert "Bob" not in serialized
    assert "OPPONENT_" not in serialized

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value), set())
        return set()

    assert keys(profile).isdisjoint(
        {
            "alias",
            "players",
            "player_id",
            "opponent",
            "opponents",
            "replay",
            "actions",
            "hero_cards",
            "board",
        }
    )

    unknown = hub["client"].get(
        "/v1/contributors/does-not-exist/profile", headers=bob_headers
    )
    assert unknown.status_code == 404
    # An enrolled account without a contribution is not publicly discoverable.
    not_yet_contributor = hub["client"].get(
        f"/v1/contributors/{hub['owner'].public_id}/profile", headers=bob_headers
    )
    assert not_yet_contributor.status_code == 404


def test_contributor_profile_recent_tournaments_is_capped_at_ten(hub):
    enrolled = enroll_friend(hub)
    headers = auth(enrolled["device_token"])
    base = datetime(2025, 2, 1, 19, 0, tzinfo=UTC)
    for index in range(11):
        payload = tournament_payload(f"{index + 1:064x}")
        started = base + timedelta(days=index)
        payload["tournament"]["started_at"] = started.isoformat()
        payload["tournament"]["ended_at"] = (started + timedelta(minutes=10)).isoformat()
        payload["tournament"]["hands"][0]["played_at"] = (
            started + timedelta(minutes=1)
        ).isoformat()
        assert hub["client"].post(
            "/v1/sync/tournaments", json=payload, headers=headers
        ).status_code == 201

    profile = hub["client"].get(
        f"/v1/contributors/{enrolled['member_id']}/profile", headers=headers
    )
    assert profile.status_code == 200, profile.text
    recent = profile.json()["recent_tournaments"]
    assert len(recent) == 10
    assert recent[0]["started_at"] == "2025-02-11T19:00:00Z"
    assert recent[-1]["started_at"] == "2025-02-02T19:00:00Z"


def test_contributor_profile_never_adds_different_currencies(hub):
    enrolled = enroll_friend(hub)
    headers = auth(enrolled["device_token"])
    eur = tournament_payload("4" * 64)
    usd = tournament_payload("5" * 64)
    usd["tournament"]["currency"] = "USD"
    for payload in (eur, usd):
        assert hub["client"].post(
            "/v1/sync/tournaments", json=payload, headers=headers
        ).status_code == 201

    response = hub["client"].get(
        f"/v1/contributors/{enrolled['member_id']}/profile", headers=headers
    )
    assert response.status_code == 200, response.text
    profile = response.json()
    assert profile["summary"]["games"] == 2
    assert profile["summary"]["currency"] is None
    for field in (
        "total_buyins",
        "total_winnings",
        "net_result",
        "roi_percent",
        "average_buyin",
        "average_winnings",
        "average_net",
    ):
        assert profile["summary"][field] is None
    assert [row["currency"] for row in profile["by_currency"]] == ["EUR", "USD"]
    assert [row["net_result"] for row in profile["by_currency"]] == [4.0, 4.0]
    assert [(row["currency"], row["cumulative_net"]) for row in profile["trend"]] == [
        ("EUR", 4.0),
        ("USD", 4.0),
    ]


def test_tracking_configuration_is_fail_closed_before_database_mutation(tmp_path):
    base = {
        "WXA_HUB_DATA_DIR": str(tmp_path / "must-not-exist"),
        "WXA_HUB_OPPONENT_TRACKING": "YES",
    }
    with pytest.raises(ValueError, match="OPPONENT_IDENTITY_KEY"):
        get_hub_config(base)
    assert not (tmp_path / "must-not-exist").exists()
    invalid = {
        **base,
        "WXA_HUB_OPPONENT_IDENTITY_KEY": base64.b64encode(b"short").decode(),
        "WXA_HUB_OPPONENT_ENCRYPTION_KEY": base64.b64encode(b"e" * 32).decode(),
    }
    with pytest.raises(ValueError, match="32 octets"):
        get_hub_config(invalid)
    same_key = base64.b64encode(b"s" * 32).decode()
    with pytest.raises(ValueError, match="distinctes"):
        get_hub_config(
            {
                **base,
                "WXA_HUB_OPPONENT_IDENTITY_KEY": same_key,
                "WXA_HUB_OPPONENT_ENCRYPTION_KEY": same_key,
            }
        )


def test_create_hub_app_refuses_blocked_interlock_before_opponent_scan(tracking_hub):
    interlock = AnalysisInterlock()
    interlock.trip("Winamax detected during startup")

    with pytest.raises(AnalysisForbiddenError):
        create_hub_app(
            tracking_hub["database"],
            docs_enabled=False,
            trusted_hosts=("testserver",),
            interlock=interlock,
            hub_config=tracking_hub["config"],
        )


def test_opponent_identity_normalizes_exactly_and_encrypts_with_authenticated_aad():
    service = OpponentIdentityService(
        identity_key=b"i" * 32,
        encryption_key=b"e" * 32,
        key_version=1,
    )
    display, first_key = service.identity_for("  A\u030Alice  ")
    _same_display, same_key = service.identity_for("ÅLICE")
    _different_display, different_key = service.identity_for("ÅLICE!")
    assert display == "Ålice"
    assert first_key == same_key
    assert first_key != different_key
    encrypted = service.encrypt("Sensitive Alias")
    assert b"Sensitive Alias" not in encrypted.ciphertext
    assert service.decrypt(
        identity_key=encrypted.identity_key,
        ciphertext=encrypted.ciphertext,
        nonce=encrypted.nonce,
        key_version=encrypted.key_version,
    ) == "Sensitive Alias"
    with pytest.raises(OpponentIdentityError):
        service.decrypt(
            identity_key="0" * 64,
            ciphertext=encrypted.ciphertext,
            nonce=encrypted.nonce,
            key_version=encrypted.key_version,
        )


def test_opponent_consent_enrichment_crypto_idempotence_and_profile(
    tracking_hub, caplog
):
    client = tracking_hub["client"]
    legacy = enroll_friend(tracking_hub, policy_version="1")
    legacy_headers = auth(legacy["device_token"])
    core = client.post(
        "/v1/sync/tournaments", json=tournament_payload(), headers=legacy_headers
    )
    assert core.status_code == 201
    tournament_id = core.json()["public_id"]
    assert client.get("/v1/contributors", headers=legacy_headers).status_code == 403
    me = client.get("/v1/me", headers=legacy_headers).json()
    assert me["policy_version"] == "1"
    assert me["opponent_tracking_required"] is True
    upgraded = client.post(
        "/v1/consent",
        json={"consent": True, "policy_version": "2"},
        headers=legacy_headers,
    )
    assert upgraded.status_code == 200
    assert client.get("/v1/contributors", headers=legacy_headers).status_code == 403

    raw_first = "SQLite-Plaintext-Canary"
    raw_second = "Second Opponent"
    payload = opponent_payload(raw_first, raw_second)
    created = client.post(
        f"/v1/sync/tournaments/{tournament_id}/opponents",
        json=payload,
        headers=legacy_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json() == {
        "status": "created",
        "opponent_count": 2,
        "observation_count": 2,
    }
    repeated = client.post(
        f"/v1/sync/tournaments/{tournament_id}/opponents",
        json=payload,
        headers=legacy_headers,
    )
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "existing"
    changed = opponent_payload(raw_first + " changed", raw_second)
    conflict = client.post(
        f"/v1/sync/tournaments/{tournament_id}/opponents",
        json=changed,
        headers=legacy_headers,
    )
    assert conflict.status_code == 409
    assert raw_first not in conflict.text
    assert client.get("/v1/contributors", headers=legacy_headers).status_code == 200

    listing = client.get("/v1/opponents?limit=50&offset=0", headers=legacy_headers)
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    assert {item["display_name"] for item in items} == {raw_first, raw_second}
    first = next(item for item in items if item["display_name"] == raw_first)
    profile = client.get(
        f"/v1/opponents/{first['public_id']}/profile", headers=legacy_headers
    )
    assert profile.status_code == 200, profile.text
    data = profile.json()
    assert data["identity"]["display_name"] == raw_first
    assert data["summary"]["hands"] == 1
    assert data["summary"]["net_chips"] == -20
    assert data["summary"]["preflop_known_hands"] == 0
    assert data["summary"]["vpip"] == {
        "made": 0,
        "opportunities": 0,
        "percent": None,
    }
    assert data["summary"]["three_bet"]["opportunities"] == 0
    assert data["summary"]["wtsd"]["opportunities"] == 1
    assert data["recent_observations"][0]["net"] == -20
    assert data["recent_observations"][0]["preflop_known"] is False
    assert "final_rank" not in json.dumps(data)
    assert "reward" not in json.dumps(data)

    db = tracking_hub["database"].session()
    stored = db.scalar(select(Opponent).where(Opponent.public_id == first["public_id"]))
    assert stored is not None
    assert raw_first.encode() not in stored.display_ciphertext
    assert len(stored.display_nonce) == 12
    db.close()
    for path in (
        tracking_hub["database"].database_path,
        Path(str(tracking_hub["database"].database_path) + "-wal"),
        Path(str(tracking_hub["database"].database_path) + "-shm"),
    ):
        if path.exists():
            assert raw_first.encode() not in path.read_bytes()
    assert raw_first not in caplog.text
    wrong_config = get_hub_config(
        {
            "WXA_HUB_DATA_DIR": str(tracking_hub["config"].data_dir),
            "WXA_HUB_OPPONENT_TRACKING": "YES",
            "WXA_HUB_OPPONENT_IDENTITY_KEY": base64.b64encode(b"i" * 32).decode(),
            "WXA_HUB_OPPONENT_ENCRYPTION_KEY": base64.b64encode(b"x" * 32).decode(),
        }
    )
    with pytest.raises(ValueError, match="incompatible"):
        create_hub_app(
            tracking_hub["database"],
            docs_enabled=False,
            trusted_hosts=("testserver",),
            interlock=AnalysisInterlock(),
            hub_config=wrong_config,
        )
    verification_db = tracking_hub["database"].session()
    assert int(verification_db.scalar(select(func.count(Opponent.id))) or 0) == 2
    verification_db.close()


def test_opponent_interlock_trip_before_commit_rolls_back_every_identity(tracking_hub):
    enrolled = enroll_friend(tracking_hub, policy_version="2")
    headers = auth(enrolled["device_token"])
    core = tracking_hub["client"].post(
        "/v1/sync/tournaments", json=tournament_payload(), headers=headers
    ).json()
    db = tracking_hub["database"].session()
    member = db.scalar(select(Member).where(Member.public_id == enrolled["member_id"]))
    assert member is not None
    calls = 0

    def trip_before_commit() -> None:
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise AnalysisForbiddenError("synthetic safety trip")

    request = OpponentSyncRequest.model_validate(opponent_payload())
    with pytest.raises(HTTPException) as failure:
        sync_tournament_opponents(
            db,
            member_id=member.id,
            tournament_public_id=core["public_id"],
            request=request,
            identity_service=tracking_hub["app"].state.opponent_identity_service,
            ensure_allowed=trip_before_commit,
        )
    assert failure.value.status_code == 503
    assert int(db.scalar(select(func.count(Opponent.id))) or 0) == 0
    assert int(db.scalar(select(func.count(SharedTournamentOpponent.id))) or 0) == 0
    assert int(db.scalar(select(func.count(SharedOpponentObservation.id))) or 0) == 0
    assert int(db.scalar(select(func.count(OpponentSyncReceipt.id))) or 0) == 0
    db.close()


def test_opponent_enrichment_ownership_recency_and_name_errors_are_private(
    tracking_hub, caplog
):
    alice = enroll_friend(tracking_hub, policy_version="2")
    headers = auth(alice["device_token"])
    core = tracking_hub["client"].post(
        "/v1/sync/tournaments", json=tournament_payload(), headers=headers
    ).json()
    bob = enroll_additional_friend(tracking_hub, "Bob", policy_version="2")
    bob_headers = auth(bob["device_token"])
    bob_core = tournament_payload("b" * 64)
    assert tracking_hub["client"].post(
        "/v1/sync/tournaments", json=bob_core, headers=bob_headers
    ).status_code == 201
    stolen = tracking_hub["client"].post(
        f"/v1/sync/tournaments/{core['public_id']}/opponents",
        json=opponent_payload(),
        headers=bob_headers,
    )
    assert stolen.status_code == 404

    invalid_name = "Private-Name-Canary\u202e"
    invalid = tracking_hub["client"].post(
        f"/v1/sync/tournaments/{core['public_id']}/opponents",
        json=opponent_payload(invalid_name, "Valid Name"),
        headers=headers,
    )
    assert invalid.status_code == 422
    assert "Private-Name-Canary" not in invalid.text
    assert "Private-Name-Canary" not in caplog.text

    db = tracking_hub["database"].session()
    tournament = db.scalar(
        select(SharedTournament)
        .where(SharedTournament.public_id == core["public_id"])
        .options(selectinload(SharedTournament.hands))
    )
    assert tournament is not None
    recent = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=30)
    tournament.ended_at = recent
    for hand in tournament.hands:
        hand.played_at = recent
    db.commit()
    db.close()
    too_recent = tracking_hub["client"].post(
        f"/v1/sync/tournaments/{core['public_id']}/opponents",
        json=opponent_payload(),
        headers=headers,
    )
    assert too_recent.status_code == 409


def test_opponent_normalization_suppression_revocation_and_cascades(tracking_hub):
    client = tracking_hub["client"]
    alice = enroll_friend(tracking_hub, policy_version="2")
    headers = auth(alice["device_token"])
    core = client.post(
        "/v1/sync/tournaments", json=tournament_payload(), headers=headers
    ).json()
    assert client.post(
        f"/v1/sync/tournaments/{core['public_id']}/opponents",
        json=opponent_payload("Alice", "Case Name"),
        headers=headers,
    ).status_code == 201
    db = tracking_hub["database"].session()
    # A contributor and an opponent with the same display value remain wholly
    # separate models; there is no automatic identity link.
    member = db.scalar(select(Member).where(Member.public_id == alice["member_id"]))
    opponent = db.scalar(select(Opponent).order_by(Opponent.id))
    assert member is not None and opponent is not None
    assert not hasattr(opponent, "member_id")
    opponent_id = opponent.public_id
    db.close()

    db = tracking_hub["database"].session()
    suppress_opponent_by_public_id(db, public_id=opponent_id, confirmation="DELETE")
    assert db.scalar(select(Opponent).where(Opponent.public_id == opponent_id)) is None
    assert int(db.scalar(select(func.count(OpponentSuppression.id))) or 0) == 1
    assert int(db.scalar(select(func.count(SharedTournamentOpponent.id))) or 0) == 1
    assert int(db.scalar(select(func.count(SharedOpponentObservation.id))) or 0) == 1
    db.close()

    bob = enroll_additional_friend(tracking_hub, "Bob", policy_version="2")
    bob_headers = auth(bob["device_token"])
    bob_payload = tournament_payload("c" * 64)
    bob_payload["tournament"]["started_at"] = datetime(
        2025, 1, 4, 19, 0, tzinfo=UTC
    ).isoformat()
    bob_payload["tournament"]["ended_at"] = datetime(
        2025, 1, 4, 19, 10, tzinfo=UTC
    ).isoformat()
    bob_payload["tournament"]["hands"][0]["played_at"] = datetime(
        2025, 1, 4, 19, 1, tzinfo=UTC
    ).isoformat()
    bob_core = client.post(
        "/v1/sync/tournaments", json=bob_payload, headers=bob_headers
    ).json()
    assert client.post(
        f"/v1/sync/tournaments/{bob_core['public_id']}/opponents",
        json=opponent_payload("  ALICE  ", "Bob Unique"),
        headers=bob_headers,
    ).status_code == 201
    db = tracking_hub["database"].session()
    # The suppressed normalized HMAC cannot be recreated; only Bob Unique is new.
    assert int(db.scalar(select(func.count(Opponent.id))) or 0) == 2
    revoke(db, kind="member", public_id=bob["member_id"])
    db.close()
    visible = client.get("/v1/opponents", headers=headers).json()["items"]
    assert all(item["display_name"] != "Bob Unique" for item in visible)


def test_opponent_metrics_use_real_opportunities_and_aggregate_contributors(tracking_hub):
    client = tracking_hub["client"]
    alice = enroll_friend(tracking_hub, policy_version="2")
    alice_headers = auth(alice["device_token"])
    payload = tournament_payload("6" * 64)
    payload["tournament"]["hands"][0]["players"][1].update(
        {"showed": True, "is_winner": True, "won": 500, "net": 450}
    )
    payload["tournament"]["hands"][0]["actions"] = [
        {"sequence": 1, "actor_alias": "OPPONENT_1", "street": "PREFLOP", "action_type": "POST_SB", "amount": 10, "to_amount": 10, "pot_after": 10, "is_all_in": False},
        {"sequence": 2, "actor_alias": "OPPONENT_2", "street": "PREFLOP", "action_type": "POST_BB", "amount": 20, "to_amount": 20, "pot_after": 30, "is_all_in": False},
        {"sequence": 3, "actor_alias": "HERO", "street": "PREFLOP", "action_type": "RAISE", "amount": 50, "to_amount": 50, "pot_after": 80, "is_all_in": False},
        {"sequence": 4, "actor_alias": "OPPONENT_1", "street": "PREFLOP", "action_type": "RAISE", "amount": 140, "to_amount": 150, "pot_after": 220, "is_all_in": False},
        {"sequence": 5, "actor_alias": "OPPONENT_2", "street": "PREFLOP", "action_type": "FOLD", "amount": None, "to_amount": None, "pot_after": 220, "is_all_in": False},
        {"sequence": 6, "actor_alias": "HERO", "street": "PREFLOP", "action_type": "CALL", "amount": 100, "to_amount": 150, "pot_after": 320, "is_all_in": False},
        {"sequence": 7, "actor_alias": "OPPONENT_1", "street": "FLOP", "action_type": "BET", "amount": 100, "to_amount": 100, "pot_after": 420, "is_all_in": False},
        {"sequence": 8, "actor_alias": "HERO", "street": "FLOP", "action_type": "CALL", "amount": 100, "to_amount": 100, "pot_after": 520, "is_all_in": False},
        {"sequence": 9, "actor_alias": "OPPONENT_1", "street": "TURN", "action_type": "CHECK", "amount": None, "to_amount": None, "pot_after": 520, "is_all_in": False},
        {"sequence": 10, "actor_alias": "HERO", "street": "TURN", "action_type": "CHECK", "amount": None, "to_amount": None, "pot_after": 520, "is_all_in": False},
        {"sequence": 11, "actor_alias": "OPPONENT_1", "street": "SHOWDOWN", "action_type": "SHOW", "amount": None, "to_amount": None, "pot_after": 520, "is_all_in": False},
    ]
    core = client.post("/v1/sync/tournaments", json=payload, headers=alice_headers).json()
    assert client.post(
        f"/v1/sync/tournaments/{core['public_id']}/opponents",
        json=opponent_payload("Shared Identity", "Folded Identity"),
        headers=alice_headers,
    ).status_code == 201
    listing = client.get("/v1/opponents", headers=alice_headers).json()["items"]
    shared = next(item for item in listing if item["display_name"] == "Shared Identity")
    folded = next(item for item in listing if item["display_name"] == "Folded Identity")
    shared_profile = client.get(
        f"/v1/opponents/{shared['public_id']}/profile", headers=alice_headers
    ).json()
    assert shared_profile["summary"]["vpip"] == {
        "made": 1,
        "opportunities": 1,
        "percent": 100.0,
    }
    assert shared_profile["summary"]["preflop_known_hands"] == 1
    assert shared_profile["summary"]["three_bet"] == {
        "made": 1,
        "opportunities": 1,
        "percent": 100.0,
    }
    assert shared_profile["summary"]["aggression"] == {
        "aggressive_actions": 1,
        "calls": 0,
        "checks": 1,
        "folds": 0,
        "opportunities": 2,
        "frequency_percent": 50.0,
        "factor": None,
    }
    folded_profile = client.get(
        f"/v1/opponents/{folded['public_id']}/profile", headers=alice_headers
    ).json()
    assert folded_profile["summary"]["three_bet"]["opportunities"] == 1
    assert folded_profile["summary"]["three_bet"]["made"] == 0

    bob = enroll_additional_friend(tracking_hub, "Bob", policy_version="2")
    bob_headers = auth(bob["device_token"])
    bob_payload = tournament_payload("7" * 64)
    started = datetime(2025, 1, 5, 19, 0, tzinfo=UTC)
    bob_payload["tournament"]["started_at"] = started.isoformat()
    bob_payload["tournament"]["ended_at"] = (started + timedelta(minutes=10)).isoformat()
    bob_payload["tournament"]["hands"][0]["played_at"] = (
        started + timedelta(minutes=1)
    ).isoformat()
    bob_core = client.post(
        "/v1/sync/tournaments", json=bob_payload, headers=bob_headers
    ).json()
    assert client.post(
        f"/v1/sync/tournaments/{bob_core['public_id']}/opponents",
        json=opponent_payload(" shared identity ", "Bob Other"),
        headers=bob_headers,
    ).status_code == 201
    aggregated = client.get(
        f"/v1/opponents/{shared['public_id']}/profile", headers=bob_headers
    ).json()
    assert aggregated["summary"]["contributors"] == 2
    assert aggregated["summary"]["tournaments"] == 2
    assert aggregated["summary"]["hands"] == 2


def test_additive_hub_initialization_preserves_v1_rows(tmp_path):
    database = HubDatabase(tmp_path / "legacy" / "community_hub.db")
    database.initialize()
    additive = {
        "opponents",
        "opponent_suppressions",
        "opponent_sync_receipts",
        "shared_tournament_opponents",
        "shared_opponent_observations",
    }
    with database.engine.begin() as connection:
        for table in (
            "shared_opponent_observations",
            "shared_tournament_opponents",
            "opponent_sync_receipts",
            "opponent_suppressions",
            "opponents",
        ):
            connection.execute(text(f"DROP TABLE {table}"))
        connection.execute(
            text(
                "INSERT INTO members "
                "(public_id,display_name,display_name_key,role,policy_version,consented_at,created_at) "
                "VALUES ('legacy-id','Legacy','legacy-key','member','1',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    database.initialize()
    db = database.session()
    assert db.scalar(select(Member.display_name).where(Member.public_id == "legacy-id")) == "Legacy"
    names = set(database.engine.dialect.get_table_names(db.connection()))
    assert additive <= names
    db.close()
    database.dispose()


def test_member_deletion_purges_orphan_opponents_and_retention_is_explicit(tracking_hub):
    client = tracking_hub["client"]
    alice = enroll_friend(tracking_hub, policy_version="2")
    headers = auth(alice["device_token"])
    core = client.post(
        "/v1/sync/tournaments", json=tournament_payload(), headers=headers
    ).json()
    assert client.post(
        f"/v1/sync/tournaments/{core['public_id']}/opponents",
        json=opponent_payload("Retention A", "Retention B"),
        headers=headers,
    ).status_code == 201
    db = tracking_hub["database"].session()
    for opponent in db.scalars(select(Opponent)):
        opponent.last_seen_at = datetime(2020, 1, 1)
    db.commit()
    assert purge_opponents(db, retention_days=365) == 2
    assert int(db.scalar(select(func.count(SharedTournamentOpponent.id))) or 0) == 0
    assert int(db.scalar(select(func.count(SharedOpponentObservation.id))) or 0) == 0
    # Retention is not an opt-out: it does not add permanent tombstones.
    assert int(db.scalar(select(func.count(OpponentSuppression.id))) or 0) == 0
    db.close()

    # Recreate identities on a fresh tournament, then deleting the sole source
    # must also remove the now-orphaned global identities.
    second = tournament_payload("8" * 64)
    started = datetime(2025, 1, 6, 19, 0, tzinfo=UTC)
    second["tournament"]["started_at"] = started.isoformat()
    second["tournament"]["ended_at"] = (started + timedelta(minutes=10)).isoformat()
    second["tournament"]["hands"][0]["played_at"] = (
        started + timedelta(minutes=1)
    ).isoformat()
    second_core = client.post(
        "/v1/sync/tournaments", json=second, headers=headers
    ).json()
    assert client.post(
        f"/v1/sync/tournaments/{second_core['public_id']}/opponents",
        json=opponent_payload("Delete A", "Delete B"),
        headers=headers,
    ).status_code == 201
    db = tracking_hub["database"].session()
    delete_member(db, public_id=alice["member_id"], confirmation="DELETE")
    assert int(db.scalar(select(func.count(Opponent.id))) or 0) == 0
    assert int(db.scalar(select(func.count(SharedTournamentOpponent.id))) or 0) == 0
    assert int(db.scalar(select(func.count(SharedOpponentObservation.id))) or 0) == 0
    db.close()


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


def test_real_local_client_delivers_separate_opponent_enrichment_end_to_end(
    db, tracking_hub
):
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
        upstream = tracking_hub["client"].request(
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
    joined = community.join(
        db,
        CommunityJoinRequest(
            hub_url="http://localhost",
            invite=tracking_hub["invite_token"],
            display_name="Alice",
            consent=True,
            consent_version="2",
        ),
    )
    assert joined["pending"] == 1
    result = community.sync(db)
    assert result.queued == 1
    assert result.synced == 2
    assert result.pending == 0
    assert result.available is True
    listing = community.proxy_get(db, "/v1/opponents")
    assert listing["total"] == 2
    assert all(item["display_name"] for item in listing["items"])
    hub_db = tracking_hub["database"].session()
    assert int(hub_db.scalar(select(func.count(Opponent.id))) or 0) == 2
    assert int(hub_db.scalar(select(func.count(SharedTournament.id))) or 0) == 1
    assert int(hub_db.scalar(select(func.count(SharedOpponentObservation.id))) or 0) == 12
    hub_db.close()
    assert community.leave(db) is True


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
    with pytest.raises(ValueError, match="OneDrive"):
        get_hub_config({"WXA_HUB_DATA_DIR": "/srv/OneDrive - Team/hub-data"})


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


def test_runner_rejects_missing_opponent_keys_before_database_initialization(tmp_path):
    database_called = False

    def forbidden_database(_path):
        nonlocal database_called
        database_called = True
        raise AssertionError("database must not be constructed")

    target = tmp_path / "missing-opponent-keys"
    exit_code = run(
        [],
        environ={
            **APPROVAL_ENV,
            "WXA_HUB_DATA_DIR": str(target),
            "WXA_HUB_OPPONENT_TRACKING": "YES",
        },
        detector=lambda: False,
        database_factory=forbidden_database,
    )
    assert exit_code == 2
    assert not database_called
    assert not target.exists()


def test_runtime_guard_requests_server_shutdown_without_restart(tmp_path):
    probe_results = iter((False, False, False, False, False, True))
    servers = []
    configs = []

    def detector() -> bool:
        return next(probe_results, True)

    class FakeServer:
        def __init__(self, config) -> None:
            self.should_exit = False
            self.run_count = 0
            configs.append(config)
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
    assert configs[0].proxy_headers is False


def test_non_loopback_binding_requires_tls():
    with pytest.raises(Exception, match="TLS"):
        validate_tls_binding("0.0.0.0", None, None)
    assert validate_tls_binding("127.0.0.1", None, None) == (None, None)

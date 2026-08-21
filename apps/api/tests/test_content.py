from __future__ import annotations

import datetime as dt

from elyon_api.services.schedule import overlaps, sort_schedules
from tests.conftest import (
    auth_json,
    bootstrap_superadmin,
    create_org,
    login,
    login_as_org_admin,
)


def _dt(hour: int) -> dt.datetime:
    return dt.datetime(2026, 8, 20, hour, tzinfo=dt.UTC)


def setup(client) -> dict:
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "ContCo")
    login_as_org_admin(client, org, "cont@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "Site 1"}).json()
    playlist = auth_json(client, "POST", "/api/playlists", json={"name": "PL1"}).json()
    return org, site, playlist


def upload_png(client, name: str):
    return client.post(
        "/api/media",
        files={"file": (f"{name}.png", b"\x89PNG\r\n\x1a\n" + name.encode(), "image/png")},
        headers={"X-CSRF-Token": client.cookies.get("elyon_csrf", "")},
    ).json()


def test_overlap_math():
    a = (_dt(9), _dt(11))
    b = (_dt(10), _dt(12))
    c = (_dt(12), _dt(13))
    assert overlaps(*a, *b)
    assert overlaps(*b, *a)
    assert not overlaps(*a, *c)


def test_playlist_crud(client):
    setup(client)
    p2 = auth_json(client, "POST", "/api/playlists", json={"name": "PL2"})
    assert p2.status_code == 201
    dup = auth_json(client, "POST", "/api/playlists", json={"name": "PL1"})
    assert dup.status_code == 409
    media = upload_png(client, "img1")
    add = auth_json(
        client,
        "POST",
        f"/api/playlists/{p2.json()['id']}/items",
        json={"media_id": media["id"], "duration_seconds": 10},
    )
    assert add.status_code == 201, add.text
    assert len(add.json()["items"]) == 1
    assert add.json()["items"][0]["position"] == 1
    reorder = auth_json(client, "POST", f"/api/playlists/{p2.json()['id']}/reorder",
                        json=[add.json()["items"][0]["id"]])
    assert reorder.status_code == 200


def test_schedule_conflict_emits_event(client):
    org, site, playlist = setup(client)
    s1 = auth_json(
        client,
        "POST",
        "/api/schedules",
        json={
            "site_id": site["id"],
            "playlist_id": playlist["id"],
            "name": "Matin",
            "start_at": _dt(9).isoformat(),
            "end_at": _dt(12).isoformat(),
        },
    )
    assert s1.status_code == 201, s1.text
    s2 = auth_json(
        client,
        "POST",
        "/api/schedules",
        json={
            "site_id": site["id"],
            "playlist_id": playlist["id"],
            "name": "Soir",
            "start_at": _dt(11).isoformat(),
            "end_at": _dt(14).isoformat(),
        },
    )
    assert s2.status_code == 201, s2.text
    events = client.get("/api/events").json()
    assert any(e["type"] == "schedule_conflict" for e in events)


def test_invalid_window(client):
    org, site, playlist = setup(client)
    resp = auth_json(
        client,
        "POST",
        "/api/schedules",
        json={
            "site_id": site["id"],
            "playlist_id": playlist["id"],
            "name": "Invalide",
            "start_at": _dt(14).isoformat(),
            "end_at": _dt(12).isoformat(),
        },
    )
    assert resp.status_code == 422


def test_schedule_resolution_order():
    from elyon_api.models import Schedule

    a = Schedule(id="aaaa", priority=0)
    b = Schedule(id="bbbb", priority=5)
    c = Schedule(id="cccc", priority=5)
    ordered = sort_schedules([a, b, c])
    assert [s.id for s in ordered] == ["bbbb", "cccc", "aaaa"]

    tied = sort_schedules([c, b])
    assert [s.id for s in tied] == ["bbbb", "cccc"]


def test_schedule_delete(client):
    org, site, playlist = setup(client)
    sched = auth_json(
        client,
        "POST",
        "/api/schedules",
        json={
            "site_id": site["id"],
            "playlist_id": playlist["id"],
            "name": "S",
            "start_at": _dt(9).isoformat(),
            "end_at": _dt(10).isoformat(),
        },
    ).json()
    resp = auth_json(client, "DELETE", f"/api/schedules/{sched['id']}")
    assert resp.status_code == 204
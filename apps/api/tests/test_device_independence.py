from __future__ import annotations

import datetime as dt
import io
import json

from PIL import Image

from elyon_api.models import Media
from elyon_api.services.media_processing import process_media
from elyon_api.services.storage import LocalStorage
from tests.conftest import (
    auth_json,
    bootstrap_superadmin,
    create_org,
    login,
    login_as_org_admin,
)


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _setup_site_with_content(client, settings, db_session_factory) -> dict:
    """Org + site + playliste (1 média prêt) + planning actif + 2 devices approuvés."""
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "IndepCo")
    login_as_org_admin(client, org, "ind@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "Site 1"}).json()
    playlist = auth_json(client, "POST", "/api/playlists", json={"name": "PL"}).json()
    media = client.post(
        "/api/media",
        files={"file": ("a.png", png_bytes(), "image/png")},
        headers={"X-CSRF-Token": client.cookies.get("elyon_csrf", "")},
    ).json()
    with db_session_factory() as session:
        stored = session.get(Media, media["id"])
        process_media(stored, settings, LocalStorage(settings.media_storage_root))
        session.commit()
    auth_json(
        client,
        "POST",
        f"/api/playlists/{playlist['id']}/items",
        json={"media_id": media["id"], "duration_seconds": 8},
    )
    now = dt.datetime.now(dt.UTC)
    schedule = auth_json(
        client,
        "POST",
        "/api/schedules",
        json={
            "site_id": site["id"],
            "playlist_id": playlist["id"],
            "name": "Partagé",
            "start_at": (now - dt.timedelta(hours=1)).isoformat(),
            "end_at": (now + dt.timedelta(hours=1)).isoformat(),
        },
    ).json()

    def enroll(serial: str) -> str:
        token = auth_json(
            client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}
        ).json()
        creds = client.post(
            "/api/enroll/request",
            json={"serial": serial, "name": serial, "site_code": token["code"]},
        ).json()
        auth_json(client, "POST", f"/api/devices/{creds['device_id']}/approve")
        return creds["device_id"]

    dev_a = enroll("RPI-A")
    dev_b = enroll("RPI-B")
    for device_id in (dev_a, dev_b):
        auth_json(
            client,
            "POST",
            f"/api/sites/{site['id']}/screens",
            json={"name": f"Écran {device_id[:8]}", "device_id": device_id},
        )
    return {"org": org, "site": site, "playlist": playlist, "schedule": schedule,
            "dev_a": dev_a, "dev_b": dev_b}


def _block_names(client, device_id: str) -> list[str]:
    resp = auth_json(client, "POST", f"/api/devices/{device_id}/publish")
    assert resp.status_code == 200, resp.text
    payload = json.loads(resp.json()["payload"])
    return [b["schedule_name"] for b in payload["blocks"]]


def test_schedule_exclusion_is_per_device(client, settings, db_session_factory):
    ctx = _setup_site_with_content(client, settings, db_session_factory)
    sched, dev_a, dev_b = ctx["schedule"], ctx["dev_a"], ctx["dev_b"]

    assert _block_names(client, dev_a) == ["Partagé"]
    assert _block_names(client, dev_b) == ["Partagé"]

    # Masquage sur UN écran seulement.
    excl = auth_json(client, "POST", f"/api/schedules/{sched['id']}/exclusions",
                     json={"device_id": dev_a})
    assert excl.status_code == 201, excl.text
    assert _block_names(client, dev_a) == []
    assert _block_names(client, dev_b) == ["Partagé"]

    # La liste des plannings signale l'exclusion locale.
    listing = auth_json(
        client, "GET", "/api/schedules",
        params={"site_id": ctx["site"]["id"], "device_id": dev_a},
    ).json()
    flags = {s["id"]: s["excluded_for_this_device"] for s in listing}
    assert flags[sched["id"]] is True
    listing_b = auth_json(
        client, "GET", "/api/schedules",
        params={"site_id": ctx["site"]["id"], "device_id": dev_b},
    ).json()
    flags_b = {s["id"]: s["excluded_for_this_device"] for s in listing_b}
    assert flags_b[sched["id"]] is False

    # Idempotent.
    again = auth_json(client, "POST", f"/api/schedules/{sched['id']}/exclusions",
                      json={"device_id": dev_a})
    assert again.status_code == 201

    # Réactivation sur cet écran.
    incl = auth_json(client, "DELETE", f"/api/schedules/{sched['id']}/exclusions/{dev_a}")
    assert incl.status_code == 204
    assert _block_names(client, dev_a) == ["Partagé"]
    assert _block_names(client, dev_b) == ["Partagé"]


def test_schedule_exclusion_requires_same_site(client, settings, db_session_factory):
    ctx = _setup_site_with_content(client, settings, db_session_factory)
    sched = ctx["schedule"]
    # Un device d'un AUTRE site est refusé.
    site2 = auth_json(client, "POST", "/api/sites", json={"name": "Site 2"}).json()
    token2 = auth_json(client, "POST", "/api/enroll/tokens",
                       params={"site_id": site2["id"]}).json()
    dev_x = client.post(
        "/api/enroll/request",
        json={"serial": "RPI-Y", "name": "Y", "site_code": token2["code"]},
    ).json()
    auth_json(client, "POST", f"/api/devices/{dev_x['device_id']}/approve")
    denied = auth_json(client, "POST", f"/api/schedules/{sched['id']}/exclusions",
                       json={"device_id": dev_x["device_id"]})
    assert denied.status_code == 400
    missing = auth_json(client, "DELETE",
                        f"/api/schedules/{sched['id']}/exclusions/nope")
    assert missing.status_code in (400, 404)


def test_playlist_team_visibility_and_editing(client):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "ScopeCo")
    op_email = "scope@org.test"
    login_as_org_admin(client, org, op_email)
    team_a = auth_json(client, "POST", "/api/teams", json={"name": "Équipe A"}).json()
    team_b = auth_json(client, "POST", "/api/teams", json={"name": "Équipe B"}).json()
    site = auth_json(client, "POST", "/api/sites", json={"name": "S"}).json()

    def make_user(email: str, team_id: str | None) -> None:
        resp = auth_json(
            client,
            "POST",
            "/api/users",
            json={
                "email": email,
                "password": "motdepasse-long",
                "full_name": "M",
                "role": "operator",
                "team_id": team_id,
            },
        )
        assert resp.status_code == 201, resp.text

    make_user("op-a@org.test", team_a["id"])
    make_user("op-b@org.test", team_b["id"])

    # L'admin crée une playliste globale (team_id NULL).
    global_pl = auth_json(client, "POST", "/api/playlists", json={"name": "Générale"}).json()
    assert global_pl["team_id"] is None

    # L'opérateur A crée une playliste rattachée à son équipe.
    login(client, "op-a@org.test")
    pl_a = auth_json(client, "POST", "/api/playlists", json={"name": "Playliste A"}).json()
    assert pl_a["team_id"] == team_a["id"]
    assert pl_a["team_name"] == "Équipe A"

    # L'opérateur B ne voit que la globale.
    login(client, "op-b@org.test")
    names_b = {p["name"] for p in client.get("/api/playlists").json()}
    assert names_b == {"Générale"}
    hidden = client.get(f"/api/playlists/{pl_a['id']}")
    assert hidden.status_code == 404

    # L'opérateur A voit la globale + la sienne.
    login(client, "op-a@org.test")
    names_a = {p["name"] for p in client.get("/api/playlists").json()}
    assert names_a == {"Générale", "Playliste A"}

    # Édition : A peut modifier la sienne…
    media = client.post(
        "/api/media",
        files={"file": ("x.png", png_bytes(), "image/png")},
        headers={"X-CSRF-Token": client.cookies.get("elyon_csrf", "")},
    ).json()
    add_ok = auth_json(client, "POST", f"/api/playlists/{pl_a['id']}/items",
                       json={"media_id": media["id"]})
    assert add_ok.status_code == 201, add_ok.text

    # …mais B ne peut ni voir ni modifier celle de A.
    login(client, "op-b@org.test")
    denied_view = client.get(f"/api/playlists/{pl_a['id']}")
    assert denied_view.status_code == 404
    denied_add = auth_json(client, "POST", f"/api/playlists/{pl_a['id']}/items",
                           json={"media_id": media["id"]})
    assert denied_add.status_code in (403, 404)
    denied_del = auth_json(client, "DELETE", f"/api/playlists/{pl_a['id']}")
    assert denied_del.status_code in (403, 404)

    # Programmer une playliste d'une autre équipe est refusé.
    now = dt.datetime.now(dt.UTC)
    bad_sched = auth_json(
        client,
        "POST",
        "/api/schedules",
        json={
            "site_id": site["id"],
            "playlist_id": pl_a["id"],
            "name": "X",
            "start_at": now.isoformat(),
            "end_at": (now + dt.timedelta(hours=1)).isoformat(),
        },
    )
    assert bad_sched.status_code == 400

    # L'admin voit tout et peut éditer les playlistes d'équipe.
    login(client, op_email)
    names_admin = {p["name"] for p in client.get("/api/playlists").json()}
    assert names_admin == {"Générale", "Playliste A"}
    admin_add = auth_json(client, "POST", f"/api/playlists/{pl_a['id']}/items",
                          json={"media_id": media["id"]})
    assert admin_add.status_code == 201, admin_add.text

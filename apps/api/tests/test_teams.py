"""Équipes : partage de bibliothèque, quotas, profil, téléchargement."""

from __future__ import annotations

import io

from tests.conftest import (
    auth_json,
    bootstrap_superadmin,
    create_org,
    login,
    login_as_org_admin,
)


def png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 18), (10, 120, 60)).save(buf, "PNG")
    return buf.getvalue()


def setup(client) -> dict:
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "TeamCo")
    login_as_org_admin(client, org, "boss@team.test")
    return {"org": org}


def _user(client, email: str, team_id: str | None = None, quota_bytes: int = 0) -> None:
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
            "quota_bytes": quota_bytes,
        },
    )
    assert resp.status_code == 201, resp.text


def _upload(client, name: str, content: bytes | None = None):
    return client.post(
        "/api/media",
        files={"file": (name, content or png_bytes(), "image/png")},
        params={"name": name},
        headers={"X-CSRF-Token": client.cookies.get("elyon_csrf", "")},
    )


def test_team_crud_and_listing(client):
    setup(client)
    created = auth_json(
        client, "POST", "/api/teams", json={"name": "Marketing", "quota_bytes": 0}
    )
    assert created.status_code == 201, created.text
    team = created.json()
    assert team["quota_bytes"] == 0
    listing = client.get("/api/teams").json()
    assert [t["name"] for t in listing] == ["Marketing"]

    patched = auth_json(
        client, "PATCH", f"/api/teams/{team['id']}", json={"quota_bytes": 5 * 1024**3}
    )
    assert patched.json()["quota_bytes"] == 5 * 1024 ** 3

    deleted = auth_json(client, "DELETE", f"/api/teams/{team['id']}")
    assert deleted.status_code == 204


def test_team_members_share_library(client):
    setup(client)
    team = auth_json(client, "POST", "/api/teams", json={"name": "Eq"}).json()
    _user(client, "a@team.test", team_id=team["id"])
    _user(client, "b@team.test", team_id=team["id"])
    _user(client, "solo@team.test")

    login(client, "a@team.test")
    up = _upload(client, "partage.png")
    assert up.status_code == 201, up.text

    login(client, "b@team.test")
    listing = client.get("/api/media").json()
    assert len(listing) == 1 and listing[0]["name"] == "partage.png"
    detail = client.get(f"/api/media/{listing[0]['id']}")
    assert detail.status_code == 200

    # Un utilisateur hors équipe ne voit rien.
    login(client, "solo@team.test")
    assert client.get("/api/media").json() == []
    assert client.get(f"/api/media/{listing[0]['id']}").status_code == 404


def test_team_quota_blocks_upload(client):
    setup(client)
    team = auth_json(
        client, "POST", "/api/teams", json={"name": "Petite", "quota_bytes": 100}
    ).json()
    _user(client, "q@team.test", team_id=team["id"])
    login(client, "q@team.test")

    ok = _upload(client, "petit.png")
    assert ok.status_code == 201, ok.text
    too_big = _upload(client, "gros.png", b"y" * 200)
    assert too_big.status_code == 413
    assert "équipe" in too_big.json()["detail"]


def test_user_quota_blocks_upload_but_team_higher(client):
    setup(client)
    team = auth_json(
        client, "POST", "/api/teams", json={"name": "Grande", "quota_bytes": 10 * 1024**3}
    ).json()
    # Le quota personnel (120 o) est plus restrictif que celui de l'équipe.
    _user(client, "p@team.test", team_id=team["id"], quota_bytes=120)
    login(client, "p@team.test")

    ok = _upload(client, "petit.png")
    assert ok.status_code == 201, ok.text
    first = ok.json()["size_bytes"]
    too_big = _upload(client, "gros.png", b"z" * (first + 60))
    assert too_big.status_code == 413
    assert "personnel" in too_big.json()["detail"]


def test_no_quota_by_default(client, settings):
    setup(client)
    _user(client, "libre@team.test")
    login(client, "libre@team.test")
    # Sans quota explicite : le plafond historique settings.user_quota_bytes s'applique.
    resp = _upload(client, "ok.png")
    assert resp.status_code == 201, resp.text


def test_profile_update_and_download(client):
    setup(client)
    team = auth_json(client, "POST", "/api/teams", json={"name": "DL"}).json()
    _user(client, "prof@team.test", team_id=team["id"])
    login(client, "prof@team.test")
    up = _upload(client, "fichier.png")
    media_id = up.json()["id"]

    # Téléchargement (bibliothèque d'équipe, fichier original).
    dl = client.get(f"/api/media/{media_id}/download")
    assert dl.status_code == 200, dl.text
    assert dl.content == png_bytes()
    assert "attachment" in dl.headers.get("content-disposition", "")

    # Changement de mot de passe : exigence du mot de passe actuel.
    bad = auth_json(
        client,
        "PATCH",
        "/api/auth/me",
        json={"password": "nouveaumotdepasse", "current_password": "faux"},
    )
    assert bad.status_code == 403
    good = auth_json(
        client,
        "PATCH",
        "/api/auth/me",
        json={"password": "nouveaumotdepasse", "current_password": "motdepasse-long"},
    )
    assert good.status_code == 200, good.text
    relogin = client.post(
        "/api/auth/login", json={"email": "prof@team.test", "password": "nouveaumotdepasse"}
    )
    assert relogin.status_code == 200, relogin.text

    # Changement de nom complet.
    renamed = auth_json(client, "PATCH", "/api/auth/me", json={"full_name": "Nouveau Nom"})
    assert renamed.json()["full_name"] == "Nouveau Nom"

    # Email déjà pris → 409.
    taken = auth_json(client, "PATCH", "/api/auth/me", json={"email": "boss@team.test"})
    assert taken.status_code == 409


def test_trash_restore_and_purge(client):
    setup(client)
    team = auth_json(client, "POST", "/api/teams", json={"name": "TrashEq"}).json()
    _user(client, "trash@team.test", team_id=team["id"])
    login(client, "trash@team.test")

    up = _upload(client, "corbeille.png")
    assert up.status_code == 201, up.text
    media_id = up.json()["id"]

    # Suppression → corbeille ; le média sort de la bibliothèque mais reste
    # listable via ?trash=true, et ne compte plus dans le quota.
    trashed = auth_json(client, "DELETE", f"/api/media/{media_id}")
    assert trashed.status_code == 204, trashed.text
    assert all(m["id"] != media_id for m in client.get("/api/media").json())
    trash_list = client.get("/api/media?trash=true").json()
    assert [m["id"] for m in trash_list] == [media_id]

    # Restauration.
    restored = auth_json(client, "POST", f"/api/media/{media_id}/restore")
    assert restored.status_code == 200, restored.text
    assert any(m["id"] == media_id for m in client.get("/api/media").json())

    # Re-suppression puis purge définitive.
    auth_json(client, "DELETE", f"/api/media/{media_id}")
    purged = auth_json(client, "DELETE", f"/api/media/{media_id}/permanent")
    assert purged.status_code == 204, purged.text
    assert client.get("/api/media?trash=true").json() == []


def test_quota_warning_suggests_trash(client, settings):
    setup(client)
    settings.user_quota_bytes = 90
    _user(client, "warn@team.test")
    login(client, "warn@team.test")
    up = _upload(client, "a.png")
    assert up.status_code == 201, up.text
    media_id = up.json()["id"]

    # Quota atteint exactement : avertissement ancien fichiers.
    q = client.get("/api/media/quota").json()
    assert q["remaining_bytes"] == 0, q
    assert "anciens fichiers" in q["warning"]

    # En corbeille, le média ne compte plus : l'espace est libéré et le
    # warning disparaît ; un nouvel upload redevient possible.
    auth_json(client, "DELETE", f"/api/media/{media_id}")
    q2 = client.get("/api/media/quota").json()
    assert q2["warning"] is None
    up2 = _upload(client, "b.png")
    assert up2.status_code == 201, up2.text

    # Saturons à nouveau avec la corbeille non vide : le message 413 invite
    # à vider la corbeille.
    auth_json(client, "DELETE", f"/api/media/{up2.json()['id']}")
    blocked = _upload(client, "c.png", b"x" * 120)
    assert blocked.status_code == 413
    assert "corbeille" in blocked.json()["detail"]

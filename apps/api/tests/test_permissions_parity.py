"""Contrat de parité RBAC : permissions.py (source de vérité) vs permissions.ts (front).

Parse les littéraux de ROLE_PERMISSIONS / ROLE_SCOPES dans apps/web/src/lib/permissions.ts
et les compare aux définitions Python. Toute dérive front/back doit échouer ici.
"""

from __future__ import annotations

import re
from pathlib import Path

from elyon_api.models import Role
from elyon_api.permissions import ROLE_PERMISSIONS, ROLE_SCOPE

TS_PATH = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "lib" / "permissions.ts"

ROLE_TS = {
    "superadmin": Role.SUPERADMIN,
    "org_admin": Role.ORG_ADMIN,
    "site_manager": Role.SITE_MANAGER,
    "operator": Role.OPERATOR,
    "viewer": Role.VIEWER,
}


def _extract_permissions(src: str, role: str) -> set[str]:
    if role in ("superadmin", "org_admin"):
        m = re.search(r"const ALL: Permission\[\] = \[(.*?)\]", src, re.S)
        assert m, "bloc ALL introuvable"
        return set(re.findall(r'"([^"]+)"', m.group(1)))
    block = re.search(rf"{role}: new Set<Permission>\(\[(.*?)\]\)", src, re.S)
    assert block, f"bloc {role} introuvable"
    return set(re.findall(r'"([^"]+)"', block.group(1)))


def test_permissions_ts_matches_python() -> None:
    src = TS_PATH.read_text()
    assert len(ROLE_TS) == 5
    for ts_role, py_role in ROLE_TS.items():
        expected = {p.value for p in ROLE_PERMISSIONS[py_role]}
        actual = _extract_permissions(src, ts_role)
        assert actual == expected, f"{ts_role}: {actual ^ expected}"
        scope = re.search(rf"{ts_role}: \"([a-z]+)\"", src)
        assert scope and scope.group(1) == ROLE_SCOPE[py_role], f"{ts_role}: scope divergent"


def test_permissions_ts_count_matches_python() -> None:
    src = TS_PATH.read_text()
    for ts_role, py_role in ROLE_TS.items():
        expected = {p.value for p in ROLE_PERMISSIONS[py_role]}
        if ts_role in ("superadmin", "org_admin"):
            continue
        actual = _extract_permissions(src, ts_role)
        assert actual == expected

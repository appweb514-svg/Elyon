from __future__ import annotations

import sys
from pathlib import Path

# Accès aux sources de l'API (apps/api) et de l'agent depuis les tests.
_REPO_ROOT = Path(__file__).resolve().parents[3]
for entry in (
    str(_REPO_ROOT / "apps" / "api"),
    str(_REPO_ROOT / "player" / "agent"),
):
    if entry not in sys.path:
        sys.path.insert(0, entry)

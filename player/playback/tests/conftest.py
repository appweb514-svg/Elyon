from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
entry = str(_REPO_ROOT / "player" / "playback")
if entry not in sys.path:
    sys.path.insert(0, entry)

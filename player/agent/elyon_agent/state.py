from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DeviceState:
    """État persisté du player : identité et secrets d'authentification."""

    device_id: str
    token: str
    pinned_public_key: str | None = None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "device_id": self.device_id,
            "token": self.token,
            "pinned_public_key": self.pinned_public_key,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)

    @classmethod
    def load(cls, path: Path) -> DeviceState | None:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data.get("device_id") or not data.get("token"):
            return None
        return cls(
            device_id=data["device_id"],
            token=data["token"],
            pinned_public_key=data.get("pinned_public_key"),
        )

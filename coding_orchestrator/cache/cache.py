from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class HashCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def key(self, namespace: str, payload: str) -> str:
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"{namespace}-{digest}"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        (self.root / f"{key}.json").write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


from __future__ import annotations

from pathlib import Path

from coding_orchestrator.observability.logger import JsonlLogger


class AuditLog(JsonlLogger):
    def __init__(self, path: Path) -> None:
        super().__init__(path)


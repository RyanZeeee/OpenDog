from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CronDef:
    id: str
    name: str
    description: str
    agent: str
    schedule: str
    enabled: bool
    one_off: bool
    min_interval_minutes: int
    deliver_to: dict[str, Any]
    prompt: str
    path: Path
    metadata: dict[str, Any] = field(default_factory=dict)

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from opendog.core.event_bus import EventBus
from opendog.core.session_store import SessionStore
from opendog.utils.config import AppConfig


@dataclass
class SharedContext:
    """Runtime-wide services and paths shared by CLI, runtime, and commands."""

    workspace_root: Path
    working_dir: Path
    config: AppConfig
    session_store: Optional[SessionStore] = None
    event_bus: EventBus = field(default_factory=EventBus)

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4


@dataclass
class RuntimeEvent:
    """A normalized event emitted by the conversation runtime."""

    type: str
    content: str = ""
    session_id: Optional[str] = None
    source: str = "runtime"
    role: Optional[str] = None
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()), compare=False)
    created_at: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat(),
        compare=False,
    )

    @classmethod
    def text(
        cls,
        content: str,
        *,
        session_id: Optional[str] = None,
        source: str = "agent",
    ) -> "RuntimeEvent":
        return cls(
            type="assistant_delta",
            content=content,
            session_id=session_id,
            source=source,
        )

    @classmethod
    def status(
        cls,
        content: str,
        *,
        session_id: Optional[str] = None,
        source: str = "runtime",
    ) -> "RuntimeEvent":
        return cls(
            type="status",
            content=content,
            session_id=session_id,
            source=source,
        )

    @classmethod
    def message(
        cls,
        role: str,
        content: str,
        *,
        session_id: Optional[str] = None,
        source: str = "runtime",
    ) -> "RuntimeEvent":
        return cls(
            type="local_message",
            role=role,
            content=content,
            session_id=session_id,
            source=source,
        )

    @classmethod
    def user_message(
        cls,
        content: str,
        *,
        session_id: Optional[str] = None,
        source: str = "tui",
    ) -> "RuntimeEvent":
        return cls(
            type="user_message",
            role="user",
            content=content,
            session_id=session_id,
            source=source,
        )

    @classmethod
    def error(
        cls,
        content: str,
        *,
        session_id: Optional[str] = None,
        source: str = "runtime",
    ) -> "RuntimeEvent":
        return cls(
            type="error",
            content=content,
            session_id=session_id,
            source=source,
        )

    @classmethod
    def from_agent_event(
        cls,
        event: dict,
        *,
        session_id: Optional[str] = None,
        source: str = "agent",
    ) -> "RuntimeEvent":
        event_type = event.get("type", "")
        content = event.get("content", "")
        if event_type == "text":
            return cls.text(content, session_id=session_id, source=source)
        if event_type == "status":
            return cls.status(content, session_id=session_id, source=source)
        return cls(
            type=event_type,
            content=content,
            session_id=session_id,
            source=source,
            data=dict(event),
        )

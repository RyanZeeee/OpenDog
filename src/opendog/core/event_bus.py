from __future__ import annotations

import inspect
from collections import defaultdict
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from opendog.core.runtime_event import RuntimeEvent

EventHandler = Callable[[RuntimeEvent], Optional[Awaitable[None]]]


@dataclass
class EventSubscription:
    event_type: str
    handler: EventHandler
    session_id: Optional[str] = None


class EventBus:
    """Small event dispatcher; later Worker support can put a queue behind it."""

    def __init__(self) -> None:
        self._subscriptions: dict[str, list[EventSubscription]] = defaultdict(list)

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        session_id: Optional[str] = None,
    ) -> None:
        self._subscriptions[event_type].append(
            EventSubscription(
                event_type=event_type,
                handler=handler,
                session_id=session_id,
            )
        )

    def unsubscribe(
        self,
        event_type: str,
        handler: EventHandler,
        session_id: Optional[str] = None,
    ) -> None:
        subscriptions = self._subscriptions.get(event_type, [])
        self._subscriptions[event_type] = [
            subscription
            for subscription in subscriptions
            if not (
                subscription.handler == handler
                and subscription.session_id == session_id
            )
        ]

    async def publish(self, event: RuntimeEvent) -> None:
        subscriptions = [
            *self._subscriptions.get(event.type, []),
            *self._subscriptions.get("*", []),
        ]
        for subscription in subscriptions:
            if not self._matches_session(subscription, event):
                continue
            result = subscription.handler(event)
            if inspect.isawaitable(result):
                await result

    def _matches_session(
        self,
        subscription: EventSubscription,
        event: RuntimeEvent,
    ) -> bool:
        if subscription.session_id is None:
            return True
        return subscription.session_id == event.session_id

"""
EdgeFinder — Internal Event Bus

Simple asyncio-based pub/sub for real-time events within the FastAPI process.
Used to bridge Celery worker outputs → SSE connections in the dashboard.

Architecture:
  - Celery workers (separate processes) cannot share this in-process bus directly.
  - Workers instead POST to POST /api/internal/events endpoint.
  - FastAPI receives the POST and publishes to this bus.
  - SSE connections subscribe to this bus and stream events to the browser.

Event format:
    {
        "type": "alert" | "price_update" | "filing" | "briefing_ready",
        "payload": { ... event-specific data ... }
    }

Usage:
    # Publishing (from FastAPI route handlers):
    await event_bus.publish("alert", {"ticker": "NVDA", "score": 87, ...})

    # Subscribing (from SSE endpoint):
    queue = asyncio.Queue()
    event_bus.subscribe(queue)
    try:
        event = await asyncio.wait_for(queue.get(), timeout=15)
        yield f"event: {event['type']}\\ndata: {json.dumps(event['payload'])}\\n\\n"
    finally:
        event_bus.unsubscribe(queue)
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class EventBus:
    """
    Asyncio-based in-process pub/sub event bus.

    Thread-safe for asyncio concurrency (single event loop).
    Not safe for multi-process use — use Redis pub/sub for that.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._event_log: list[dict[str, Any]] = []  # Last N events for replay
        self._max_log_size: int = 100

    def subscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Register a queue to receive all future events."""
        self._subscribers.append(queue)
        logger.debug("SSE subscriber added", total_subscribers=len(self._subscribers))

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a queue from the subscriber list."""
        try:
            self._subscribers.remove(queue)
            logger.debug("SSE subscriber removed", total_subscribers=len(self._subscribers))
        except ValueError:
            pass  # Already removed (e.g., on disconnect race)

    async def publish(self, event_type: str, payload: Any) -> None:
        """
        Publish an event to all current subscribers.

        If a subscriber's queue is full (maxsize exceeded), the event is dropped
        for that subscriber to prevent blocking the publisher.
        """
        event: dict[str, Any] = {"type": event_type, "payload": payload}

        # Append to replay log
        self._event_log.append(event)
        if len(self._event_log) > self._max_log_size:
            self._event_log.pop(0)

        # Deliver to all subscribers
        dead_queues: list[asyncio.Queue] = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop the event for this slow consumer rather than blocking
                logger.warning(
                    "SSE subscriber queue full, dropping event",
                    event_type=event_type,
                )
            except Exception as exc:
                logger.error("Failed to deliver event to subscriber", error=str(exc))
                dead_queues.append(queue)

        # Clean up dead subscribers
        for q in dead_queues:
            self.unsubscribe(q)

        logger.debug(
            "Event published",
            event_type=event_type,
            subscriber_count=len(self._subscribers),
        )

    def get_recent_events(self, count: int = 20) -> list[dict[str, Any]]:
        """Return the last `count` events from the replay log."""
        return self._event_log[-count:]

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

event_bus = EventBus()


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------


class EventType:
    ALERT = "alert"
    PRICE_UPDATE = "price_update"
    FILING = "filing"
    BRIEFING_READY = "briefing_ready"
    INGESTION_COMPLETE = "ingestion_complete"
    ERROR = "error"

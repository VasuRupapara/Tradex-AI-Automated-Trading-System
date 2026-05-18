"""
Central Event Queue for the Automated Trading System.

Implements the core event loop using collections.deque for rapid
append and pop operations, as specified in the blueprint.

The Event Queue is the heart of the event-driven architecture.
All components communicate strictly through this queue.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Callable, Dict, List, Optional, Type

from backend.common.events import Event, EventType
from backend.common.logger import get_logger

logger = get_logger("event-queue")


class EventQueue:
    """
    Central event queue implementing the event-driven execution loop.

    Uses collections.deque for O(1) append and popleft operations.
    Supports both synchronous and asynchronous event processing.

    The execution loop processes events in this sequence:
        1. MarketDataEvent → Strategy Engine
        2. SignalEvent → Risk Manager
        3. OrderEvent → Execution Handler
        4. FillEvent → Portfolio/Accounting
    """

    def __init__(self, maxsize: int = 100_000):
        self._queue: deque[Event] = deque(maxlen=maxsize)
        self._handlers: Dict[EventType, List[Callable]] = {}
        self._running: bool = False
        self._async_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)

    def put(self, event: Event) -> None:
        """Place an event on the queue (synchronous).
        
        Also pushes to the async queue so async_run_loop() can pick it up.
        """
        self._queue.append(event)
        # Bridge into the async queue so async_run_loop processes it
        try:
            self._async_queue.put_nowait(event)
        except Exception:
            pass  # Queue full or no running loop
        logger.debug("event_queued", event_type=event.event_type.name,
                     event_id=event.event_id[:8])

    async def async_put(self, event: Event) -> None:
        """Place an event on the async queue."""
        await self._async_queue.put(event)
        logger.debug("async_event_queued", event_type=event.event_type.name,
                     event_id=event.event_id[:8])

    def get(self) -> Optional[Event]:
        """Pop the next event from the queue (synchronous)."""
        if self._queue:
            return self._queue.popleft()
        return None

    async def async_get(self) -> Event:
        """Pop the next event from the async queue."""
        return await self._async_queue.get()

    def register_handler(self, event_type: EventType, handler: Callable) -> None:
        """Register an event handler for a specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.info("handler_registered",
                     event_type=event_type.name,
                     handler=getattr(handler, "__name__", repr(handler)))

    def process_next(self) -> bool:
        """
        Process the next event in the queue.

        Returns True if an event was processed, False if queue was empty.
        """
        event = self.get()
        if event is None:
            return False

        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error("handler_error",
                             event_type=event.event_type.name,
                             handler=getattr(handler, "__name__", repr(handler)),
                             error=str(e))
        return True

    def run_loop(self) -> None:
        """
        Run the synchronous event loop (while True).
        
        This is the core execution loop described in the blueprint.
        It continuously processes events from the queue.
        """
        self._running = True
        logger.info("event_loop_started")

        while self._running:
            if not self.process_next():
                # No events to process, brief sleep to avoid busy-waiting
                import time
                time.sleep(0.001)

    async def async_run_loop(self) -> None:
        """Run the asynchronous event loop."""
        self._running = True
        logger.info("async_event_loop_started")

        while self._running:
            event = await self.async_get()
            handlers = self._handlers.get(event.event_type, [])
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:
                    logger.error("async_handler_error",
                                 event_type=event.event_type.name,
                                 error=str(e))

    def stop(self) -> None:
        """Stop the event loop gracefully."""
        self._running = False
        logger.info("event_loop_stopped")

    @property
    def size(self) -> int:
        """Current number of events in the queue."""
        return len(self._queue)

    @property
    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        return len(self._queue) == 0

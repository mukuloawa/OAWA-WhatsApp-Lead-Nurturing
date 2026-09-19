"""Debounce scheduling and startup recovery (DESIGN.md Section 8).

Step 3: "Schedule process(event_id) to run after DEBOUNCE_SECONDS ... as
an asyncio task ... On startup, the worker also picks up any pending
events older than the debounce window, to recover from restarts."
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nurture.ghl.client import GHLClient
from nurture.settings import Settings
from nurture.store import repository
from nurture.worker.engine_interface import ConversationEngine
from nurture.worker.pipeline import process

logger = logging.getLogger("nurture.scheduler")


class Scheduler:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        ghl: GHLClient,
        engine: ConversationEngine,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._ghl = ghl
        self._engine = engine
        self._settings = settings
        self._tasks: set[asyncio.Task] = set()

    def _track(self, task: asyncio.Task) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def schedule(self, event_id: int) -> asyncio.Task:
        """Debounced: waits DEBOUNCE_SECONDS before processing."""
        task = asyncio.create_task(self._run_after_delay(event_id, self._settings.debounce_seconds))
        self._track(task)
        return task

    async def _run_after_delay(self, event_id: int, delay_seconds: float) -> None:
        await asyncio.sleep(delay_seconds)
        await self._process_safely(event_id)

    async def _process_safely(self, event_id: int) -> None:
        try:
            await process(
                event_id,
                session_factory=self._session_factory,
                ghl=self._ghl,
                engine=self._engine,
                settings=self._settings,
            )
        except Exception:  # noqa: BLE001 - a scheduled task must never crash silently or take the app down
            logger.exception("scheduler: unhandled error processing event %s", event_id)

    async def recover_pending_events(self) -> list[int]:
        """Runs once at startup. Picks up events left `pending` by a
        restart that happened mid-debounce, and processes them
        immediately (they're already past the debounce window).

        Deliberately fails soft: a DB that's unreachable or not yet
        migrated at boot must not crash the whole app — /ready already
        reports DB problems on its own, and /health must stay up
        regardless. This also matters operationally: this app is meant
        to keep receiving and queuing webhooks even if a startup scan
        hiccups once.
        """
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=self._settings.debounce_seconds)
            async with self._session_factory() as session:
                events = await repository.get_pending_events_older_than(session, cutoff=cutoff)
        except Exception:  # noqa: BLE001 - see docstring: must never block app startup
            logger.exception("scheduler: failed to check for pending events to recover at startup")
            return []
        event_ids = [e.id for e in events]
        for event_id in event_ids:
            task = asyncio.create_task(self._process_safely(event_id))
            self._track(task)
        if event_ids:
            logger.info("scheduler: recovering %d pending event(s) at startup", len(event_ids))
        return event_ids

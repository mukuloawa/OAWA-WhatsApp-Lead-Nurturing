"""Per-contact locking (DESIGN.md Section 6.2).

Postgres: `pg_advisory_xact_lock(hashtext(contact_id))`, transaction-scoped,
auto-released on commit/rollback. SQLite (tests): an in-process
`asyncio.Lock` per contact, released explicitly on exit, behind the same
async-context-manager interface.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_sqlite_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class ContactLock:
    def __init__(self, session: AsyncSession, contact_id: str) -> None:
        self._session = session
        self._contact_id = contact_id
        self._sqlite_lock: asyncio.Lock | None = None

    async def __aenter__(self) -> "ContactLock":
        dialect = self._session.get_bind().dialect.name
        if dialect == "postgresql":
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:cid))"),
                {"cid": self._contact_id},
            )
        else:
            self._sqlite_lock = _sqlite_locks[self._contact_id]
            await self._sqlite_lock.acquire()
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._sqlite_lock is not None:
            self._sqlite_lock.release()

"""FakeGHLClient: in-memory GHLClient for tests and the Phase 4 simulator.

DESIGN.md Section 7.2: "in-memory contacts and threads; records every
call for assertions. It powers all tests and the simulator."
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime, timezone

from nurture.ghl.client import GHLClient
from nurture.ghl.errors import GHLError, GHLNotFoundError
from nurture.ghl.models import Contact, Message


@dataclass
class RecordedCall:
    method: str
    kwargs: dict


class FakeGHLClient(GHLClient):
    def __init__(
        self,
        *,
        contacts: dict[str, Contact] | None = None,
        threads: dict[str, list[Message]] | None = None,
        field_ids: dict[str, str] | None = None,
    ) -> None:
        self.contacts: dict[str, Contact] = dict(contacts or {})
        self.threads: dict[str, list[Message]] = {
            contact_id: list(msgs) for contact_id, msgs in (threads or {}).items()
        }
        self.field_ids: dict[str, str] = dict(field_ids or {})
        self.notes: dict[str, list[str]] = {}
        self.calls: list[RecordedCall] = []
        self._message_id_counter = itertools.count(1)

    def _record(self, method: str, **kwargs) -> None:
        self.calls.append(RecordedCall(method=method, kwargs=kwargs))

    def _require_contact(self, contact_id: str) -> Contact:
        contact = self.contacts.get(contact_id)
        if contact is None:
            raise GHLNotFoundError(f"no such fake contact: {contact_id}")
        return contact

    async def get_contact(self, contact_id: str) -> Contact:
        self._record("get_contact", contact_id=contact_id)
        return self._require_contact(contact_id).model_copy(deep=True)

    async def get_thread(self, contact_id: str, limit: int = 50) -> list[Message]:
        self._record("get_thread", contact_id=contact_id, limit=limit)
        self._require_contact(contact_id)
        return list(self.threads.get(contact_id, []))[-limit:]

    async def send_whatsapp(self, contact_id: str, text: str) -> str:
        self._record("send_whatsapp", contact_id=contact_id, text=text)
        self._require_contact(contact_id)
        message_id = f"fake-msg-{next(self._message_id_counter)}"
        self.threads.setdefault(contact_id, []).append(
            Message(
                id=message_id,
                direction="outbound",
                text=text,
                sent_at=datetime.now(timezone.utc),
                sent_by_service=True,
            )
        )
        return message_id

    async def add_note(self, contact_id: str, text: str) -> None:
        self._record("add_note", contact_id=contact_id, text=text)
        self._require_contact(contact_id)
        self.notes.setdefault(contact_id, []).append(text)

    async def set_tags(self, contact_id: str, add: list[str], remove: list[str]) -> None:
        self._record("set_tags", contact_id=contact_id, add=list(add), remove=list(remove))
        contact = self._require_contact(contact_id)
        contact.tags |= set(add)
        contact.tags -= set(remove)

    async def update_custom_fields(self, contact_id: str, fields: dict[str, str]) -> None:
        self._record("update_custom_fields", contact_id=contact_id, fields=dict(fields))
        contact = self._require_contact(contact_id)
        missing = [key for key in fields if key not in self.field_ids]
        if missing:
            raise GHLError(
                f"update_custom_fields: no fake field id registered for keys {missing}"
            )
        for key, value in fields.items():
            # Merge rule (DESIGN.md Section 6.1): a non-empty extracted value
            # overwrites; an empty value never clears an existing one. This is
            # enforced by the caller (Phase 3/4), not the client itself — the
            # fake just stores whatever it's given, like the real one would.
            contact.fields[key] = value

    async def resolve_custom_field_ids(self, keys: list[str]) -> dict[str, str]:
        self._record("resolve_custom_field_ids", keys=list(keys))
        return {key: self.field_ids[key] for key in keys if key in self.field_ids}

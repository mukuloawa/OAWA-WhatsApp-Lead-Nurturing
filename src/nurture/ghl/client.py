"""GHLClient interface (DESIGN.md Section 7.2), unchanged from the design doc.

Business logic must never call HTTP directly (DESIGN.md Section 0, rule 4).
Everything that talks to GHL goes through an implementation of this
protocol: RealGHLClient (real.py) or FakeGHLClient (fake.py).
"""

from __future__ import annotations

from typing import Protocol

from nurture.ghl.models import Contact, Message


class GHLClient(Protocol):
    async def get_contact(self, contact_id: str) -> Contact: ...

    async def get_thread(self, contact_id: str, limit: int = 50) -> list[Message]: ...

    async def send_whatsapp(self, contact_id: str, text: str) -> str: ...  # returns message id

    async def add_note(self, contact_id: str, text: str) -> None: ...  # used in shadow mode

    async def set_tags(self, contact_id: str, add: list[str], remove: list[str]) -> None: ...

    async def update_custom_fields(self, contact_id: str, fields: dict[str, str]) -> None: ...

    async def resolve_custom_field_ids(self, keys: list[str]) -> dict[str, str]: ...

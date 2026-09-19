"""Domain types (DESIGN.md Section 7.2), unchanged from the design doc."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Contact(BaseModel):
    id: str
    first_name: str | None
    city: str | None
    tags: set[str]
    fields: dict[str, str | None]  # keyed by our field KEY, not GHL id


class Message(BaseModel):
    id: str
    direction: Literal["inbound", "outbound"]
    text: str
    sent_at: datetime
    sent_by_service: bool  # True if id is in turns.sent message ids

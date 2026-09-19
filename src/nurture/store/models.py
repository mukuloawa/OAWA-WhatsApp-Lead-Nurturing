"""SQLAlchemy models for the two operational tables (DESIGN.md Section 6.2).

Postgres is the production target; SQLite (+aiosqlite) is allowed for local
dev and tests per DESIGN.md Section 11. Both are supported by sticking to
portable column types (JSON, not JSONB; no Postgres-only features here).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InboundEvent(Base):
    __tablename__ = "inbound_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contact_id: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_inbound_events_contact_received", "contact_id", "received_at"),
    )


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contact_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("inbound_events.id"), nullable=True
    )
    inbound_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    stage_before: Mapped[str] = mapped_column(Text, nullable=False)
    stage_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    tool_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_errors: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    regenerated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    send_mode: Mapped[str] = mapped_column(Text, nullable=False)
    sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("contact_id", "inbound_message_id", name="uq_turns_contact_message"),
    )

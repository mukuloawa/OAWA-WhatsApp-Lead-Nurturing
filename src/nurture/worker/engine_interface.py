"""The seam between the Phase 3 pipeline and the Phase 4 conversation engine.

DESIGN.md Section 16 ("Pipeline integration" test row) explicitly calls
for "a stubbed Claude returning canned tool outputs" at this phase. This
module defines the shape of that output (EngineDecision, matching
Appendix B's respond tool schema exactly) and the protocol the pipeline
calls through (ConversationEngine) — NOT the real Claude-calling engine,
prompt assembly, output validation, regeneration, or state-machine
legality checks. Those are explicitly Phase 4 deliverables (DESIGN.md
Section 17) and are not implemented here.

`AlwaysEscalateEngine` is the safe default the app wires up until Phase 4
exists: if this pipeline were ever triggered before Phase 4 is built, it
escalates to a human instead of guessing at a reply.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from nurture.ghl.models import Contact, Message


class EngineDecision(BaseModel):
    """Mirrors the `respond` tool's input_schema (DESIGN.md Appendix B)."""

    reply: str
    stage: str
    extracted: dict[str, str]
    escalate: bool
    escalation_reason: str | None = None


class ConversationEngine(Protocol):
    async def decide(
        self,
        *,
        contact: Contact,
        thread: list[Message],
        known_fields: dict[str, str],
    ) -> EngineDecision: ...


class AlwaysEscalateEngine(ConversationEngine):
    """Safe placeholder used wherever the real engine (Phase 4) would be
    wired in. Never invents a reply — always escalates."""

    async def decide(
        self,
        *,
        contact: Contact,
        thread: list[Message],
        known_fields: dict[str, str],
    ) -> EngineDecision:
        return EngineDecision(
            reply="",
            stage="escalated",
            extracted={},
            escalate=True,
            escalation_reason="engine_not_implemented",
        )

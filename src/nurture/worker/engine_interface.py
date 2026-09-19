"""The seam between the pipeline (worker/) and the conversation engine
(engine/).

`EngineDecision` mirrors Appendix B's respond tool schema, plus audit
metadata for the turns table. `ConversationEngine` is the protocol the
pipeline calls through — implemented for real by
`engine.claude_client.ClaudeEngine` (Phase 4).

`AlwaysEscalateEngine` remains as a safe placeholder for tests and any
context where no real engine should be constructed (it never guesses a
reply, only escalates) — it was the app's default before Phase 4 built
the real engine.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from nurture.ghl.models import Contact, Message


class EngineDecision(BaseModel):
    """Mirrors the `respond` tool's input_schema (DESIGN.md Appendix B),
    plus audit metadata for the `turns` table (DESIGN.md Section 6.2).

    The metadata fields are optional with safe defaults so Phase 3's
    stub engines and AlwaysEscalateEngine don't need to supply them —
    only ClaudeEngine (Phase 4) populates them for real."""

    reply: str
    stage: str
    extracted: dict[str, str]
    escalate: bool
    escalation_reason: str | None = None

    model: str = "n/a"
    prompt_version: str = "n/a"
    tool_output: dict | None = None
    validation_errors: list[str] | None = None
    regenerated: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    latency_ms: int | None = None


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

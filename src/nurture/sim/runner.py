"""Scenario simulator (DESIGN.md Section 17 Phase 4, Appendix E).

"The simulator plays each lead_turns entry in order, runs the real
engine against FakeGHLClient, prints the transcript, and evaluates the
assertions. If the bot reaches a terminal stage early, the remaining
lead turns are skipped, and the assertions decide pass or fail."

Reuses the real pipeline (worker.pipeline.process) rather than
reimplementing a parallel mini-pipeline, so the simulator behaves
exactly like production would against a fake WhatsApp thread: guards
run, turns rows are written, human-takeover state carries across turns,
tags/fields actually update — the only thing that's fake is GHL itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from nurture.engine.state import TERMINAL_STAGES, current_stage_from_tags
from nurture.ghl import Contact, FakeGHLClient, Message
from nurture.ghl.fields import WA_CUSTOM_FIELD_KEYS
from nurture.sim.assertions import evaluate_assertions
from nurture.store.db import make_session_factory
from nurture.store.models import Base
from nurture.worker.engine_interface import ConversationEngine
from nurture.worker.pipeline import PipelineOutcome, process
from nurture.store import repository
from nurture.settings import Settings


@dataclass
class TurnRecord:
    lead_text: str
    outcome: PipelineOutcome


@dataclass
class ScenarioResult:
    scenario_id: str
    name: str
    passed: bool
    failures: list[str]
    transcript: list[TurnRecord]
    skipped_lead_turns: int


def load_scenario(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


async def run_scenario(scenario: dict, *, engine: ConversationEngine, settings: Settings) -> ScenarioResult:
    scenario_id = scenario["id"]

    # Always "live" against the fake client: dry_run would make zero
    # writes to FakeGHLClient, so the contact's tags/fields (and thus
    # stage progression) would never actually change between turns.
    # Nothing here ever touches a real WhatsApp number or Synamate.
    sim_settings = settings.model_copy(update={"send_mode": "live"})

    contact_data = scenario.get("contact", {})
    contact = Contact(
        id=f"sim-{scenario_id}",
        first_name=contact_data.get("first_name"),
        city=contact_data.get("city"),
        tags={"wa-stage-1"},
        fields={},
    )
    field_ids = {key: f"field-{key}" for key in WA_CUSTOM_FIELD_KEYS}
    ghl = FakeGHLClient(
        contacts={contact.id: contact}, threads={contact.id: []}, field_ids=field_ids
    )

    db_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = make_session_factory(db_engine)

    transcript: list[TurnRecord] = []
    lead_turns = scenario.get("lead_turns", [])
    skipped = 0

    for i, lead_text in enumerate(lead_turns):
        if current_stage_from_tags(contact.tags) in TERMINAL_STAGES:
            skipped = len(lead_turns) - i
            break

        msg_id = f"{scenario_id}-lead-{i}"
        ghl.threads[contact.id].append(
            Message(
                id=msg_id,
                direction="inbound",
                text=lead_text,
                sent_at=datetime.now(timezone.utc),
                sent_by_service=False,
            )
        )

        async with session_factory() as session:
            async with session.begin():
                event = await repository.insert_inbound_event(
                    session, contact_id=contact.id, payload={"contact_id": contact.id}
                )
            event_id = event.id

        outcome = await process(
            event_id,
            session_factory=session_factory,
            ghl=ghl,
            engine=engine,
            settings=sim_settings,
        )
        transcript.append(TurnRecord(lead_text=lead_text, outcome=outcome))

    await db_engine.dispose()

    failures = evaluate_assertions(
        scenario.get("assertions", {}),
        transcript=transcript,
        final_contact=contact,
        webinar_link=settings.webinar_link,
    )

    return ScenarioResult(
        scenario_id=scenario_id,
        name=scenario.get("name", scenario_id),
        passed=not failures,
        failures=failures,
        transcript=transcript,
        skipped_lead_turns=skipped,
    )


def format_transcript(result: ScenarioResult) -> str:
    lines = [f"=== {result.scenario_id}: {result.name} ==="]
    for i, turn in enumerate(result.transcript):
        lines.append(f"[{i}] LEAD: {turn.lead_text}")
        if turn.outcome.reply_text:
            lines.append(f"    OAWA: {turn.outcome.reply_text}")
        else:
            lines.append(f"    (no reply — status={turn.outcome.status}, reason={turn.outcome.reason})")
    if result.skipped_lead_turns:
        lines.append(f"(reached a terminal stage early; {result.skipped_lead_turns} lead turn(s) skipped)")
    lines.append("PASSED" if result.passed else "FAILED:")
    for f in result.failures:
        lines.append(f"  - {f}")
    return "\n".join(lines)

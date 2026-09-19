"""The processing pipeline (DESIGN.md Section 8).

`process(event_id, ...)` implements the full "On webhook" -> `process()`
flow: per-contact locking, supersede/dedupe checks, all pre-LLM guards
(G-1 through G-7, G-10), the (stubbed, in this phase) engine call, and
acting according to SEND_MODE. Guard order matches Section 8's numbered
steps exactly.

`run_decision()` holds the guard+engine logic shared between `process()`
(event-triggered, persists inbound_events/turns) and the `/admin/replay`
endpoint (ad hoc, forces dry_run, persists nothing to inbound_events).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nurture.ghl.client import GHLClient
from nurture.guards.pre_llm import (
    check_duplicate,
    check_human_takeover,
    check_kill_switch,
    check_non_text,
    check_optout,
    check_paused_optout_terminal,
    check_turn_cap,
    check_window_closed,
    load_optout_patterns,
)
from nurture.settings import Settings
from nurture.store import repository
from nurture.worker.actions import apply_send_mode, merge_extracted_fields
from nurture.worker.engine_interface import ConversationEngine
from nurture.worker.extracted_fields import translate_extracted
from nurture.worker.locks import ContactLock
from nurture.worker.stage_tags import ALL_STAGE_TAGS, STAGE_TAGS

logger = logging.getLogger("nurture.pipeline")


@dataclass
class PipelineOutcome:
    status: str  # "processed" | "skipped" | "superseded" | "failed"
    reason: str | None = None
    stage_before: str | None = None
    stage_after: str | None = None
    reply_text: str | None = None
    extracted: dict[str, str] | None = None
    sent: bool = False
    sent_message_id: str | None = None
    inbound_message_id: str | None = None
    send_mode: str | None = None


def _current_stage(tags: set[str]) -> str:
    for stage, tag in STAGE_TAGS.items():
        if tag in tags:
            return stage
    return "opened"  # default: Workflow A always sets wa-stage-1 before this service ever runs


async def run_decision(
    *,
    contact_id: str,
    ghl: GHLClient,
    engine: ConversationEngine,
    settings: Settings,
    session: AsyncSession,
    send_mode_override: str | None = None,
) -> PipelineOutcome:
    """Steps 3-9 of DESIGN.md Section 8: guards, engine call, send-mode
    action. Does not touch inbound_events (the caller does that)."""

    send_mode = send_mode_override or settings.send_mode

    contact = await ghl.get_contact(contact_id)

    guard = check_paused_optout_terminal(contact)
    if guard:
        outcome = await _apply_guard(guard, ghl=ghl, contact_id=contact_id, send_mode=send_mode)
        outcome.status = "skipped"
        return outcome

    thread = await ghl.get_thread(contact_id)
    last_inbound = next((m for m in reversed(thread) if m.direction == "inbound"), None)
    wa_last_processed_msg_id = contact.fields.get("wa_last_processed_msg_id")

    guard = check_duplicate(last_inbound, wa_last_processed_msg_id)
    if guard:
        outcome = await _apply_guard(guard, ghl=ghl, contact_id=contact_id, send_mode=send_mode)
        outcome.status = "skipped"
        return outcome

    assert last_inbound is not None  # check_duplicate already ruled out None

    guard = check_window_closed(
        last_inbound, now=datetime.now(timezone.utc), window_safety_hours=settings.window_safety_hours
    )
    if guard:
        outcome = await _apply_guard(guard, ghl=ghl, contact_id=contact_id, send_mode=send_mode)
        outcome.status = "skipped"
        outcome.inbound_message_id = last_inbound.id
        return outcome

    last_turn = await repository.get_last_turn(session, contact_id=contact_id)
    last_sent_message_id = last_turn.sent_message_id if last_turn else None
    guard = check_human_takeover(thread, last_sent_message_id=last_sent_message_id)
    if guard:
        outcome = await _apply_guard(guard, ghl=ghl, contact_id=contact_id, send_mode=send_mode)
        outcome.status = "skipped"
        outcome.inbound_message_id = last_inbound.id
        return outcome

    guard = check_non_text(last_inbound, escalation_message=settings.escalation_message)
    if guard:
        outcome = await _apply_guard(
            guard,
            ghl=ghl,
            contact_id=contact_id,
            send_mode=send_mode,
            field_updates={"wa_last_processed_msg_id": last_inbound.id},
        )
        outcome.status = "processed"
        outcome.inbound_message_id = last_inbound.id
        outcome.stage_before = _current_stage(contact.tags)
        outcome.stage_after = "escalated"
        return outcome

    optout_patterns = load_optout_patterns(settings.config_dir / "optout.yaml")
    guard = check_optout(
        last_inbound.text, optout_patterns, optout_message=settings.optout_message
    )
    if guard:
        outcome = await _apply_guard(
            guard,
            ghl=ghl,
            contact_id=contact_id,
            send_mode=send_mode,
            field_updates={"wa_last_processed_msg_id": last_inbound.id},
        )
        outcome.status = "processed"
        outcome.inbound_message_id = last_inbound.id
        outcome.stage_before = _current_stage(contact.tags)
        outcome.stage_after = None
        return outcome

    wa_bot_turns = int(contact.fields.get("wa_bot_turns") or 0)
    guard = check_turn_cap(
        wa_bot_turns, settings.max_bot_turns, escalation_message=settings.escalation_message
    )
    if guard:
        outcome = await _apply_guard(
            guard,
            ghl=ghl,
            contact_id=contact_id,
            send_mode=send_mode,
            field_updates={
                "wa_last_processed_msg_id": last_inbound.id,
                "wa_bot_turns": str(wa_bot_turns + 1),
            },
        )
        outcome.status = "processed"
        outcome.inbound_message_id = last_inbound.id
        outcome.stage_before = _current_stage(contact.tags)
        outcome.stage_after = "escalated"
        return outcome

    # --- Step 8: engine call (stubbed in Phase 3; see engine_interface.py) ---
    known_fields = {k: v for k, v in contact.fields.items() if v is not None}
    decision = await engine.decide(contact=contact, thread=thread, known_fields=known_fields)

    stage_before = _current_stage(contact.tags)
    wa_diagnosis_turns = int(contact.fields.get("wa_diagnosis_turns") or 0)

    if decision.escalate:
        message = settings.escalation_message
        stage_after = "escalated"
        add_tags = [STAGE_TAGS["escalated"]]
        new_diagnosis_turns = 0
        escalation_reason = decision.escalation_reason or "engine_escalated"
    else:
        message = decision.reply
        stage_after = decision.stage
        add_tags = [STAGE_TAGS[stage_after]] if stage_after in STAGE_TAGS else []
        new_diagnosis_turns = wa_diagnosis_turns + 1 if stage_after == "diagnosis" else 0
        escalation_reason = None

    remove_tags = [t for t in contact.tags if t in ALL_STAGE_TAGS and t not in add_tags]

    field_updates = merge_extracted_fields(translate_extracted(decision.extracted))
    field_updates["wa_last_processed_msg_id"] = last_inbound.id
    field_updates["wa_bot_turns"] = str(wa_bot_turns + 1)
    field_updates["wa_diagnosis_turns"] = str(new_diagnosis_turns)
    if escalation_reason:
        field_updates["wa_escalation_reason"] = escalation_reason

    send_outcome = await apply_send_mode(
        ghl=ghl,
        send_mode=send_mode,
        contact_id=contact_id,
        message=message,
        add_tags=add_tags,
        remove_tags=remove_tags,
        field_updates=field_updates,
    )

    return PipelineOutcome(
        status="processed",
        reason=escalation_reason,
        stage_before=stage_before,
        stage_after=stage_after,
        reply_text=message,
        extracted=decision.extracted,
        sent=send_outcome.sent,
        sent_message_id=send_outcome.message_id,
        inbound_message_id=last_inbound.id,
        send_mode=send_mode,
    )


async def _apply_guard(
    guard,
    *,
    ghl: GHLClient,
    contact_id: str,
    send_mode: str,
    field_updates: dict[str, str] | None = None,
) -> PipelineOutcome:
    send_outcome = await apply_send_mode(
        ghl=ghl,
        send_mode=send_mode,
        contact_id=contact_id,
        message=guard.send_message,
        add_tags=guard.add_tags,
        remove_tags=guard.remove_tags,
        field_updates=field_updates or {},
    )
    return PipelineOutcome(
        status="skipped",  # overwritten by caller where the guard actually "processed" something
        reason=guard.reason,
        reply_text=guard.send_message,
        sent=send_outcome.sent,
        sent_message_id=send_outcome.message_id,
        send_mode=send_mode,
    )


async def process(
    event_id: int,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    ghl: GHLClient,
    engine: ConversationEngine,
    settings: Settings,
) -> PipelineOutcome:
    """DESIGN.md Section 8, `process(event_id)`."""

    async with session_factory() as session:
        async with session.begin():
            event = await repository.get_event(session, event_id)
            if event is None:
                logger.error("process: event %s not found", event_id)
                return PipelineOutcome(status="failed", reason="event_not_found")
            if event.status != "pending":
                return PipelineOutcome(status=event.status, reason=event.status_reason)

            async with ContactLock(session, event.contact_id):
                # G-10: pre-everything.
                guard = check_kill_switch(settings.bot_enabled)
                if guard:
                    await repository.mark_event_status(
                        session, event, status="skipped", reason=guard.reason
                    )
                    return PipelineOutcome(status="skipped", reason=guard.reason)

                if await repository.has_newer_pending_event(
                    session,
                    contact_id=event.contact_id,
                    received_at=event.received_at,
                    exclude_id=event.id,
                ):
                    await repository.mark_event_status(session, event, status="superseded")
                    return PipelineOutcome(status="superseded")

                try:
                    outcome = await run_decision(
                        contact_id=event.contact_id,
                        ghl=ghl,
                        engine=engine,
                        settings=settings,
                        session=session,
                    )
                except Exception as exc:  # noqa: BLE001 - DESIGN.md Section 8/12: never crash, never message the lead
                    logger.exception("process: event %s failed", event_id)
                    await repository.mark_event_status(
                        session, event, status="failed", reason=str(exc)
                    )
                    return PipelineOutcome(status="failed", reason=str(exc))

                await repository.mark_event_status(
                    session,
                    event,
                    status=outcome.status,
                    reason=outcome.reason,
                    processed_at=datetime.now(timezone.utc),
                )

                if outcome.inbound_message_id is not None:
                    await repository.insert_turn(
                        session,
                        contact_id=event.contact_id,
                        event_id=event.id,
                        inbound_message_id=outcome.inbound_message_id,
                        stage_before=outcome.stage_before or "unknown",
                        stage_after=outcome.stage_after,
                        model="stub" if outcome.status == "processed" else "n/a",
                        prompt_version="n/a",  # Phase 4 fills this in for real engine calls
                        tool_output={"extracted": outcome.extracted} if outcome.extracted else None,
                        reply_text=outcome.reply_text,
                        send_mode=outcome.send_mode or settings.send_mode,
                        sent=outcome.sent,
                        sent_message_id=outcome.sent_message_id,
                    )

                return outcome

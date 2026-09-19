"""Pipeline integration tests (DESIGN.md Section 16): full process() with
FakeGHLClient, SQLite, and a stubbed engine. Covers every row of Section
10 (G-1 to G-7, G-10) and all three send modes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nurture.ghl import Contact, FakeGHLClient, Message
from nurture.ghl.fields import WA_CUSTOM_FIELD_KEYS
from nurture.settings import Settings
from nurture.store import repository
from nurture.worker.engine_interface import EngineDecision
from nurture.worker.pipeline import process


def make_field_ids() -> dict[str, str]:
    return {key: f"field-id-{key}" for key in WA_CUSTOM_FIELD_KEYS}


def make_contact(**overrides) -> Contact:
    defaults = dict(id="c1", first_name="Rahul", city="Pune", tags={"wa-stage-1"}, fields={})
    defaults.update(overrides)
    return Contact(**defaults)


def make_message(**overrides) -> Message:
    defaults = dict(
        id="m1",
        direction="inbound",
        text="hello",
        sent_at=datetime.now(timezone.utc),
        sent_by_service=False,
    )
    defaults.update(overrides)
    return Message(**defaults)


def settings_with(valid_settings_kwargs, **overrides) -> Settings:
    kwargs = dict(valid_settings_kwargs)
    kwargs.update(overrides)
    return Settings(_env_file=None, **kwargs)


async def insert_event(db_session_factory, *, contact_id: str, received_at=None) -> int:
    async with db_session_factory() as session:
        async with session.begin():
            event = await repository.insert_inbound_event(
                session, contact_id=contact_id, payload={"contact_id": contact_id}
            )
            if received_at is not None:
                event.received_at = received_at
        return event.id


DECISION_BASICS = EngineDecision(
    reply="Got it — and how many years have you been in business?",
    stage="basics",
    extracted={"aum": "6 crore"},
    escalate=False,
)


# --- G-10: kill switch -------------------------------------------------------


async def test_g10_kill_switch_processes_nothing(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    contact = make_contact()
    fake_ghl = FakeGHLClient(contacts={"c1": contact}, threads={"c1": []}, field_ids=make_field_ids())
    engine = stub_engine_factory(DECISION_BASICS)
    settings = settings_with(valid_settings_kwargs, bot_enabled=False)
    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert outcome.status == "skipped"
    assert outcome.reason == "bot_disabled"
    assert fake_ghl.calls == []  # "pre-everything": no GHL calls at all
    assert engine.calls == []


# --- G-1: paused / optout / manual review / terminal ------------------------


@pytest.mark.parametrize(
    "tag,reason",
    [
        ("wa-paused", "paused"),
        ("wa-optout", "opted_out"),
        ("wa-manual-review", "manual_review"),
        ("wa-confirmed", "terminal_stage"),
    ],
)
async def test_g1_skips_silently(
    db_session_factory, valid_settings_kwargs, stub_engine_factory, tag, reason
):
    contact = make_contact(tags={tag})
    fake_ghl = FakeGHLClient(contacts={"c1": contact}, threads={"c1": []}, field_ids=make_field_ids())
    engine = stub_engine_factory(DECISION_BASICS)
    settings = settings_with(valid_settings_kwargs, send_mode="live")
    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert outcome.status == "skipped"
    assert outcome.reason == reason
    assert engine.calls == []
    # Only get_contact should have run — no thread fetch, no writes.
    assert [c.method for c in fake_ghl.calls] == ["get_contact"]


# --- G-2: duplicate -----------------------------------------------------------


async def test_g2_duplicate_message_is_skipped(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    msg = make_message(id="already-seen")
    contact = make_contact(fields={"wa_last_processed_msg_id": "already-seen"})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [msg]}, field_ids=make_field_ids()
    )
    engine = stub_engine_factory(DECISION_BASICS)
    settings = settings_with(valid_settings_kwargs, send_mode="live")
    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert outcome.status == "skipped"
    assert outcome.reason == "duplicate"
    assert engine.calls == []


async def test_g2_no_inbound_message_is_skipped(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    contact = make_contact()
    fake_ghl = FakeGHLClient(contacts={"c1": contact}, threads={"c1": []}, field_ids=make_field_ids())
    engine = stub_engine_factory(DECISION_BASICS)
    settings = settings_with(valid_settings_kwargs, send_mode="live")
    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert outcome.status == "skipped"
    assert outcome.reason == "duplicate"


# --- G-3: window closed -------------------------------------------------------


async def test_g3_window_closed_tags_manual_review(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    old_msg = make_message(
        id="old-msg", sent_at=datetime.now(timezone.utc) - timedelta(hours=30)
    )
    contact = make_contact()
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [old_msg]}, field_ids=make_field_ids()
    )
    engine = stub_engine_factory(DECISION_BASICS)
    settings = settings_with(valid_settings_kwargs, send_mode="live", window_safety_hours=23.5)
    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert outcome.status == "skipped"
    assert outcome.reason == "window_closed"
    assert "wa-manual-review" in contact.tags
    assert engine.calls == []


# --- G-4: human takeover -------------------------------------------------------


async def test_g4_human_takeover_pauses(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    inbound = make_message(id="lead-reply", direction="inbound", text="hi")
    human_outbound = make_message(
        id="human-msg", direction="outbound", text="hey it's Priya from the team"
    )
    contact = make_contact()
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact},
        threads={"c1": [human_outbound, inbound]},
        field_ids=make_field_ids(),
    )
    engine = stub_engine_factory(DECISION_BASICS)
    settings = settings_with(valid_settings_kwargs, send_mode="live")

    # Simulate a prior bot turn whose sent id does NOT match the thread's
    # last outbound message, i.e. a human sent something after the bot.
    async with db_session_factory() as session:
        async with session.begin():
            await repository.insert_turn(
                session,
                contact_id="c1",
                inbound_message_id="earlier-msg",
                stage_before="opened",
                stage_after="basics",
                model="stub",
                prompt_version="n/a",
                reply_text="hi",
                send_mode="live",
                sent=True,
                sent_message_id="bot-earlier-msg",
            )

    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert outcome.status == "skipped"
    assert outcome.reason == "human_active"
    assert "wa-paused" in contact.tags
    assert engine.calls == []


async def test_g4_does_not_trigger_on_first_ever_turn(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    opener = make_message(id="opener", direction="outbound", text="Hi, what's your AUM?")
    inbound = make_message(id="lead-reply", direction="inbound", text="6 crore")
    contact = make_contact()
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [opener, inbound]}, field_ids=make_field_ids()
    )
    engine = stub_engine_factory(DECISION_BASICS)
    settings = settings_with(valid_settings_kwargs, send_mode="dry_run")
    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    # No prior turn recorded -> the opener template is not a takeover.
    assert outcome.status == "processed"
    assert outcome.reason != "human_active"
    assert len(engine.calls) == 1


# --- G-7: non-text -------------------------------------------------------------


async def test_g7_non_text_escalates(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    inbound = make_message(id="voice-note", text="")
    contact = make_contact()
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [inbound]}, field_ids=make_field_ids()
    )
    engine = stub_engine_factory(DECISION_BASICS)
    settings = settings_with(valid_settings_kwargs, send_mode="live")
    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert outcome.status == "processed"
    assert outcome.reason == "non_text_message"
    assert outcome.reply_text == settings.escalation_message
    assert "wa-escalated" in contact.tags
    assert engine.calls == []  # escalated before ever reaching the engine


# --- G-5: opt-out ---------------------------------------------------------------


async def test_g5_optout_removes_stage_tags_and_adds_optout(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    inbound = make_message(id="stop-msg", text="stop")
    contact = make_contact(tags={"wa-stage-3"})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [inbound]}, field_ids=make_field_ids()
    )
    engine = stub_engine_factory(DECISION_BASICS)
    settings = settings_with(valid_settings_kwargs, send_mode="live")
    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert outcome.status == "processed"
    assert outcome.reason == "optout_keyword"
    assert outcome.reply_text == settings.optout_message
    assert "wa-optout" in contact.tags
    assert "wa-stage-3" not in contact.tags
    assert engine.calls == []


# --- G-6: turn cap ---------------------------------------------------------------


async def test_g6_turn_cap_escalates(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    inbound = make_message(id="reply-11")
    contact = make_contact(fields={"wa_bot_turns": "10"})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [inbound]}, field_ids=make_field_ids()
    )
    engine = stub_engine_factory(DECISION_BASICS)
    settings = settings_with(valid_settings_kwargs, send_mode="live", max_bot_turns=10)
    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert outcome.status == "processed"
    assert outcome.reason == "max_bot_turns_exceeded"
    assert "wa-escalated" in contact.tags
    assert engine.calls == []


# --- Supersede (dedupe of rapid-fire webhook events) ----------------------------


async def test_superseded_event_is_marked_and_not_processed(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    contact = make_contact()
    fake_ghl = FakeGHLClient(contacts={"c1": contact}, threads={"c1": []}, field_ids=make_field_ids())
    engine = stub_engine_factory(DECISION_BASICS)
    settings = settings_with(valid_settings_kwargs, send_mode="dry_run")

    now = datetime.now(timezone.utc)
    older_event_id = await insert_event(db_session_factory, contact_id="c1", received_at=now)
    newer_event_id = await insert_event(
        db_session_factory, contact_id="c1", received_at=now + timedelta(seconds=1)
    )

    outcome = await process(
        older_event_id,
        session_factory=db_session_factory,
        ghl=fake_ghl,
        engine=engine,
        settings=settings,
    )

    assert outcome.status == "superseded"
    assert fake_ghl.calls == []  # never even touched GHL
    assert engine.calls == []

    async with db_session_factory() as session:
        newer_event = await repository.get_event(session, newer_event_id)
        assert newer_event.status == "pending"  # untouched, ready for its own processing


# --- Normal processing across all three send modes ------------------------------


@pytest.mark.parametrize("send_mode", ["dry_run", "shadow", "live"])
async def test_normal_turn_across_send_modes(
    db_session_factory, valid_settings_kwargs, stub_engine_factory, send_mode
):
    inbound = make_message(id="lead-reply-1", text="6 crore, 3 saal se")
    opener = make_message(id="opener", direction="outbound", text="Hi, AUM?")
    contact = make_contact(tags={"wa-stage-1"})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [opener, inbound]}, field_ids=make_field_ids()
    )
    engine = stub_engine_factory(DECISION_BASICS)
    settings = settings_with(valid_settings_kwargs, send_mode=send_mode)
    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert outcome.status == "processed"
    assert outcome.stage_before == "opened"
    assert outcome.stage_after == "basics"
    assert len(engine.calls) == 1

    called_methods = [c.method for c in fake_ghl.calls]

    if send_mode == "dry_run":
        assert "send_whatsapp" not in called_methods
        assert "add_note" not in called_methods
        assert "update_custom_fields" not in called_methods
        assert "set_tags" not in called_methods
        assert outcome.sent is False
        assert outcome.sent_message_id is None
        # Contact state must be completely untouched.
        assert contact.tags == {"wa-stage-1"}
        assert contact.fields == {}
    elif send_mode == "shadow":
        assert "add_note" in called_methods
        assert "send_whatsapp" not in called_methods
        assert fake_ghl.notes["c1"][0].startswith("[BOT DRAFT — send manually] ")
        assert outcome.sent is True
        assert outcome.sent_message_id is None
        assert "wa-stage-2" in contact.tags
        assert "wa-stage-1" not in contact.tags
        assert contact.fields["wa_aum"] == "6 crore"
    else:  # live
        assert "send_whatsapp" in called_methods
        assert outcome.sent is True
        assert outcome.sent_message_id is not None
        assert "wa-stage-2" in contact.tags
        assert "wa-stage-1" not in contact.tags
        assert contact.fields["wa_aum"] == "6 crore"
        assert contact.fields["wa_bot_turns"] == "1"

    # turns row persisted regardless of mode
    async with db_session_factory() as session:
        turn = await repository.get_last_turn(session, contact_id="c1")
        assert turn is not None
        assert turn.reply_text == DECISION_BASICS.reply
        assert turn.send_mode == send_mode
        assert turn.inbound_message_id == "lead-reply-1"


async def test_engine_escalation_sends_fixed_escalation_message(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    inbound = make_message(id="fee-question", text="what does the program cost?")
    contact = make_contact(tags={"wa-stage-3"})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [inbound]}, field_ids=make_field_ids()
    )
    escalate_decision = EngineDecision(
        reply="",
        stage="escalated",
        extracted={},
        escalate=True,
        escalation_reason="asked_about_fees",
    )
    engine = stub_engine_factory(escalate_decision)
    settings = settings_with(valid_settings_kwargs, send_mode="live")
    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert outcome.status == "processed"
    assert outcome.stage_after == "escalated"
    assert outcome.reply_text == settings.escalation_message  # NOT decision.reply
    assert "wa-escalated" in contact.tags
    assert "wa-stage-3" not in contact.tags
    assert contact.fields["wa_escalation_reason"] == "asked_about_fees"


async def test_diagnosis_turn_counter_increments_and_resets(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    inbound = make_message(id="diag-reply-1")
    contact = make_contact(tags={"wa-stage-4"}, fields={"wa_diagnosis_turns": "1"})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [inbound]}, field_ids=make_field_ids()
    )
    decision = EngineDecision(
        reply="How long has this been going on?", stage="diagnosis", extracted={}, escalate=False
    )
    engine = stub_engine_factory(decision)
    settings = settings_with(valid_settings_kwargs, send_mode="live")
    event_id = await insert_event(db_session_factory, contact_id="c1")

    await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert contact.fields["wa_diagnosis_turns"] == "2"


async def test_llm_unavailable_tags_but_sends_no_message(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    inbound = make_message(id="reply-during-outage")
    contact = make_contact(tags={"wa-stage-2"})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [inbound]}, field_ids=make_field_ids()
    )
    decision = EngineDecision(
        reply="",
        stage="escalated",
        extracted={},
        escalate=True,
        escalation_reason="llm_unavailable",
    )
    engine = stub_engine_factory(decision)
    settings = settings_with(valid_settings_kwargs, send_mode="live")
    event_id = await insert_event(db_session_factory, contact_id="c1")

    outcome = await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    assert outcome.status == "processed"
    assert outcome.reply_text is None  # DESIGN.md Section 7.3/9.5: no message, tag only
    assert outcome.sent is False
    assert "send_whatsapp" not in [c.method for c in fake_ghl.calls]
    assert "wa-escalated" in contact.tags
    assert contact.fields["wa_escalation_reason"] == "llm_unavailable"


async def test_turns_row_captures_engine_audit_metadata(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    inbound = make_message(id="lead-reply-audit")
    contact = make_contact(tags={"wa-stage-1"})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [inbound]}, field_ids=make_field_ids()
    )
    decision = EngineDecision(
        reply="Got it, years in business?",
        stage="basics",
        extracted={"aum": "6 crore"},
        escalate=False,
        model="claude-sonnet-5",
        prompt_version="deadbeef1234",
        tool_output={"reply": "Got it, years in business?", "stage": "basics"},
        regenerated=True,
        input_tokens=111,
        output_tokens=22,
        cache_read_tokens=5,
        latency_ms=987,
    )
    engine = stub_engine_factory(decision)
    settings = settings_with(valid_settings_kwargs, send_mode="live")
    event_id = await insert_event(db_session_factory, contact_id="c1")

    await process(
        event_id, session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    async with db_session_factory() as session:
        turn = await repository.get_last_turn(session, contact_id="c1")

    assert turn.model == "claude-sonnet-5"
    assert turn.prompt_version == "deadbeef1234"
    assert turn.tool_output == {"reply": "Got it, years in business?", "stage": "basics"}
    assert turn.regenerated is True
    assert turn.input_tokens == 111
    assert turn.output_tokens == 22
    assert turn.cache_read_tokens == 5
    assert turn.latency_ms == 987

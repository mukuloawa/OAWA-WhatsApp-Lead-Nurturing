from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nurture.ghl.models import Contact, Message
from nurture.guards.pre_llm import (
    check_duplicate,
    check_human_takeover,
    check_kill_switch,
    check_non_text,
    check_optout,
    check_paused_optout_terminal,
    check_turn_cap,
    check_window_closed,
)


def make_contact(**overrides) -> Contact:
    defaults = dict(id="c1", first_name="Rahul", city="Pune", tags=set(), fields={})
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


# --- G-10 -----------------------------------------------------------------


def test_g10_kill_switch_triggers_when_bot_disabled():
    result = check_kill_switch(bot_enabled=False)
    assert result is not None
    assert result.action == "skip"
    assert result.reason == "bot_disabled"


def test_g10_kill_switch_does_not_trigger_when_enabled():
    assert check_kill_switch(bot_enabled=True) is None


# --- G-1 --------------------------------------------------------------------


@pytest.mark.parametrize(
    "tag,expected_reason",
    [
        ("wa-paused", "paused"),
        ("wa-optout", "opted_out"),
        ("wa-manual-review", "manual_review"),
        ("wa-confirmed", "terminal_stage"),
        ("wa-declined", "terminal_stage"),
        ("wa-escalated", "terminal_stage"),
    ],
)
def test_g1_triggers_for_each_blocking_tag(tag, expected_reason):
    contact = make_contact(tags={tag})
    result = check_paused_optout_terminal(contact)
    assert result is not None
    assert result.action == "skip"
    assert result.reason == expected_reason


def test_g1_does_not_trigger_for_normal_stage_tag():
    contact = make_contact(tags={"wa-stage-2"})
    assert check_paused_optout_terminal(contact) is None


# --- G-2 --------------------------------------------------------------------


def test_g2_triggers_when_no_inbound_message():
    result = check_duplicate(None, "some-id")
    assert result is not None
    assert result.reason == "duplicate"


def test_g2_triggers_when_message_id_matches_last_processed():
    msg = make_message(id="m42")
    result = check_duplicate(msg, "m42")
    assert result is not None
    assert result.reason == "duplicate"


def test_g2_does_not_trigger_for_new_message():
    msg = make_message(id="m43")
    assert check_duplicate(msg, "m42") is None


def test_g2_does_not_trigger_when_no_prior_processed_id():
    msg = make_message(id="m43")
    assert check_duplicate(msg, None) is None


# --- G-3 --------------------------------------------------------------------


def test_g3_triggers_when_window_closed():
    old_msg = make_message(sent_at=datetime.now(timezone.utc) - timedelta(hours=24))
    result = check_window_closed(old_msg, now=datetime.now(timezone.utc), window_safety_hours=23.5)
    assert result is not None
    assert result.reason == "window_closed"
    assert result.add_tags == ["wa-manual-review"]


def test_g3_does_not_trigger_within_window():
    recent_msg = make_message(sent_at=datetime.now(timezone.utc) - timedelta(hours=1))
    result = check_window_closed(recent_msg, now=datetime.now(timezone.utc), window_safety_hours=23.5)
    assert result is None


# --- G-4 --------------------------------------------------------------------


def test_g4_does_not_trigger_before_first_bot_turn():
    thread = [make_message(id="opener", direction="outbound")]
    result = check_human_takeover(thread, last_sent_message_id=None)
    assert result is None


def test_g4_triggers_when_last_outbound_is_not_ours():
    thread = [
        make_message(id="bot-msg-1", direction="outbound"),
        make_message(id="human-msg-1", direction="outbound"),
    ]
    result = check_human_takeover(thread, last_sent_message_id="bot-msg-1")
    assert result is not None
    assert result.action == "pause"
    assert result.reason == "human_active"
    assert result.add_tags == ["wa-paused"]


def test_g4_does_not_trigger_when_last_outbound_is_ours():
    thread = [make_message(id="bot-msg-1", direction="outbound")]
    result = check_human_takeover(thread, last_sent_message_id="bot-msg-1")
    assert result is None


# --- G-7 --------------------------------------------------------------------


def test_g7_triggers_for_empty_text_message():
    msg = make_message(text="")
    result = check_non_text(msg, escalation_message="please hold")
    assert result is not None
    assert result.reason == "non_text_message"
    assert result.send_message == "please hold"


def test_g7_does_not_trigger_for_text_message():
    msg = make_message(text="hello there")
    assert check_non_text(msg, escalation_message="please hold") is None


# --- G-5 --------------------------------------------------------------------


@pytest.mark.parametrize("text", ["stop", "Stop", "STOP", "unsubscribe", "band karo", "stop please"])
def test_g5_triggers_for_optout_keywords(text):
    patterns = ["stop", "unsubscribe", "band karo"]
    result = check_optout(text, patterns, optout_message="bye")
    assert result is not None
    assert result.action == "optout"
    assert result.send_message == "bye"


def test_g5_does_not_trigger_for_unrelated_text():
    patterns = ["stop", "unsubscribe"]
    assert check_optout("I want to stop losing clients", patterns, optout_message="bye") is None


# --- G-6 --------------------------------------------------------------------


def test_g6_triggers_at_cap():
    result = check_turn_cap(10, 10, escalation_message="hold on")
    assert result is not None
    assert result.reason == "max_bot_turns_exceeded"
    assert result.send_message == "hold on"


def test_g6_does_not_trigger_below_cap():
    assert check_turn_cap(9, 10, escalation_message="hold on") is None

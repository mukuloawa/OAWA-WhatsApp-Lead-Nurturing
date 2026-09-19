from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from nurture.engine.prompt import (
    build_user_message,
    compute_prompt_version,
    render_agenda_bullets,
    render_conversation,
    render_system_prompt,
)
from nurture.ghl.models import Contact, Message

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_render_system_prompt_substitutes_all_tokens():
    rendered = render_system_prompt(
        prompts_dir=REPO_ROOT / "prompts",
        config_dir=REPO_ROOT / "config",
        session_name="AUM Strategic Diagnostic",
        session_when="Saturday, 11:00 AM IST",
        session_cost="free",
        max_diagnosis_turns=3,
    )
    assert "<<" not in rendered  # no leftover tokens
    assert "AUM Strategic Diagnostic" in rendered
    assert "Saturday, 11:00 AM IST" in rendered
    assert "free" in rendered
    assert "3" in rendered  # MAX_DIAGNOSIS_TURNS


def test_prompt_version_is_stable_for_same_input():
    a = compute_prompt_version("hello world")
    b = compute_prompt_version("hello world")
    assert a == b
    assert len(a) == 12


def test_prompt_version_changes_with_content():
    a = compute_prompt_version("hello world")
    b = compute_prompt_version("hello world!")
    assert a != b


def test_render_agenda_bullets_lists_each_item(tmp_path):
    agenda_file = tmp_path / "agenda.yaml"
    agenda_file.write_text("agenda:\n  - First item\n  - Second item\n")
    bullets = render_agenda_bullets(agenda_file)
    assert bullets == "- First item\n- Second item"


def _msg(**overrides):
    defaults = dict(
        id="m1", direction="inbound", text="hi", sent_at=datetime.now(timezone.utc), sent_by_service=False
    )
    defaults.update(overrides)
    return Message(**defaults)


def test_render_conversation_labels_speakers():
    thread = [
        _msg(id="1", direction="outbound", text="Hi, AUM?"),
        _msg(id="2", direction="inbound", text="6 crore"),
    ]
    rendered = render_conversation(thread)
    assert rendered == "OAWA: Hi, AUM?\nLEAD: 6 crore"


def test_render_conversation_trims_long_messages():
    thread = [_msg(text="x" * 2000)]
    rendered = render_conversation(thread)
    assert len(rendered) == len("LEAD: ") + 1500


def test_render_conversation_limits_to_last_30_messages():
    thread = [_msg(id=str(i), text=f"msg {i}") for i in range(40)]
    rendered = render_conversation(thread)
    lines = rendered.split("\n")
    assert len(lines) == 30
    assert lines[0] == "LEAD: msg 10"
    assert lines[-1] == "LEAD: msg 39"


def test_render_conversation_renders_empty_text_as_non_text_placeholder():
    thread = [_msg(text="")]
    rendered = render_conversation(thread)
    assert rendered == "LEAD: [sent a non-text message]"


def test_build_user_message_includes_known_fields_and_conversation():
    contact = Contact(id="c1", first_name="Rahul", city="Pune", tags=set(), fields={})
    thread = [_msg(id="1", direction="inbound", text="6 crore")]
    message = build_user_message(
        contact=contact,
        thread=thread,
        current_stage="basics",
        known_fields={"aum": "6 crore"},
        diagnosis_turns_so_far=0,
    )
    assert "KNOWN FIELDS (JSON):" in message
    assert '"first_name": "Rahul"' in message
    assert '"city_from_registration": "Pune"' in message
    assert '"current_stage": "basics"' in message
    assert '"aum": "6 crore"' in message
    assert "CONVERSATION SO FAR (oldest first):" in message
    assert "LEAD: 6 crore" in message
    assert message.endswith("Write OAWA's next message by calling the respond tool.")

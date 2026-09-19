"""Pre-LLM guards G-1 through G-7 and G-10 (DESIGN.md Section 10).

Deterministic, testable in isolation from the pipeline that calls them
(DESIGN.md Section 4: "Deterministic checks before and after the LLM").
Post-LLM guards G-8/G-9 (output validation, stage-transition legality)
are Phase 4 work and are not implemented here.

Two guards rely on interpretations DESIGN.md doesn't fully pin down —
each is called out below and repeated in docs/phase3-notes.md:

- G-4 (human takeover): DESIGN.md says "if there is any outbound message
  after the last outbound the service sent, and it isn't a known
  template". There is no field anywhere (verified in Phase 0/2) that
  marks a message as "a known template" vs. human-sent. This
  implementation instead compares the thread's last outbound message id
  against the id this service itself last sent (via the new
  turns.sent_message_id column), and simply skips the check before the
  service's first-ever turn for a contact (so the opener/nudge templates
  are never mistaken for a takeover) rather than trying to classify
  message provenance.
- G-7 (non-text latest message): the Message model (DESIGN.md Section
  7.2, unchanged) carries no content-type/attachment field, so there is
  no direct signal to detect "voice note / image / sticker" beyond an
  empty message body. Phase 2's real fixtures show attachment-only
  messages do have an empty body. This implementation treats an
  empty-text latest inbound message as non-text. Worst case for this
  approximation is a literally-blank inbound text message being
  escalated to a human, which is a safe failure direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml

from nurture.ghl.models import Contact, Message
from nurture.worker.stage_tags import ALL_STAGE_TAGS, FLAG_TAGS, STAGE_TAGS, TERMINAL_STAGE_TAGS

GuardAction = Literal["skip", "pause", "optout", "escalate"]


@dataclass
class GuardResult:
    action: GuardAction
    reason: str
    add_tags: list[str] = field(default_factory=list)
    remove_tags: list[str] = field(default_factory=list)
    send_message: str | None = None  # sent via the active send mode, if not None


# --- G-10: global kill switch --------------------------------------------


def check_kill_switch(bot_enabled: bool) -> GuardResult | None:
    if bot_enabled:
        return None
    return GuardResult(action="skip", reason="bot_disabled")


# --- G-1: paused / opted out / manual review / terminal stage -------------


def check_paused_optout_terminal(contact: Contact) -> GuardResult | None:
    if FLAG_TAGS["paused"] in contact.tags:
        return GuardResult(action="skip", reason="paused")
    if FLAG_TAGS["optout"] in contact.tags:
        return GuardResult(action="skip", reason="opted_out")
    if FLAG_TAGS["manual_review"] in contact.tags:
        return GuardResult(action="skip", reason="manual_review")
    if contact.tags & TERMINAL_STAGE_TAGS:
        return GuardResult(action="skip", reason="terminal_stage")
    return None


# --- G-2: duplicate inbound message ----------------------------------------


def check_duplicate(
    last_inbound: Message | None, wa_last_processed_msg_id: str | None
) -> GuardResult | None:
    if last_inbound is None:
        return GuardResult(action="skip", reason="duplicate")
    if wa_last_processed_msg_id and last_inbound.id == wa_last_processed_msg_id:
        return GuardResult(action="skip", reason="duplicate")
    return None


# --- G-3: 24h window closed -------------------------------------------------


def check_window_closed(
    last_inbound: Message, *, now: datetime, window_safety_hours: float
) -> GuardResult | None:
    sent_at = last_inbound.sent_at
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    age_hours = (now - sent_at).total_seconds() / 3600
    if age_hours > window_safety_hours:
        return GuardResult(
            action="skip", reason="window_closed", add_tags=[FLAG_TAGS["manual_review"]]
        )
    return None


# --- G-4: human takeover -----------------------------------------------------


def check_human_takeover(
    thread: list[Message], *, last_sent_message_id: str | None
) -> GuardResult | None:
    if last_sent_message_id is None:
        # No turn recorded yet for this contact: nothing to compare
        # against, so an existing outbound message (e.g. the opener
        # template) is never mistaken for a takeover. See module
        # docstring.
        return None
    outbound = [m for m in thread if m.direction == "outbound"]
    if not outbound:
        return None
    last_outbound = outbound[-1]
    if last_outbound.id != last_sent_message_id:
        return GuardResult(
            action="pause", reason="human_active", add_tags=[FLAG_TAGS["paused"]]
        )
    return None


# --- G-7: non-text latest inbound message -----------------------------------


def check_non_text(last_inbound: Message, *, escalation_message: str) -> GuardResult | None:
    if last_inbound.text.strip() == "":
        return GuardResult(
            action="escalate",
            reason="non_text_message",
            add_tags=[STAGE_TAGS["escalated"]],
            send_message=escalation_message,
        )
    return None


# --- G-5: opt-out keyword ----------------------------------------------------


def load_optout_patterns(path: Path) -> list[str]:
    data = yaml.safe_load(path.read_text()) or {}
    return [str(p).strip().lower() for p in data.get("patterns", [])]


def _matches_optout(text: str, patterns: list[str]) -> bool:
    normalised = text.strip().lower()
    for pattern in patterns:
        if normalised == pattern or normalised.startswith(pattern + " "):
            return True
    return False


def check_optout(
    last_inbound_text: str, optout_patterns: list[str], *, optout_message: str
) -> GuardResult | None:
    if _matches_optout(last_inbound_text, optout_patterns):
        return GuardResult(
            action="optout",
            reason="optout_keyword",
            add_tags=[FLAG_TAGS["optout"]],
            remove_tags=list(ALL_STAGE_TAGS),
            send_message=optout_message,
        )
    return None


# --- G-6: bot turn cap -------------------------------------------------------


def check_turn_cap(
    wa_bot_turns: int, max_bot_turns: int, *, escalation_message: str
) -> GuardResult | None:
    if wa_bot_turns >= max_bot_turns:
        return GuardResult(
            action="escalate",
            reason="max_bot_turns_exceeded",
            add_tags=[STAGE_TAGS["escalated"]],
            send_message=escalation_message,
        )
    return None

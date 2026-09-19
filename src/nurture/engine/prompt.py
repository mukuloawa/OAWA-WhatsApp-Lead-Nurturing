"""Prompt assembly (DESIGN.md Section 9.1).

The system prompt is `prompts/system.md` (Appendix A), loaded and stored
as a file rather than paraphrased in code (DESIGN.md Section 0, rule 5).
Tokens are substituted at startup/per-render from config.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from nurture.ghl.models import Contact, Message

THREAD_MESSAGE_LIMIT = 30
THREAD_MESSAGE_CHAR_LIMIT = 1500


def render_agenda_bullets(agenda_path: Path) -> str:
    data = yaml.safe_load(agenda_path.read_text()) or {}
    items = data.get("agenda", [])
    return "\n".join(f"- {item}" for item in items)


def render_system_prompt(
    *,
    prompts_dir: Path,
    config_dir: Path,
    session_name: str,
    session_when: str,
    session_cost: str,
    max_diagnosis_turns: int,
) -> str:
    template = (prompts_dir / "system.md").read_text()
    agenda_bullets = render_agenda_bullets(config_dir / "agenda.yaml")
    return (
        template.replace("<<SESSION_NAME>>", session_name)
        .replace("<<SESSION_WHEN>>", session_when)
        .replace("<<SESSION_COST>>", session_cost)
        .replace("<<SESSION_AGENDA>>", agenda_bullets)
        .replace("<<MAX_DIAGNOSIS_TURNS>>", str(max_diagnosis_turns))
    )


def compute_prompt_version(rendered_system_prompt: str) -> str:
    """DESIGN.md Section 9.1: first 12 chars of the SHA-256 of the
    rendered prompt."""
    return hashlib.sha256(rendered_system_prompt.encode("utf-8")).hexdigest()[:12]


def _render_message_line(message: Message) -> str:
    speaker = "OAWA" if message.direction == "outbound" else "LEAD"
    text = message.text.strip()
    if not text:
        # DESIGN.md Section 9.1: non-text messages (images, voice notes,
        # stickers) render as "LEAD: [sent a voice note]" etc. The
        # Message model carries no content-type info to tell those
        # apart (see docs/phase3-notes.md §3), so a single generic
        # placeholder is used for all of them.
        text = "[sent a non-text message]"
    elif len(text) > THREAD_MESSAGE_CHAR_LIMIT:
        text = text[:THREAD_MESSAGE_CHAR_LIMIT]
    return f"{speaker}: {text}"


def render_conversation(thread: list[Message]) -> str:
    recent = thread[-THREAD_MESSAGE_LIMIT:]
    return "\n".join(_render_message_line(m) for m in recent)


def build_user_message(
    *,
    contact: Contact,
    thread: list[Message],
    current_stage: str,
    known_fields: dict[str, str],
    diagnosis_turns_so_far: int,
) -> str:
    known = {
        "first_name": contact.first_name,
        "city_from_registration": contact.city,
        "current_stage": current_stage,
        "aum": known_fields.get("aum", ""),
        "years_in_business": known_fields.get("years_in_business", ""),
        "problem_category": known_fields.get("problem_category", ""),
        "diagnosis_turns_so_far": diagnosis_turns_so_far,
    }
    known_json = json.dumps(known)
    conversation = render_conversation(thread)

    return (
        f"KNOWN FIELDS (JSON):\n{known_json}\n\n"
        f"CONVERSATION SO FAR (oldest first):\n{conversation}\n\n"
        "Write OAWA's next message by calling the respond tool."
    )

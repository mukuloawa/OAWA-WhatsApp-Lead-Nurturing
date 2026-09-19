"""Applying a decision (guard or engine) according to SEND_MODE (DESIGN.md
Section 8, step 9).

live:    send WhatsApp, then update custom fields, then swap tags.
shadow:  post a "[BOT DRAFT — send manually]" note, then fields, then tags.
dry_run: no GHL writes at all.

Ordering (send/note before fields/tags) matches DESIGN.md's own note:
"If the send succeeds and a later update fails, the turns row (with
sent=true and the unique constraint) prevents a double send on retry."
"""

from __future__ import annotations

from dataclasses import dataclass

from nurture.ghl.client import GHLClient

SHADOW_DRAFT_PREFIX = "[BOT DRAFT — send manually] "


@dataclass
class SendOutcome:
    sent: bool
    message_id: str | None


async def apply_send_mode(
    *,
    ghl: GHLClient,
    send_mode: str,
    contact_id: str,
    message: str | None,
    add_tags: list[str],
    remove_tags: list[str],
    field_updates: dict[str, str],
) -> SendOutcome:
    if send_mode == "dry_run":
        return SendOutcome(sent=False, message_id=None)

    if send_mode == "live":
        message_id = await ghl.send_whatsapp(contact_id, message) if message else None
        sent = message_id is not None
    elif send_mode == "shadow":
        if message:
            await ghl.add_note(contact_id, f"{SHADOW_DRAFT_PREFIX}{message}")
            sent = True
        else:
            sent = False
        message_id = None
    else:
        raise ValueError(f"unknown send_mode: {send_mode!r}")

    if field_updates:
        await ghl.update_custom_fields(contact_id, field_updates)
    if add_tags or remove_tags:
        await ghl.set_tags(contact_id, add=add_tags, remove=remove_tags)

    return SendOutcome(sent=sent, message_id=message_id)


def merge_extracted_fields(extracted: dict[str, str]) -> dict[str, str]:
    """DESIGN.md Section 6.1 merge rule: a non-empty extracted value
    overwrites the GHL field; an empty value never clears an existing
    one. Implemented by simply excluding empty values from the update
    payload — GHLClient.update_custom_fields only touches keys given to
    it, so anything excluded is left alone in GHL."""
    return {key: value for key, value in extracted.items() if value}

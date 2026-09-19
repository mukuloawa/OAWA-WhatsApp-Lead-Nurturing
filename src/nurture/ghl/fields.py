"""The 12 custom field keys this service tracks on a GHL contact.

DESIGN.md Section 6.1. None of these exist in the live account yet
(confirmed read-only in Phase 0/2 — see docs/phase0-findings.md); they
must be created by hand in the GHL UI before shadow/live mode.

Per docs/phase0-findings.md, existing custom fields are addressed by an
opaque `id`, and their `fieldKey` is namespaced as `"contact.<name>"` —
not a bare key. So a key here like `"wa_aum"` is expected to correspond
to a live GHL fieldKey of `"contact.wa_aum"` once created.
"""

from __future__ import annotations

WA_CUSTOM_FIELD_KEYS: tuple[str, ...] = (
    "wa_aum",
    "wa_years_in_business",
    "wa_problem_category",
    "wa_problem_in_their_words",
    "wa_problem_duration",
    "wa_tried_so_far",
    "wa_key_metric",
    "wa_ceiling_view",
    "wa_bot_turns",
    "wa_diagnosis_turns",
    "wa_last_processed_msg_id",
    "wa_escalation_reason",
)


def to_ghl_field_key(our_key: str) -> str:
    """Our bare key (e.g. "wa_aum") -> GHL's namespaced fieldKey."""
    return f"contact.{our_key}"


def from_ghl_field_key(ghl_field_key: str) -> str | None:
    """GHL's namespaced fieldKey -> our bare key, or None if not one of ours."""
    prefix = "contact."
    if not ghl_field_key.startswith(prefix):
        return None
    bare = ghl_field_key[len(prefix) :]
    return bare if bare in WA_CUSTOM_FIELD_KEYS else None

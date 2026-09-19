"""State machine: validates stage transitions and maps stages to tags
(DESIGN.md Section 4, Section 5, Section 5.1).

The stage<->tag data table lived in `worker/stage_tags.py` during Phase 3
(transition legality wasn't built yet); moved here in Phase 4 to match
DESIGN.md Section 4's component table, which assigns both jobs to this
module.
"""

from __future__ import annotations

STAGE_TAGS: dict[str, str] = {
    "opened": "wa-stage-1",
    "basics": "wa-stage-2",
    "problem_ask": "wa-stage-3",
    "diagnosis": "wa-stage-4",
    "invited": "wa-invited",
    "confirmed": "wa-confirmed",
    "declined": "wa-declined",
    "escalated": "wa-escalated",
}

TERMINAL_STAGE_TAGS: frozenset[str] = frozenset(
    {STAGE_TAGS["confirmed"], STAGE_TAGS["declined"], STAGE_TAGS["escalated"]}
)

ALL_STAGE_TAGS: frozenset[str] = frozenset(STAGE_TAGS.values())

FLAG_TAGS = {
    "paused": "wa-paused",
    "optout": "wa-optout",
    "followup_sent": "wa-followup-sent",
    "manual_review": "wa-manual-review",
}

TERMINAL_STAGES: frozenset[str] = frozenset({"confirmed", "declined", "escalated"})

# DESIGN.md Section 5.1 "Allowed transitions". "(any) -> escalated" is
# handled separately in is_transition_legal rather than listed in every
# row.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "opened": frozenset({"basics", "problem_ask", "escalated", "declined"}),
    "basics": frozenset({"basics", "problem_ask", "escalated", "declined"}),
    "problem_ask": frozenset({"problem_ask", "diagnosis", "escalated", "declined"}),
    "diagnosis": frozenset({"diagnosis", "invited", "escalated", "declined"}),
    "invited": frozenset({"invited", "confirmed", "declined", "escalated"}),
    "confirmed": frozenset(),
    "declined": frozenset(),
    "escalated": frozenset(),
}


def current_stage_from_tags(tags: set[str]) -> str:
    for stage, tag in STAGE_TAGS.items():
        if tag in tags:
            return stage
    return "opened"  # Workflow A always sets wa-stage-1 before this service ever runs


def is_transition_legal(
    *,
    stage_before: str,
    stage_after: str,
    wa_diagnosis_turns: int,
    max_diagnosis_turns: int,
    has_aum: bool,
    has_problem_category: bool,
) -> tuple[bool, str | None]:
    """DESIGN.md Section 5.1. Returns (legal, reason_if_not)."""

    if stage_after == "escalated":
        return True, None  # "(any) -> escalated" is always allowed

    if stage_before in TERMINAL_STAGES:
        # "confirmed, declined, escalated -> (terminal; service ignores further events)"
        return False, "stage_before_is_terminal"

    allowed = ALLOWED_TRANSITIONS.get(stage_before, frozenset())
    if stage_after not in allowed:
        return False, "transition_not_allowed"

    if stage_after == "diagnosis" and wa_diagnosis_turns >= max_diagnosis_turns:
        # "Max MAX_DIAGNOSIS_TURNS consecutive diagnosis turns. After
        # that, the next turn must be invited or escalated."
        return False, "max_diagnosis_turns_exceeded"

    if stage_after == "invited" and not (has_aum and has_problem_category):
        # "Transition to invited requires aum and problem_category to be
        # captured (in GHL or in this turn's extraction). Otherwise it
        # is treated as illegal."
        return False, "invited_requires_aum_and_problem_category"

    return True, None

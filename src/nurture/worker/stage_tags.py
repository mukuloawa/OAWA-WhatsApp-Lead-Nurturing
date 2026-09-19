"""Stage <-> GHL tag mapping (DESIGN.md Section 5's table), as plain data.

DESIGN.md Section 4 assigns "validates stage transitions and maps stages
to tags" to `engine/state.py`, a Phase 4 deliverable. Transition
*legality* (Section 5.1 — illegal-transition rejection, the
MAX_DIAGNOSIS_TURNS cap, regeneration on rejection) is genuinely Phase 4
work and is not implemented here. This module holds only the static
stage->tag lookup table itself, which the Phase 3 pipeline needs to know
which tag to add/remove when acting on a stage the (stubbed, in this
phase) engine returned.
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

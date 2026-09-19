"""Output validation rules V1-V7 (DESIGN.md Section 9.2) and link
injection (Section 9.3).

V7 is a normalisation step, not a failure: DESIGN.md says "normalise
rather than fail" for an escalate/stage mismatch, so it's applied before
the other rules run, not added to the failed-rules list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nurture.engine.state import is_transition_legal
from nurture.worker.engine_interface import EngineDecision

WEBINAR_LINK_TOKEN = "[[WEBINAR_LINK]]"

# V2: a URL, `www.`, or a bare domain (heuristic — DESIGN.md doesn't
# specify an exact pattern, just "https?://, www., or a bare domain
# pattern").
_URL_RE = re.compile(
    r"https?://\S+|www\.\S+|\b[a-zA-Z0-9-]+\.(?:com|in|co|org|net|io|me)\b", re.IGNORECASE
)

RULE_DESCRIPTIONS: dict[str, str] = {
    "V1": "the reply was empty or over 900 characters",
    "V2": "the reply contained a URL — only the [[WEBINAR_LINK]] token is allowed, and only in the invite",
    "V3": "the [[WEBINAR_LINK]] token was used outside the invite, or missing from the invite",
    "V4": "the reply contained more than one question mark — ask exactly one question",
    "V5": "the proposed stage transition is not allowed from the current stage",
    "V6": "the reply contained a banned phrase",
    "no_tool_call": "the response did not call the respond tool with valid arguments",
}


@dataclass
class ValidationResult:
    ok: bool
    failed_rules: list[str] = field(default_factory=list)


def normalise(decision: EngineDecision) -> EngineDecision:
    """V7: escalate/stage mismatch is normalised, not rejected."""
    if decision.escalate and decision.stage != "escalated":
        return decision.model_copy(update={"stage": "escalated"})
    if decision.stage == "escalated" and not decision.escalate:
        return decision.model_copy(update={"escalate": True})
    return decision


def _contains_banned_phrase(text: str, banned_phrases: list[str]) -> bool:
    lowered = text.lower()
    return any(phrase.lower() in lowered for phrase in banned_phrases)


def validate(
    decision: EngineDecision,
    *,
    stage_before: str,
    wa_diagnosis_turns: int,
    max_diagnosis_turns: int,
    has_aum: bool,
    has_problem_category: bool,
    link_already_sent: bool,
    banned_phrases: list[str],
) -> ValidationResult:
    failed: list[str] = []
    reply = decision.reply

    # V1: reply empty or > 900 chars. Does not apply when escalating
    # (Appendix B note: "when escalate=true, the service ignores reply
    # and sends ESCALATION_MESSAGE. Validation rule V1 ... does not
    # apply to escalations.")
    if not decision.escalate:
        if not reply.strip() or len(reply) > 900:
            failed.append("V1")

    # V2: URL.
    if _URL_RE.search(reply):
        failed.append("V2")

    # V3: [[WEBINAR_LINK]] token placement.
    has_token = WEBINAR_LINK_TOKEN in reply
    if has_token and decision.stage != "invited":
        failed.append("V3")
    elif decision.stage == "invited" and not has_token and not link_already_sent:
        failed.append("V3")

    # V4: more than one '?'.
    if reply.count("?") > 1:
        failed.append("V4")

    # V5: stage transition legality (DESIGN.md Section 5.1).
    legal, _reason = is_transition_legal(
        stage_before=stage_before,
        stage_after=decision.stage,
        wa_diagnosis_turns=wa_diagnosis_turns,
        max_diagnosis_turns=max_diagnosis_turns,
        has_aum=has_aum,
        has_problem_category=has_problem_category,
    )
    if not legal:
        failed.append("V5")

    # V6: banned phrases.
    if _contains_banned_phrase(reply, banned_phrases):
        failed.append("V6")

    return ValidationResult(ok=not failed, failed_rules=failed)


def describe_failed_rules(failed_rules: list[str]) -> str:
    return "; ".join(RULE_DESCRIPTIONS.get(rule, rule) for rule in failed_rules)


def inject_link(decision: EngineDecision, webinar_link: str) -> EngineDecision:
    """DESIGN.md Section 9.3: after validation, the token is replaced
    with the real link. The model never sees the real URL."""
    if WEBINAR_LINK_TOKEN not in decision.reply:
        return decision
    return decision.model_copy(
        update={"reply": decision.reply.replace(WEBINAR_LINK_TOKEN, webinar_link)}
    )

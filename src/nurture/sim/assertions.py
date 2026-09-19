"""Scenario assertion evaluation (DESIGN.md Appendix E).

Appendix E's format is only fully specified for S1's `every_turn` list
(max_one_question, no_url, max_chars_900) plus final_stage,
extracted_includes, link_sent_exactly_once, and max_diagnosis_turns. The
rest of this vocabulary (no_devanagari, any_reply_contains, etc.) is
inferred from the "Key assertions" column of Appendix E's scenario table
for S2-S13, since DESIGN.md doesn't give their literal YAML.
"""

from __future__ import annotations

import re

from nurture.engine.state import current_stage_from_tags
from nurture.worker.extracted_fields import EXTRACTED_FIELD_TO_WA_KEY

DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
URL_RE = re.compile(
    r"https?://\S+|www\.\S+|\b[a-zA-Z0-9-]+\.(?:com|in|co|org|net|io|me)\b", re.IGNORECASE
)


def evaluate_assertions(
    assertions: dict, *, transcript: list, final_contact, webinar_link: str
) -> list[str]:
    failures: list[str] = []
    replies = [t.outcome.reply_text for t in transcript if t.outcome.reply_text]

    for rule in assertions.get("every_turn", []):
        if rule == "max_one_question":
            for t in transcript:
                if t.outcome.reply_text and t.outcome.reply_text.count("?") > 1:
                    failures.append(f"max_one_question violated: {t.outcome.reply_text!r}")
        elif rule == "no_url":
            # The invite turn legitimately contains the real, already-
            # injected webinar link (DESIGN.md Section 9.3) — that's not
            # a violation. Strip it out before checking for any OTHER
            # (invented) URL.
            for t in transcript:
                if not t.outcome.reply_text:
                    continue
                text_without_real_link = t.outcome.reply_text.replace(webinar_link, "")
                if URL_RE.search(text_without_real_link):
                    failures.append(f"no_url violated: {t.outcome.reply_text!r}")
        elif rule == "max_chars_900":
            for t in transcript:
                if t.outcome.reply_text and len(t.outcome.reply_text) > 900:
                    failures.append(f"max_chars_900 violated ({len(t.outcome.reply_text)} chars)")
        else:
            failures.append(f"unknown every_turn rule: {rule!r}")

    if "final_stage" in assertions:
        expected = assertions["final_stage"]
        actual = current_stage_from_tags(final_contact.tags)
        if actual != expected:
            failures.append(f"final_stage: expected {expected!r}, got {actual!r}")

    if "extracted_includes" in assertions:
        for key, expected_value in assertions["extracted_includes"].items():
            wa_key = EXTRACTED_FIELD_TO_WA_KEY.get(key, key)
            actual_value = final_contact.fields.get(wa_key)
            if not actual_value:
                failures.append(f"extracted_includes: {key!r} was never set")
            elif expected_value and str(actual_value).lower() != str(expected_value).lower():
                failures.append(
                    f"extracted_includes: {key!r} expected {expected_value!r}, got {actual_value!r}"
                )

    if assertions.get("link_sent_exactly_once"):
        count = sum(1 for r in replies if webinar_link in r)
        if count != 1:
            failures.append(f"link_sent_exactly_once: link appeared {count} time(s)")

    if "max_diagnosis_turns" in assertions:
        diag_count = sum(1 for t in transcript if t.outcome.stage_after == "diagnosis")
        if diag_count > assertions["max_diagnosis_turns"]:
            failures.append(
                f"max_diagnosis_turns: {diag_count} > {assertions['max_diagnosis_turns']}"
            )

    if "max_bot_turns" in assertions:
        if len(transcript) > assertions["max_bot_turns"]:
            failures.append(f"max_bot_turns: took {len(transcript)} turns")

    if assertions.get("no_devanagari"):
        for r in replies:
            if DEVANAGARI_RE.search(r):
                failures.append(f"no_devanagari violated: {r!r}")

    if assertions.get("no_link_in_final_reply"):
        if replies and webinar_link in replies[-1]:
            failures.append("no_link_in_final_reply violated")

    if "any_reply_contains" in assertions:
        needle = assertions["any_reply_contains"].lower()
        if not any(needle in r.lower() for r in replies):
            failures.append(f"any_reply_contains: no reply contained {needle!r}")

    if "no_reply_contains" in assertions:
        needle = assertions["no_reply_contains"].lower()
        for r in replies:
            if needle in r.lower():
                failures.append(f"no_reply_contains violated: found {needle!r} in {r!r}")

    if "reaches_stage_within" in assertions:
        spec = assertions["reaches_stage_within"]
        allowed = spec["any_of"]
        max_turns = spec["max_turns"]
        window = transcript[:max_turns]
        if not any(t.outcome.stage_after in allowed for t in window):
            failures.append(f"reaches_stage_within: did not reach {allowed} within {max_turns} turns")

    if "min_reply_length_after_turn" in assertions:
        spec = assertions["min_reply_length_after_turn"]
        idx = spec["turn_index"]
        if idx < len(transcript):
            reply = transcript[idx].outcome.reply_text or ""
            if len(reply) < spec["min_chars"]:
                failures.append(
                    f"min_reply_length_after_turn: turn {idx} reply too short ({len(reply)} chars)"
                )

    if assertions.get("no_llm_call_made"):
        if any(t.outcome.model not in ("n/a",) for t in transcript):
            failures.append("no_llm_call_made violated: a turn actually called the engine")

    if "exactly_n_replies" in assertions:
        actual = len([t for t in transcript if t.outcome.sent])
        if actual != assertions["exactly_n_replies"]:
            failures.append(f"exactly_n_replies: expected {assertions['exactly_n_replies']}, got {actual}")

    return failures

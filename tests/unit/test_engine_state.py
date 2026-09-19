from __future__ import annotations

import pytest

from nurture.engine.state import is_transition_legal


def legal(stage_before, stage_after, **overrides):
    kwargs = dict(
        stage_before=stage_before,
        stage_after=stage_after,
        wa_diagnosis_turns=0,
        max_diagnosis_turns=3,
        has_aum=True,
        has_problem_category=True,
    )
    kwargs.update(overrides)
    ok, _reason = is_transition_legal(**kwargs)
    return ok


@pytest.mark.parametrize(
    "stage_before,stage_after",
    [
        ("opened", "basics"),
        ("opened", "problem_ask"),
        ("opened", "declined"),
        ("basics", "basics"),
        ("basics", "problem_ask"),
        ("problem_ask", "problem_ask"),
        ("problem_ask", "diagnosis"),
        ("diagnosis", "diagnosis"),
        ("diagnosis", "invited"),
        ("invited", "invited"),
        ("invited", "confirmed"),
        ("invited", "declined"),
    ],
)
def test_allowed_transitions_from_section_5_1(stage_before, stage_after):
    assert legal(stage_before, stage_after) is True


@pytest.mark.parametrize(
    "stage_before,stage_after",
    [
        ("opened", "diagnosis"),  # skips problem_ask
        ("opened", "invited"),
        ("basics", "invited"),
        ("problem_ask", "invited"),  # skips diagnosis
        ("problem_ask", "confirmed"),
        ("invited", "basics"),  # can't go backwards
    ],
)
def test_disallowed_transitions_from_section_5_1(stage_before, stage_after):
    assert legal(stage_before, stage_after) is False


@pytest.mark.parametrize("stage_before", ["opened", "basics", "problem_ask", "diagnosis", "invited"])
def test_any_stage_can_escalate(stage_before):
    assert legal(stage_before, "escalated") is True


@pytest.mark.parametrize("terminal_stage", ["confirmed", "declined", "escalated"])
def test_terminal_stages_allow_nothing_except_escalate(terminal_stage):
    assert legal(terminal_stage, "basics") is False
    assert legal(terminal_stage, "escalated") is True


def test_diagnosis_blocked_once_max_turns_reached():
    assert legal("diagnosis", "diagnosis", wa_diagnosis_turns=3, max_diagnosis_turns=3) is False
    assert legal("diagnosis", "diagnosis", wa_diagnosis_turns=2, max_diagnosis_turns=3) is True


def test_invited_requires_aum_and_problem_category():
    assert legal("diagnosis", "invited", has_aum=False, has_problem_category=True) is False
    assert legal("diagnosis", "invited", has_aum=True, has_problem_category=False) is False
    assert legal("diagnosis", "invited", has_aum=True, has_problem_category=True) is True

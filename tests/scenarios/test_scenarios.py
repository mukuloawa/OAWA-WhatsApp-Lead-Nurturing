"""Appendix E scenario tests, against the REAL Claude API (DESIGN.md
Section 16: "Scenario (live LLM) ... not run in CI by default
(`pytest -m llm`)").

This file isn't under `tests/unit`/`tests/integration`, so plain `pytest`
never collects it at all — it only runs when pointed at explicitly:

    pytest tests/scenarios/                  # S14 only (needs no API key)
    ANTHROPIC_API_KEY=... pytest -m llm tests/scenarios/   # S1-S13 for real

S14 ("stop") never reaches the engine (guard G-5 intercepts first), so
it isn't marked `llm` and runs for real with plain `pytest tests/scenarios/`
even with no API key at all. S1-S13 are marked `llm` and skip cleanly
without ANTHROPIC_API_KEY. S15-S17 are deliberately not run against the
real API here (DESIGN.md marks them "stubbed Claude" / "pipeline test"
scenarios) — see their own YAML files' comments for where they're
actually verified.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nurture.engine.claude_client import build_claude_engine
from nurture.settings import REPO_ROOT, Settings
from nurture.sim.runner import format_transcript, load_scenario, run_scenario
from nurture.worker.engine_interface import AlwaysEscalateEngine

SCENARIOS_DIR = REPO_ROOT / "scenarios"

LIVE_LLM_SCENARIOS = [f"S{i}" for i in range(1, 14)]  # S1-S13
NO_API_NEEDED_SCENARIOS = ["S14"]  # intercepted by a guard before the engine is ever called


def _scenario_settings() -> Settings:
    return Settings(
        _env_file=None,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        ghl_token="unused-scenario-token",
        ghl_location_id="unused-scenario-location",
        webhook_secret="x" * 32,
        admin_secret="unused-scenario-admin-secret",
        database_url="sqlite+aiosqlite:///:memory:",
        webinar_link="https://oawa.example/webinar",
        session_when="Saturday, 11:00 AM IST",
        session_name="AUM Strategic Diagnostic",
        session_cost="free",
        config_dir=REPO_ROOT / "tests" / "scenarios" / "fixtures" / "config",
    )


def _find_scenario_file(scenario_id: str) -> Path:
    matches = list(SCENARIOS_DIR.glob(f"{scenario_id}_*.yaml"))
    assert matches, f"no scenario file found for {scenario_id}"
    return matches[0]


@pytest.mark.llm
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — scenario tests need the real Claude API",
)
@pytest.mark.parametrize("scenario_id", LIVE_LLM_SCENARIOS)
async def test_scenario_against_real_claude(scenario_id):
    settings = _scenario_settings()
    engine = build_claude_engine(settings)
    scenario = load_scenario(_find_scenario_file(scenario_id))

    result = await run_scenario(scenario, engine=engine, settings=settings)

    print(format_transcript(result))
    assert result.passed, "\n".join(result.failures)


@pytest.mark.parametrize("scenario_id", NO_API_NEEDED_SCENARIOS)
async def test_scenario_that_never_calls_the_engine(scenario_id):
    """S14 ("stop") is intercepted by guard G-5 before any engine call,
    so this can run for real, every time, with no API key at all."""
    settings = _scenario_settings()
    engine = AlwaysEscalateEngine()  # would fail the test loudly if ever actually called
    scenario = load_scenario(_find_scenario_file(scenario_id))

    result = await run_scenario(scenario, engine=engine, settings=settings)

    print(format_transcript(result))
    assert result.passed, "\n".join(result.failures)

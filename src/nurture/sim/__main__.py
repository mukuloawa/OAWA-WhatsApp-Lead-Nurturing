"""Scenario simulator CLI: `python -m nurture.sim [path ...]`.

With no arguments, runs every `*.yaml` in `scenarios/`. Uses the real
ClaudeEngine (needs ANTHROPIC_API_KEY) unless --stub is passed, in which
case it uses AlwaysEscalateEngine — useful for a dry run of the harness
itself without spending any API budget.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from nurture.engine.claude_client import build_claude_engine
from nurture.settings import REPO_ROOT, get_settings
from nurture.sim.runner import format_transcript, load_scenario, run_scenario
from nurture.worker.engine_interface import AlwaysEscalateEngine


async def main() -> int:
    args = sys.argv[1:]
    use_stub = "--stub" in args
    paths = [Path(a) for a in args if a != "--stub"]

    if not paths:
        paths = sorted((REPO_ROOT / "scenarios").glob("*.yaml"))

    if not paths:
        print("No scenario files found.", file=sys.stderr)
        return 2

    settings = get_settings()
    engine = AlwaysEscalateEngine() if use_stub else build_claude_engine(settings)

    all_passed = True
    for path in paths:
        scenario = load_scenario(path)
        result = await run_scenario(scenario, engine=engine, settings=settings)
        print(format_transcript(result))
        print()
        all_passed = all_passed and result.passed

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

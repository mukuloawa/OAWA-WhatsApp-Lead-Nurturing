"""Scenario simulator (DESIGN.md Section 17 Phase 4, Appendix E).

- runner.py: run_scenario() — plays a scenario's lead_turns through the
  real pipeline (worker.pipeline.process) against FakeGHLClient.
- assertions.py: the Appendix E assertion vocabulary.
- __main__.py: `python -m nurture.sim [path ...]` CLI entry point.
"""

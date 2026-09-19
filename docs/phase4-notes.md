# Phase 4 — Conversation Engine: Design Notes and Limitations

| | |
|---|---|
| **Date** | 19 September 2026 |
| **Scope** | DESIGN.md Section 17, Phase 4: prompt rendering, the real Claude call with forced tool use, output validation (V1-V7), regeneration, link injection, the state machine (transition legality), extraction merge, audit rows, the simulator CLI, and the Appendix E scenarios. |
| **Live account impact** | None. No WhatsApp messages sent, no live contacts/tags/fields/workflows touched. |
| **Real Claude API calls made while building this** | **None.** This environment has no `ANTHROPIC_API_KEY` — see §1 below, which is the most important thing in this document. |

## 1. The real API access gap (read this first)

DESIGN.md's Phase 4 acceptance criteria are:

> unit tests green; all scenarios in Appendix E pass their deterministic assertions on 3 consecutive runs; the human has read the full transcripts of scenarios S1-S3 and approved the tone.

The first part is met: **all unit and integration tests pass (185/185)**, using a fully mocked Anthropic client (`tests/unit/test_claude_engine.py`) and a scripted multi-turn engine that exercises the entire simulator end to end (`tests/integration/test_simulator.py`) — so the *mechanics* (prompt rendering, validation, regeneration, retries, link injection, state machine, the simulator itself) are genuinely proven, not just written.

The second and third parts — **running S1-S13 against the real Claude API three times, and you reading real transcripts of S1-S3 to approve tone** — could not be completed, because this environment has no Anthropic API key. This is not a corner cut; it's a hard access limitation, surfaced here explicitly rather than glossed over.

What *was* possible without a key, and was actually run for real: **S14 ("stop")**, because guard G-5 intercepts before the engine is ever called — `pytest tests/scenarios/` runs it with no API key needed, and it passes. This at least proves the simulator, the real pipeline, and the guard system work correctly together end to end.

**What this means for you:** to close out Phase 4's acceptance criteria properly, either:
- give me an `ANTHROPIC_API_KEY` (e.g. as a session env var) and I'll run `pytest -m llm tests/scenarios/` and report the real transcripts, or
- run it yourself locally: `ANTHROPIC_API_KEY=... python -m nurture.sim` (runs every scenario) or target specific ones with `python -m nurture.sim scenarios/S1_lead_gen_cooperative.yaml`.

Either way, please actually read the S1-S3 transcripts and confirm the tone before this phase is considered fully done — that step is explicitly a human judgement call in DESIGN.md, not something I can substitute for.

## 2. Link injection is inside `ClaudeEngine`, not the pipeline

DESIGN.md Section 4 scopes all of Section 9 (prompt assembly, validation, regeneration, link injection) to `engine/` — i.e. to the `ConversationEngine` implementation itself, not the pipeline that calls it. `ClaudeEngine.decide()` therefore validates, regenerates, and injects the real webinar link before ever returning an `EngineDecision`; `worker/pipeline.py` just uses whatever `reply` it gets back.

**Consequence:** any other `ConversationEngine` implementation (a test stub, a future alternative) that wants an invite reply to actually go out with the real link has to inject it itself — the pipeline will not do this for you. This tripped up a test while building this phase (a scripted stub engine emitted the literal `[[WEBINAR_LINK]]` token, which the pipeline duly sent verbatim, un-replaced) — the test was wrong, not the pipeline; fixed by having the stub supply the already-injected link, matching what `ClaudeEngine` actually returns.

## 3. `llm_unavailable` interpretation

DESIGN.md Section 9.5 says escalations send the fixed `ESCALATION_MESSAGE` and tag `wa-escalated`, "except `llm_unavailable` and `window_closed`". Section 7.3/12 separately say a Claude timeout/overload becomes "tag only, no message". Read together: `llm_unavailable` still tags `wa-escalated` and writes `wa_escalation_reason`, exactly like a normal escalation, but skips sending any message at all (not even the fixed escalation text) — implemented that way in `worker/pipeline.py`, tested in `tests/integration/test_pipeline.py::test_llm_unavailable_tags_but_sends_no_message`.

## 4. Auth errors vs. transient errors

DESIGN.md Section 7.3 says "one retry on timeout/overload". This implementation retries once specifically on `APITimeoutError`, `APIConnectionError`, and `InternalServerError` (transient/availability problems), but does **not** retry on `AuthenticationError` or other 4xx `APIStatusError`s — retrying an identical request with the same bad credentials can't succeed, so it escalates as `llm_unavailable` immediately instead of wasting a second call.

## 5. Appendix E assertion vocabulary beyond S1

DESIGN.md gives S1's YAML verbatim, including its `every_turn: [max_one_question, no_url, max_chars_900]` / `final_stage` / `extracted_includes` / `link_sent_exactly_once` / `max_diagnosis_turns` assertion keys. It does **not** give literal YAML for S2-S17 — only short natural-language "Key assertions" in Appendix E's summary table. The additional assertion types used for those scenarios (`no_devanagari`, `any_reply_contains`, `no_reply_contains`, `reaches_stage_within`, `min_reply_length_after_turn`, `no_link_in_final_reply`, `no_llm_call_made`, `exactly_n_replies`) were designed to mechanically check what that table describes in words. They're a reasonable-effort translation, not something DESIGN.md specifies exactly — worth a look if you want stricter or different checks.

## 6. S15-S17 are not run against the real API here

DESIGN.md's own table marks S15 "(stubbed Claude)", S16 and S17 "(pipeline test, stubbed Claude)" — these were never meant to hit the real API. Their actual verification lives in the pytest suite that already existed or was extended for them:
- **S15** (model outputs a URL, should regenerate then escalate): `tests/unit/test_claude_engine.py::test_both_attempts_invalid_escalates_with_validation_failed_reason` and `::test_invalid_first_reply_triggers_regeneration_then_succeeds`.
- **S16** (three rapid messages -> exactly one reply): `tests/integration/test_pipeline.py::test_superseded_event_is_marked_and_not_processed` and the scheduler debounce tests.
- **S17** (human takeover -> paused, no reply): `tests/integration/test_pipeline.py::test_g4_human_takeover_pauses`.

Their YAML files under `scenarios/` exist for Appendix E documentation completeness and say this explicitly in their own comments; running them through `python -m nurture.sim` doesn't exercise the actual behaviour DESIGN.md describes for them.

## 7. Code reorganisation: `engine/state.py`

DESIGN.md Section 4 assigns the stage<->tag mapping *and* transition-legality validation to `engine/state.py`. Phase 3 (before this module existed) put only the mapping in `worker/stage_tags.py`. Phase 4 moved that data into the new `engine/state.py` alongside the transition-legality logic it's now paired with, and updated every import (`worker/pipeline.py`, `guards/pre_llm.py`). `worker/stage_tags.py` no longer exists. A `current_stage_from_tags()` helper (previously duplicated privately in `worker/pipeline.py`) now lives there too, as the single shared implementation.

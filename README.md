# OAWA WhatsApp Lead Nurturing Service

Replaces the 30-45 minute discovery call before OAWA's Saturday "AUM
Strategic Diagnostic" session with an AI-driven WhatsApp conversation.
See [`DESIGN.md`](./DESIGN.md) for the full specification and
[`docs/phase0-findings.md`](./docs/phase0-findings.md) for what has been
verified against the real Synamate/GHL account so far.

**Status: Phase 4 (conversation engine) built, but not fully verified —
see `docs/phase4-notes.md`.** The real Claude-calling engine (prompt
rendering, forced tool use, output validation, regeneration, link
injection, the state machine, audit rows) is implemented and its
mechanics are fully unit/integration tested with a mocked Anthropic
client. **This environment has no `ANTHROPIC_API_KEY`**, so the
Appendix E scenarios have not been run against the real API, and their
transcripts have not been human-reviewed — both are explicit DESIGN.md
Phase 4 acceptance criteria that are still outstanding. Nothing has been
deployed, and no WhatsApp message has ever been sent to a real lead.

## Requirements

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/) (recommended) or plain `pip`

## Local setup

```bash
cp .env.example .env
# edit .env — at minimum set dummy values for the required variables
# so the app will start; see DESIGN.md Section 11 for what each does.

uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# apply database migrations (SQLite by default per .env.example)
alembic upgrade head

# run the app
uvicorn nurture.main:app --reload
```

Then check:

```bash
curl localhost:8000/health   # {"status": "ok"}
curl localhost:8000/ready    # {"status": "ok", "checks": {...}}
```

With `SEND_MODE=dry_run` (the default), you can safely POST to the
webhook endpoint and nothing will be written to GHL — only local Postgres/
SQLite audit rows:

```bash
curl -X POST localhost:8000/webhook/wa-reply \
  -H "Content-Type: application/json" \
  -H "X-OAWA-Secret: $WEBHOOK_SECRET" \
  -d '{"contact_id": "some-real-or-fake-contact-id", "location_id": "'"$GHL_LOCATION_ID"'"}'
```

This will still call `RealGHLClient.get_contact`/`get_thread` (real,
read-only calls) and, once past all guards, the real Claude API, once
the debounce delay elapses — neither is faked out for manual `curl`
testing, only GHL/Claude *writes* are suppressed by `dry_run`. Use a
`FakeGHLClient`-backed test (see `tests/integration/`) or a contact
you're sure is safe to read if you try this against a real account.

The app **refuses to start** if any required environment variable
(`ANTHROPIC_API_KEY`, `GHL_TOKEN`, `WEBHOOK_SECRET`, etc. — see
`DESIGN.md` Section 11) is missing, and refuses to start in
`SEND_MODE=shadow`/`live` while `config/agenda.yaml` still has the
`FILL IN` placeholder (DESIGN.md Section 11).

`SEND_MODE` defaults to `dry_run`. Don't flip it without asking — even
though the real engine now exists, its live-API behaviour (S1-S13) is
still unverified in this environment (see status note above and
`docs/phase4-notes.md`).

## Running tests

```bash
pytest
```

185 tests: unit tests (`tests/unit/`) plus pipeline/guard/endpoint/
simulator integration tests (`tests/integration/`, using `FakeGHLClient`,
SQLite, and — for the Claude engine specifically — a mocked Anthropic
client, never the real API). Scenario tests that call the real Claude
API (`tests/scenarios/`) are marked `llm`, live outside `testpaths`, and
are never collected by plain `pytest` — see `docs/phase4-notes.md` §1
for how to actually run them.

## Repository layout

See `DESIGN.md` Section 15 for the intended final layout. As of Phase 4:

- `src/nurture/settings.py` — typed, validated app configuration.
- `src/nurture/main.py` — FastAPI app factory; wires up all four endpoints,
  the GHL adapter, the real conversation engine, and the scheduler.
- `src/nurture/api/health.py`, `webhook.py`, `admin.py` — the four HTTP endpoints.
- `src/nurture/store/` — SQLAlchemy models (`inbound_events`, `turns`),
  the async DB engine/session helpers, and `repository.py` (DB queries).
- `src/nurture/ghl/` — the `GHLClient` protocol (`client.py`), domain
  types (`models.py`), the 12 tracked custom field keys (`fields.py`),
  `RealGHLClient` (`real.py`), and `FakeGHLClient` (`fake.py`). This is
  the only module allowed to make GHL HTTP calls.
- `src/nurture/guards/pre_llm.py` — guards G-1 through G-7, G-10.
- `src/nurture/engine/` — `prompt.py` (rendering), `validation.py`
  (V1-V7 + link injection), `state.py` (stage<->tag data + transition
  legality), `claude_client.py` (`ClaudeEngine`, the real engine, with
  regeneration and retry).
- `src/nurture/worker/` — `pipeline.py` (the process() pipeline),
  `scheduler.py` (debounce + startup recovery), `locks.py` (per-contact
  locking), `actions.py` (send-mode behaviour), `extracted_fields.py`
  (Appendix B <-> GHL key mapping), `engine_interface.py` (the pipeline
  <-> engine seam, plus the safe `AlwaysEscalateEngine` fallback).
- `src/nurture/sim/` — `runner.py` (plays a scenario through the real
  pipeline against `FakeGHLClient`), `assertions.py` (the Appendix E
  assertion vocabulary), `__main__.py` (`python -m nurture.sim` CLI).
- `scenarios/*.yaml` — the 17 Appendix E scenarios (S1-S17).
- `alembic/` — database migrations.
- `config/` — `agenda.yaml` (still has the `FILL IN` placeholder — OAWA
  needs to supply the real session agenda before shadow/live mode),
  `optout.yaml`, `banned_phrases.yaml`.
- `prompts/` — the system prompt and tool schema from DESIGN.md
  Appendices A and B, stored verbatim as files per DESIGN.md Section 0.
- `docs/phase0-findings.md` — Phase 0 verification results.
- `docs/phase3-notes.md`, `docs/phase4-notes.md` — every interpretation/
  judgement call made while building the pipeline, guards, and engine,
  and why — including the real API access gap.
- `tests/fixtures/ghl/` — response fixtures used to test `RealGHLClient`'s
  parsing; each has a `_fixture_note` saying whether it's a real
  (anonymised) capture or hand-built from a verified schema — see
  `tests/fixtures/ghl/README.md`.

## What this service does **not** do yet

- Has never had a real conversation with a real lead — the engine's
  mechanics are proven with a mocked Anthropic client, but no scenario
  has been run against the real Claude API (no `ANTHROPIC_API_KEY` in
  this environment — see `docs/phase4-notes.md` §1).
- `RealGHLClient`'s write operations (send WhatsApp, notes, tags, custom
  field updates) have real, tested code paths, but have still never been
  executed against the real Synamate account — only read operations
  have (see `docs/phase0-findings.md`).
- Is not deployed anywhere.

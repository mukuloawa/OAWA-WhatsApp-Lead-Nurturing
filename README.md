# OAWA WhatsApp Lead Nurturing Service

Replaces the 30-45 minute discovery call before OAWA's Saturday "AUM
Strategic Diagnostic" session with an AI-driven WhatsApp conversation.
See [`DESIGN.md`](./DESIGN.md) for the full specification and
[`docs/phase0-findings.md`](./docs/phase0-findings.md) for what has been
verified against the real Synamate/GHL account so far.

**Status: Phase 3 (pipeline and guards, stubbed LLM) complete.** The
webhook, debounce worker, startup recovery, all pre-LLM guards (G-1
through G-7, G-10), and all three send modes are implemented and wired
up end to end. There is still no real conversation engine (Phase 4) —
the app runs with a safe placeholder that always escalates to a human
rather than guessing a reply. Nothing has been deployed, and no
WhatsApp message has ever been sent to a real lead. See
`docs/phase0-findings.md` and `docs/phase3-notes.md` for what's been
verified vs. interpreted.

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
read-only calls) once the debounce delay elapses, since Phase 3 doesn't
fake out the adapter for manual `curl` testing — only `dry_run`'s *write*
suppression is automatic. Use a `FakeGHLClient`-backed test (see
`tests/integration/`) or a contact you're sure is safe to read if you
try this against a real account.

The app **refuses to start** if any required environment variable
(`ANTHROPIC_API_KEY`, `GHL_TOKEN`, `WEBHOOK_SECRET`, etc. — see
`DESIGN.md` Section 11) is missing. This is intentional (DESIGN.md
Section 11 / Section 17 Phase 1 acceptance criteria).

`SEND_MODE` defaults to `dry_run`. It must stay that way until Phase 4
(the real conversation engine) exists and has been explicitly approved —
right now the app only ever escalates (via `AlwaysEscalateEngine`), so
even `shadow`/`live` mode would just draft/send the fixed escalation
message, never a guessed reply. Still, don't flip it without asking.

## Running tests

```bash
pytest
```

111 tests: unit tests (`tests/unit/`) plus pipeline/guard/endpoint
integration tests (`tests/integration/`, using `FakeGHLClient` and
SQLite). Scenario tests that call the real Claude API are marked `llm`
and excluded by default; they don't exist yet (Phase 4).

## Repository layout

See `DESIGN.md` Section 15 for the intended final layout. As of Phase 3:

- `src/nurture/settings.py` — typed, validated app configuration.
- `src/nurture/main.py` — FastAPI app factory; wires up all four endpoints,
  the GHL adapter, the (stubbed) engine, and the scheduler.
- `src/nurture/api/health.py`, `webhook.py`, `admin.py` — the four HTTP endpoints.
- `src/nurture/store/` — SQLAlchemy models (`inbound_events`, `turns`),
  the async DB engine/session helpers, and `repository.py` (DB queries).
- `src/nurture/ghl/` — the `GHLClient` protocol (`client.py`), domain
  types (`models.py`), the 12 tracked custom field keys (`fields.py`),
  `RealGHLClient` (`real.py`), and `FakeGHLClient` (`fake.py`). This is
  the only module allowed to make GHL HTTP calls.
- `src/nurture/guards/pre_llm.py` — guards G-1 through G-7, G-10.
- `src/nurture/worker/` — `pipeline.py` (the process() pipeline),
  `scheduler.py` (debounce + startup recovery), `locks.py` (per-contact
  locking), `actions.py` (send-mode behaviour), `stage_tags.py` and
  `extracted_fields.py` (data tables), `engine_interface.py` (the seam to
  Phase 4, plus the safe `AlwaysEscalateEngine` default).
- `src/nurture/engine/`, `sim/` — placeholder packages for Phase 4; each
  `__init__.py` says what phase fills it in.
- `alembic/` — database migrations.
- `config/` — `agenda.yaml` (still has the `FILL IN` placeholder — OAWA
  needs to supply the real session agenda before shadow/live mode),
  `optout.yaml`, `banned_phrases.yaml`.
- `prompts/` — the system prompt and tool schema from DESIGN.md
  Appendices A and B, stored verbatim as files per DESIGN.md Section 0.
- `docs/phase0-findings.md` — Phase 0 verification results.
- `docs/phase3-notes.md` — every interpretation/judgement call made
  while building the pipeline and guards, and why.
- `tests/fixtures/ghl/` — response fixtures used to test `RealGHLClient`'s
  parsing; each has a `_fixture_note` saying whether it's a real
  (anonymised) capture or hand-built from a verified schema — see
  `tests/fixtures/ghl/README.md`.

## What this service does **not** do yet

- Has no real conversation engine — runs on `AlwaysEscalateEngine`, a
  safe placeholder that hands every conversation to a human (Phase 4).
- Post-LLM output validation and stage-transition legality (guards G-8,
  G-9) are not implemented — they depend on the real engine.
- Does not call the Anthropic API.
- `RealGHLClient`'s write operations (send WhatsApp, notes, tags, custom
  field updates) have real, tested code paths now, but have still never
  been executed against the real Synamate account — only read operations
  have (see `docs/phase0-findings.md`).
- Is not deployed anywhere.

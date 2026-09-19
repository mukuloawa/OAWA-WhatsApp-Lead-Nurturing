# OAWA WhatsApp Lead Nurturing Service

Replaces the 30-45 minute discovery call before OAWA's Saturday "AUM
Strategic Diagnostic" session with an AI-driven WhatsApp conversation.
See [`DESIGN.md`](./DESIGN.md) for the full specification and
[`docs/phase0-findings.md`](./docs/phase0-findings.md) for what has been
verified against the real Synamate/GHL account so far.

**Status: Phase 1 (project skeleton) only.** No GHL adapter, no webhook,
no conversation engine, and nothing deployed yet. The app currently only
exposes `/health` and `/ready`; it does not talk to WhatsApp, Synamate,
or Claude.

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

The app **refuses to start** if any required environment variable
(`ANTHROPIC_API_KEY`, `GHL_TOKEN`, `WEBHOOK_SECRET`, etc. — see
`DESIGN.md` Section 11) is missing. This is intentional (DESIGN.md
Section 11 / Section 17 Phase 1 acceptance criteria).

`SEND_MODE` defaults to `dry_run`. It must stay that way until the
phases in `DESIGN.md` Section 17 that actually build sending behaviour
(Phase 3 onward) exist, are tested, and have been explicitly approved.

## Running tests

```bash
pytest
```

This runs the unit tests only (`tests/unit/`, `tests/integration/`).
Scenario tests that call the real Claude API are marked `llm` and
excluded by default; they don't exist yet (Phase 4).

## Repository layout

See `DESIGN.md` Section 15 for the intended final layout. As of Phase 1:

- `src/nurture/settings.py` — typed, validated app configuration.
- `src/nurture/main.py` — FastAPI app factory; wires up `/health` and `/ready`.
- `src/nurture/api/health.py` — the two Phase 1 endpoints.
- `src/nurture/store/` — SQLAlchemy models (`inbound_events`, `turns`) and
  the async DB engine/session helpers.
- `src/nurture/ghl/`, `engine/`, `guards/`, `worker/`, `sim/` — placeholder
  packages for Phases 2-4; each `__init__.py` says what phase fills it in.
- `alembic/` — database migrations.
- `config/` — `agenda.yaml` (still has the `FILL IN` placeholder — OAWA
  needs to supply the real session agenda before shadow/live mode),
  `optout.yaml`, `banned_phrases.yaml`.
- `prompts/` — the system prompt and tool schema from DESIGN.md
  Appendices A and B, stored verbatim as files per DESIGN.md Section 0.
- `docs/phase0-findings.md` — Phase 0 verification results.

## What this service does **not** do yet

- Does not call the Synamate/GHL API (no `GHL_TOKEN` calls are made
  anywhere in the code yet).
- Does not call the Anthropic API.
- Does not send WhatsApp messages, create/modify GHL tags, custom
  fields, contacts, notes, or workflows.
- Is not deployed anywhere.

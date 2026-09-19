# Phase 3 — Pipeline & Guards: Design Notes and Interpretations

| | |
|---|---|
| **Date** | 19 September 2026 |
| **Scope** | DESIGN.md Section 17, Phase 3: webhook, event store, debounce worker, startup recovery, pre-LLM guards (G-1 to G-7, G-10), all three send modes, human-takeover detection. Explicitly excludes Phase 4 (conversation engine, output validation G-8/G-9, state-machine transition legality). |
| **Live account impact** | None. No WhatsApp messages sent, no contacts/tags/custom fields modified, no workflows touched. All pipeline testing uses `FakeGHLClient` and SQLite. |

DESIGN.md's Section 8/9/10 describe the pipeline in enough detail to build it, but a few specific points either aren't fully pinned down or turned out to depend on information not available from GHL (per Phase 0/2's findings). This document records every such judgement call made while building Phase 3, so they're visible for review rather than buried in code comments.

## 1. `turns.sent_message_id` (schema addition)

DESIGN.md Section 7.2's `Message` model has a field comment: `sent_by_service: bool # True if id is in turns.sent message ids`. But Section 6.2's `turns` table DDL has no column that stores the GHL message id the service actually sent — only `inbound_message_id` (the *triggering* inbound message), not an outbound one. This is a genuine contradiction between two parts of DESIGN.md itself.

**Resolution:** added a new nullable `sent_message_id TEXT` column to `turns` (new Alembic migration), populated with the id `send_whatsapp()` returns whenever a turn actually sends. This is what makes human-takeover detection (G-4, below) implementable at all.

## 2. G-4: human takeover detection

DESIGN.md: *"if there is any outbound message after the last outbound the service sent, and it isn't a known template, a human has replied."*

No field anywhere in the verified GHL API surface (Phase 0/2) marks a message as "a known template" vs. human-sent. Rather than guess at one, this implementation:

- Looks up the id of the last message *this service* sent for the contact (via the new `turns.sent_message_id` column).
- Compares it to the thread's actual last outbound message id.
- If they differ, a human has taken over → pause.
- **Before the service's first-ever turn for a contact** (no `turns` row yet), the check is skipped entirely — so the opener/nudge templates (sent by GHL workflows, not this service) are never mistaken for a takeover, without needing to classify message provenance at all.

## 3. G-7: non-text latest message

DESIGN.md's `Message` model (Section 7.2, deliberately left unchanged from the spec) carries no content-type or attachment field — only `text`. Phase 2's real captured fixtures show attachment-only messages (voice notes, images) have an empty `body`. This implementation treats an **empty-text latest inbound message** as non-text and escalates.

Worst case of this approximation: a literally blank inbound text message gets escalated to a human unnecessarily. That's a safe failure direction (a human sees it, not the bot guessing), not a silent wrong answer.

## 4. Extracted-field name mapping

DESIGN.md Appendix B's `respond` tool schema uses bare field names (`aum`, `years_in_business`, `problem_category`, ...). DESIGN.md Section 6.1's GHL custom fields use `wa_`-prefixed keys (`wa_aum`, `wa_years_in_business`, ...). Nothing in DESIGN.md states the translation explicitly, but the correspondence is unambiguous (there's exactly one custom field per extracted field, differing only by the `wa_` prefix), so a mapping table (`worker/extracted_fields.py`) was added to translate one to the other before writing to GHL.

**Known gap:** the tool schema's `city` field is excluded from this mapping. `city` is a native GHL contact field (Section 9.1: "ask for city only if it is missing"), not one of the 12 `wa_*` custom fields, and `GHLClient.update_custom_fields` only ever touches custom fields. Writing an extracted city back onto the contact's native field is **not implemented** in Phase 3 — if the engine (Phase 4) extracts a city correction, it is currently silently dropped rather than written anywhere. This should be addressed either in Phase 4 or with a small adapter addition.

## 5. `dry_run` suppresses *all* GHL writes, including guard-triggered tag changes

Some guards (G-3 window-closed, G-4 human-takeover) add a tag (`wa-manual-review`, `wa-paused`) even though their primary action is "skip." DESIGN.md defines `dry_run` globally as *"no GHL writes; log only."* This implementation takes that literally — in `dry_run` mode, **no** tag is added for these guards either, not just no message sent. This was a judgement call: one could argue safety-flag tags should apply regardless of send mode, but the more consistent (and more conservative, for proving out the system against real leads with zero side effects) reading of "no GHL writes" is that it means *no* writes, full stop.

## 6. Stage↔tag mapping vs. transition validation

`worker/stage_tags.py` holds only the static `STAGE_TAGS` lookup table (pure data, directly from DESIGN.md Section 5's table) — needed so the pipeline knows which tag to add/remove for a given stage. It does **not** implement Section 5.1's transition legality rules (illegal-transition rejection, the `MAX_DIAGNOSIS_TURNS` regeneration trigger). DESIGN.md Section 4 assigns that to `engine/state.py`, explicitly a Phase 4 deliverable, and it is not built here.

## 7. Section 16 vs. Section 17 scope tension ("regeneration")

DESIGN.md Section 16's testing-strategy table lists "regeneration" as something the Phase-3-style pipeline-integration tests should cover. But Section 17's own phase breakdown lists regeneration under Phase 4's deliverables (it depends on the output-validation guards G-8/G-9, which are explicitly Phase 4). This build followed Section 17's phase split and this task's explicit Phase 3 instructions (guards G-1 to G-7 and G-10, three send modes, webhook/debounce/recovery/human-takeover) — regeneration is not implemented, and is left for Phase 4.

## 8. `AlwaysEscalateEngine`: the safe default until Phase 4

`main.py` wires a real `RealGHLClient` (constructed from settings) but no real conversation engine exists yet. Rather than leave that dependency unset, it defaults to `AlwaysEscalateEngine` — a stub that always returns `escalate=True`. This means the full pipeline is genuinely exercisable end-to-end today, and if this were ever deployed before Phase 4 exists (it won't be — nothing has been deployed), the worst case is every conversation gets handed to a human, never a guessed reply.

## 9. `turns` row persistence policy

A `turns` audit row is written whenever the pipeline determined the triggering inbound message (i.e. got at least as far as G-2's duplicate check). Pure early skips — G-10 (kill switch) and G-1 (paused/optout/manual-review/terminal) — never reach that point and only get an `inbound_events.status_reason`, not a `turns` row, since there is nothing yet to audit (no inbound message was even identified).

## 10. Infrastructure fix: SQLite autoincrement

Found while writing these tests, not specific to guard/pipeline logic: `BigInteger` primary keys silently fail to auto-populate on SQLite inserts (SQLite only aliases `ROWID` auto-increment for a column declared as plain `INTEGER PRIMARY KEY`). Fixed via `BigInteger().with_variant(Integer, "sqlite")` on both `id` columns, in both the models and the existing initial migration (edited in place, since this branch has not been deployed). Postgres is unaffected — it still gets a real `BIGINT`/`BIGSERIAL`-equivalent column. Verified against both SQLite and a live local Postgres instance.

## 11. `/ready` still doesn't check the GHL field-ID map

Phase 1 left this unimplemented pending Phase 2's GHL adapter; Phase 2's adapter now exists, but wiring a real field-ID resolution call into `/ready` would mean **every** readiness check makes a live (read-only) call to the real Synamate account. Given this phase's "don't touch live Synamate unnecessarily" constraint, this was deliberately left as-is rather than added opportunistically. Worth revisiting once the app is actually being deployed (Phase 5).

# GHL API fixtures

Used by `tests/unit/test_ghl_real_client.py` to test `RealGHLClient`'s
parsing against real response shapes, without calling the live API in
tests. Each file has a `_fixture_note` explaining its provenance:

| File | Provenance |
|---|---|
| `get_contact.json` | Real response, PII anonymised |
| `get_custom_fields.json` | Real subset, unmodified (no PII in field definitions) |
| `get_custom_fields_with_wa_fields.json` | Real subset + synthetic wa_* fields appended |
| `get_contact_with_wa_fields.json` | Synthetic (same shape as `get_contact.json`) |
| `list_messages.json` | Real response, PII anonymised |
| `list_messages_whatsapp_synthetic.json` | Synthetic (no live WhatsApp threads exist yet) |
| `send_whatsapp_response.json` | Synthetic, from verified schema (write op, never called live) |
| `create_note_response.json` | Synthetic, from verified schema (write op, never called live) |
| `add_tags_response.json` | Synthetic, from verified schema (write op, never called live) |
| `remove_tags_response.json` | Synthetic, from verified schema (write op, never called live) |
| `update_contact_response.json` | Synthetic, from verified schema (write op, never called live) |

"Real" fixtures were captured via read-only calls against the real OAWA
Synamate account (see `docs/phase0-findings.md`). "Synthetic" fixtures
were hand-built to match a schema that was verified (via `describe_operation`,
never executed) but not captured live, because either no live example
exists yet (no WhatsApp threads) or the operation is a write DESIGN.md's
Phase 2 explicitly forbids calling against real data.

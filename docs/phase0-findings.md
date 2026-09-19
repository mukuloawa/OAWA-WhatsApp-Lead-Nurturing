# Phase 0 — GHL/Synamate Verification Findings

| | |
|---|---|
| **Date** | 19 September 2026 |
| **Scope** | Read-only verification only, per DESIGN.md Section 17 ("Phase 0: GHL verification spike") |
| **Method** | Live, read-only calls against the real OAWA Synamate/GHL location, made through an already-authorized GHL connection available in this session (not the eventual service's own `GHL_TOKEN`) |
| **Location checked** | `FlT9bndDcWIrmuveZWZa` — "OAWA", Mumbai (active paid GHL subscription) |
| **Writes performed** | **None.** No messages sent, no tags/fields/workflows created or changed, no contact data modified. |

This document is the Phase 0 deliverable referenced in DESIGN.md Section 17. It does not replace DESIGN.md; it records what Phase 0 found. Where a finding changes a DESIGN.md assumption, DESIGN.md itself should be updated in a follow-up pass, once the human has reviewed this document — that follow-up has not been done yet.

---

## 1. What was verified

Confirmed by live read-only calls against the real account:

| DESIGN.md item | Result |
|---|---|
| GHL API v2 reachable, account is real and active | Confirmed. Active paid subscription (Stripe `subscriptionStatus: active`), 25,465 contacts, 412 custom fields, 362 tags already in use. Not a test/empty account. |
| §7.2 "Get contact" | Confirmed working (via contact search; a direct `GET /contacts/{contactId}` was not separately called but is the same underlying resource). |
| §7.2 "Find conversation" — `GET /conversations/search?locationId=&contactId=` | Confirmed. Operation `search-conversation`, path `/conversations/search`, query params include `contactId`, `lastMessageType`, `lastMessageAction`, `status`. Response includes `conversations[]` and `total`. |
| §7.2 "List custom fields" — `GET /locations/{locationId}/customFields` | Confirmed. Response shape: `{ customFields: [...] }`. See §2 below for the field-addressing finding. |
| §6.1 "How custom fields are addressed" **[VERIFY]** | **Resolved.** Each custom field has both an opaque `id` (e.g. `23BgESqc7DqLFQ2vS0Vi`) and a namespaced `fieldKey` (e.g. `"contact.aum_in_crores"`) — not a bare key as DESIGN.md's example implied. A contact record's own `customFields` array stores values keyed by `id` only (not `fieldKey`), confirming the design's plan to resolve key→id once at startup (§6.1, §7.2 `resolve_custom_field_ids`) is the right approach. |
| §5 human-takeover detection signal | **Resolved — mechanism found.** Each conversation exposes `lastOutboundMessageAction: "automated" \| "manual"`. This is the field the service can use to distinguish a workflow/template-sent message from a message a human typed directly in GHL (DESIGN.md Q3, partially). |
| §7.2 "Send WhatsApp" request shape | Schema confirmed only (via `describe_operation`, not called): `POST /conversations/messages`, body `{ type: "WhatsApp", contactId, message, ... }`. Matches DESIGN.md's expectation. |
| §7.2 "Add tags" / "Update custom fields" / "Add note" | Operation schemas confirmed to exist with expected shapes (`POST /contacts/{contactId}/tags`, `PUT /contacts/{contactId}`, `POST /contacts/{contactId}/notes`). Not called (all are writes). |
| Naming collisions for the 12 new custom fields (§6.1) | **None.** Checked all 412 existing fields — none of `wa_aum`, `wa_years_in_business`, `wa_problem_category`, `wa_problem_in_their_words`, `wa_problem_duration`, `wa_tried_so_far`, `wa_key_metric`, `wa_ceiling_view`, `wa_bot_turns`, `wa_diagnosis_turns`, `wa_last_processed_msg_id`, `wa_escalation_reason` exist yet. One unrelated field already uses a `wa_` prefix (`contact.wa_group_joined`, "WA Group Joined") — different purpose, not a conflict. |
| Naming collisions for the 12 new tags (§5) | **None.** Checked all 362 existing tags — none of `wa-stage-1..4`, `wa-invited`, `wa-confirmed`, `wa-declined`, `wa-escalated`, `wa-paused`, `wa-optout`, `wa-followup-sent`, `wa-manual-review` exist yet. Two unrelated tags contain the substring "wa-" (`05-09-2026-wa-asd-registration`, `12-09-2026-wa-asd-registration`) — event-registration tags, not a conflict. |

---

## 2. What was not verified

Could not be confirmed through read-only API calls in this pass:

- **`GHL_BASE_URL` / `GHL_API_VERSION` literal values** (§11: `https://services.leadconnectorhq.com`, `2021-07-28`). Calls in this pass went through an already-configured connection that handles these internally, so the literal header values the standalone service will send were not independently observed. Still marked **[VERIFY]** for Phase 2.
- **GHL webhook retry behaviour** (§12, Q2). Not observable without configuring a real webhook and inspecting delivery/retry logs.
- **Whether the "Custom Webhook" workflow action is available on this GHL plan** (Appendix D, Workflow B). This is a workflow-builder UI feature, not visible through the API surface checked here.
- **Exact "Customer Replied" webhook trigger payload** (§Q2). Requires building the workflow in the Synamate UI and firing a real event.
- **Whether a self-generated GHL Private Integration Token** (the credential the standalone service will actually use, via `GHL_TOKEN`) **has the same scopes/access** as the connection used for this check. This check used a connection already authorized for this session — it proves the *account and API* work, not that the *specific token the service will use* will have equivalent access.

---

## 3. What differs from DESIGN.md's original assumptions

- **WhatsApp does not appear to be active yet.** A search for any conversation of type WhatsApp in this account returned zero results. DESIGN.md's assumptions (end of §19) state "the WhatsApp number is already connected in Synamate" — this was **not confirmed**, and the evidence (no WhatsApp threads at all, ever) suggests it may not be connected yet, or has never been used. **Needs manual confirmation in the Synamate UI**, not just an API check (see §4).
- **Lead source differs from "Meta Lead Ad" native form.** DESIGN.md's Workflow A (Appendix D) assumes a trigger of "contact created from the Meta lead form." The one real, recent lead sampled during this check was actually created via a **website registration page** (`oawa-education.in/session-registration`), reached through an Instagram ad — i.e. a landing-page form submission, not Meta's native on-platform lead form. The existing tag on that contact is `"26-09-2026 webinar registration"`, not anything resembling a `wa-stage-*` tag.
- **Custom fields with similar intent already exist.** The account already has fields that appear to capture some of the same information the new WhatsApp bot is meant to extract via conversation — e.g. `contact.aum_in_crores`, a field resembling "I think I've hit a ceiling with the kind of clients I can attract," and one resembling "what I've tried so far that didn't work." These look like they come from an existing manual/form-based diagnostic process. DESIGN.md's 12 new `wa_*` fields do not conflict with these (different keys), but this raises a design question — see §5.
- **No `wa-*` automation exists yet anywhere in the account** (0 of 362 tags match). This confirms Workflows A/B/C/D (Appendix D) and the two WhatsApp templates (Appendix C) genuinely have not been built yet — expected for a Phase 5 task, but worth stating plainly since DESIGN.md is written as if some of this groundwork might already exist.

---

## 4. What still requires manual confirmation (not API-checkable)

1. **Confirm WhatsApp Business is actually connected to this Synamate location** (Settings → Integrations/Conversations in the GHL UI). This is the most important open item before Phase 5.
2. **Confirm the Synamate plan tier supports:** Private Integration tokens, the specific API scopes listed in §7.2/§11, and the "Custom Webhook" workflow action.
3. **Generate a real GHL Private Integration Token** and confirm it has the scopes the service needs (`contacts.readonly`, `contacts.write`, `conversations.readonly`, `conversations/message.readonly`, `conversations/message.write`, `locations/customFields.readonly`, `locations/tags.readonly`, etc.) — this is a separate credential from the one used for this check.
4. **Decide the actual trigger for Workflow A** given the lead source finding above (website form vs. native Meta Lead Ad) — likely a short conversation with whoever built the `oawa-education.in` registration page.
5. Confirm GHL's webhook retry behaviour with GHL/Synamate support or documentation, since it could not be observed passively.

---

## 5. Decisions needed later (not blockers, but flagged for the human)

- **Field naming/alignment:** create the 12 new `wa_*` fields fresh and separate from the existing similar-looking fields (as DESIGN.md currently specifies — no technical conflict either way), or intentionally reuse/align with the existing fields (e.g. `contact.aum_in_crores`) for cleaner reporting. Either works; this is a judgement call for OAWA, not a technical requirement.
- **Workflow A's trigger condition**, once the actual lead-intake mechanism (website form vs. native Meta form) is confirmed with the team.
- Whether the existing manual diagnostic-style custom fields indicate an overlapping process that should be reconciled with the new automated flow (e.g. should the bot skip questions if these fields are already filled from a prior form?). Not addressed by DESIGN.md today — worth a decision before Phase 4.

---

## 6. Verified operation reference table (for Phase 2)

| Operation | Verified `operationId` | Method & path | Scope required | Called in this pass? |
|---|---|---|---|---|
| Get contact / search contacts | `search-contacts-advanced` (also `get-contact`) | `POST /contacts/search` (`GET /contacts/{contactId}`) | `contacts.readonly` | Yes (search) |
| Find conversation | `search-conversation` | `GET /conversations/search` | `conversations.readonly` | Yes |
| Get message by id | `get-message` | `GET /conversations/messages/{id}` | `conversations/message.readonly` | Schema only |
| Send WhatsApp message | `send-a-new-message` | `POST /conversations/messages` | `conversations/message.write` | Schema only — **not called** |
| Add note | `create-note` | `POST /contacts/{contactId}/notes` | `contacts.write` | Schema only — **not called** |
| Add/remove tags | `add-tags` / `contacts.create-association` | `POST /contacts/{contactId}/tags` / `POST /contacts/bulk/tags/update/{type}` | `contacts.write` | Schema only — **not called** |
| Update contact / custom fields | `update-contact` | `PUT /contacts/{contactId}` | `contacts.write` | Schema only — **not called** |
| List custom fields | `get-custom-fields` | `GET /locations/{locationId}/customFields` | `locations/customFields.readonly` | Yes |
| List tags | `get-location-tags` | `GET /locations/{locationId}/tags` | `locations/tags.readonly` | Yes |
| Get location details | `get-location` | `GET /locations/{locationId}` | `locations.readonly` | Yes |

---

*This document records Phase 0 findings only. No code, workflows, custom fields, tags, or CRM data were created or modified while gathering it.*

"""Maps the `respond` tool's extracted-field names (DESIGN.md Appendix B)
to this service's GHL custom field keys (DESIGN.md Section 6.1). Pure
data, not business logic — analogous to stage_tags.py.

`city` is deliberately excluded: it is a native GHL contact field
(Section 9.1: "Use city_from_registration; ask for city only if it is
missing"), not one of the 12 wa_* custom fields, so it does not belong
in a custom-fields update payload. Writing an extracted city back onto
the contact's native `city` field is not implemented — GHLClient's
`update_custom_fields` only ever touches custom fields (DESIGN.md
Section 7.2). This is a real, known gap, not an oversight — flagged
here and in the Phase 3 report rather than silently dropped.
"""

from __future__ import annotations

EXTRACTED_FIELD_TO_WA_KEY: dict[str, str] = {
    "aum": "wa_aum",
    "years_in_business": "wa_years_in_business",
    "problem_category": "wa_problem_category",
    "problem_in_their_words": "wa_problem_in_their_words",
    "problem_duration": "wa_problem_duration",
    "tried_so_far": "wa_tried_so_far",
    "key_metric": "wa_key_metric",
    "ceiling_view": "wa_ceiling_view",
}


def translate_extracted(extracted: dict[str, str]) -> dict[str, str]:
    return {
        EXTRACTED_FIELD_TO_WA_KEY[key]: value
        for key, value in extracted.items()
        if key in EXTRACTED_FIELD_TO_WA_KEY
    }

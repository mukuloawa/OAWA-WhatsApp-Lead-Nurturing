from __future__ import annotations

from nurture.ghl.fields import WA_CUSTOM_FIELD_KEYS, from_ghl_field_key, to_ghl_field_key


def test_to_ghl_field_key_adds_contact_prefix():
    assert to_ghl_field_key("wa_aum") == "contact.wa_aum"


def test_from_ghl_field_key_strips_prefix_for_known_keys():
    assert from_ghl_field_key("contact.wa_aum") == "wa_aum"


def test_from_ghl_field_key_returns_none_for_unrelated_field():
    # Real near-miss found in Phase 0: contact.wa_group_joined is NOT one
    # of our 12 tracked keys.
    assert from_ghl_field_key("contact.wa_group_joined") is None


def test_from_ghl_field_key_returns_none_without_contact_prefix():
    assert from_ghl_field_key("wa_aum") is None


def test_all_12_keys_round_trip():
    assert len(WA_CUSTOM_FIELD_KEYS) == 12
    for key in WA_CUSTOM_FIELD_KEYS:
        assert from_ghl_field_key(to_ghl_field_key(key)) == key

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nurture.settings import Settings


def test_settings_load_with_all_required_values(valid_settings_kwargs):
    settings = Settings(_env_file=None, **valid_settings_kwargs)
    assert settings.send_mode == "dry_run"  # default
    assert settings.max_diagnosis_turns == 3  # default
    assert settings.ghl_location_id == "FlT9bndDcWIrmuveZWZa"


@pytest.mark.parametrize(
    "missing_key",
    [
        "anthropic_api_key",
        "ghl_token",
        "ghl_location_id",
        "webhook_secret",
        "admin_secret",
        "database_url",
        "webinar_link",
        "session_when",
    ],
)
def test_settings_refuses_to_start_when_required_value_missing(valid_settings_kwargs, missing_key):
    kwargs = dict(valid_settings_kwargs)
    del kwargs[missing_key]
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


def test_webhook_secret_must_be_at_least_32_chars(valid_settings_kwargs):
    kwargs = dict(valid_settings_kwargs)
    kwargs["webhook_secret"] = "too-short"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)


def test_agenda_placeholder_is_detected_as_not_filled_in(test_settings):
    # config/agenda.yaml ships with the FILL IN placeholder until OAWA
    # supplies the real agenda (DESIGN.md Section 11, Q4).
    assert test_settings.agenda_is_filled_in() is False


def test_require_agenda_filled_in_is_a_noop_in_dry_run(test_settings):
    test_settings.send_mode = "dry_run"
    test_settings.require_agenda_filled_in()  # must not raise


def test_require_agenda_filled_in_blocks_shadow_and_live(test_settings):
    for mode in ("shadow", "live"):
        test_settings.send_mode = mode
        with pytest.raises(RuntimeError):
            test_settings.require_agenda_filled_in()

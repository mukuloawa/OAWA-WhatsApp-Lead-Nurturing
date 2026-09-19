"""ClaudeEngine tests. No real Anthropic API calls — the SDK client is
faked so retry, regeneration, validation, and link-injection logic can
all be verified deterministically."""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import pytest

from nurture.engine.claude_client import ClaudeEngine
from nurture.ghl.models import Contact, Message


def fake_usage(input_tokens=100, output_tokens=50, cache_read_input_tokens=0):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
    )


def tool_use_response(tool_input: dict, **usage_kwargs):
    block = SimpleNamespace(type="tool_use", name="respond", input=tool_input)
    return SimpleNamespace(content=[block], usage=fake_usage(**usage_kwargs))


def no_tool_response(**usage_kwargs):
    block = SimpleNamespace(type="text", text="I'm not sure")
    return SimpleNamespace(content=[block], usage=fake_usage(**usage_kwargs))


class FakeAnthropicClient:
    """Each item in `queue` is either a fake response object or an
    exception instance to raise. .messages.create() pops one per call."""

    def __init__(self, queue: list):
        self._queue = list(queue)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_engine(client, **overrides) -> ClaudeEngine:
    defaults = dict(
        client=client,
        model="claude-sonnet-5",
        system_prompt="You are OAWA's AI assistant.",
        prompt_version="abc123def456",
        respond_tool_schema={"name": "respond", "input_schema": {}},
        webinar_link="https://real-link.example/webinar",
        max_diagnosis_turns=3,
        banned_phrases=["guaranteed"],
        timeout=1.0,
    )
    defaults.update(overrides)
    return ClaudeEngine(**defaults)


def make_contact(**overrides) -> Contact:
    defaults = dict(id="c1", first_name="Rahul", city="Pune", tags={"wa-stage-1"}, fields={})
    defaults.update(overrides)
    return Contact(**defaults)


def make_thread() -> list[Message]:
    from datetime import datetime, timezone

    return [
        Message(
            id="m1",
            direction="inbound",
            text="6 crore",
            sent_at=datetime.now(timezone.utc),
            sent_by_service=False,
        )
    ]


VALID_BASICS_INPUT = {
    "reply": "Got it — and how many years have you been in business?",
    "stage": "basics",
    "extracted": {"aum": "6 crore"},
    "escalate": False,
}


async def test_successful_first_try_populates_audit_metadata():
    client = FakeAnthropicClient([tool_use_response(VALID_BASICS_INPUT, input_tokens=120, output_tokens=30)])
    engine = make_engine(client)

    decision = await engine.decide(contact=make_contact(), thread=make_thread(), known_fields={})

    assert decision.reply == VALID_BASICS_INPUT["reply"]
    assert decision.stage == "basics"
    assert decision.escalate is False
    assert decision.regenerated is False
    assert decision.model == "claude-sonnet-5"
    assert decision.prompt_version == "abc123def456"
    assert decision.input_tokens == 120
    assert decision.output_tokens == 30
    assert decision.tool_output == VALID_BASICS_INPUT
    assert len(client.calls) == 1


async def test_invalid_first_reply_triggers_regeneration_then_succeeds():
    bad_input = {**VALID_BASICS_INPUT, "reply": "Visit https://scam.example now"}
    client = FakeAnthropicClient(
        [tool_use_response(bad_input), tool_use_response(VALID_BASICS_INPUT)]
    )
    engine = make_engine(client)

    decision = await engine.decide(contact=make_contact(), thread=make_thread(), known_fields={})

    assert decision.regenerated is True
    assert decision.reply == VALID_BASICS_INPUT["reply"]
    assert len(client.calls) == 2
    # The regeneration call includes the rejection feedback.
    regen_message = client.calls[1]["messages"][0]["content"]
    assert "rejected for" in regen_message


async def test_both_attempts_invalid_escalates_with_validation_failed_reason():
    bad_input = {**VALID_BASICS_INPUT, "reply": "Visit https://scam.example now"}
    client = FakeAnthropicClient([tool_use_response(bad_input), tool_use_response(bad_input)])
    engine = make_engine(client)

    decision = await engine.decide(contact=make_contact(), thread=make_thread(), known_fields={})

    assert decision.escalate is True
    assert decision.stage == "escalated"
    assert decision.escalation_reason.startswith("validation_failed:")
    assert "V2" in decision.escalation_reason
    assert decision.regenerated is True
    assert decision.validation_errors == ["V2"]
    assert len(client.calls) == 2


async def test_no_tool_call_is_treated_as_validation_failure_and_regenerates():
    client = FakeAnthropicClient([no_tool_response(), tool_use_response(VALID_BASICS_INPUT)])
    engine = make_engine(client)

    decision = await engine.decide(contact=make_contact(), thread=make_thread(), known_fields={})

    assert decision.regenerated is True
    assert decision.reply == VALID_BASICS_INPUT["reply"]
    assert len(client.calls) == 2


async def test_malformed_tool_input_is_treated_as_validation_failure():
    malformed = {"reply": "hi"}  # missing required fields (stage, extracted, escalate)
    client = FakeAnthropicClient([tool_use_response(malformed), tool_use_response(VALID_BASICS_INPUT)])
    engine = make_engine(client)

    decision = await engine.decide(contact=make_contact(), thread=make_thread(), known_fields={})

    assert decision.regenerated is True
    assert decision.reply == VALID_BASICS_INPUT["reply"]


async def test_timeout_then_success_retries_once():
    client = FakeAnthropicClient(
        [
            anthropic.APITimeoutError(request=SimpleNamespace()),
            tool_use_response(VALID_BASICS_INPUT),
        ]
    )
    engine = make_engine(client)

    decision = await engine.decide(contact=make_contact(), thread=make_thread(), known_fields={})

    assert decision.escalate is False
    assert len(client.calls) == 2


async def test_timeout_twice_escalates_as_llm_unavailable_without_a_message():
    client = FakeAnthropicClient(
        [
            anthropic.APITimeoutError(request=SimpleNamespace()),
            anthropic.APITimeoutError(request=SimpleNamespace()),
        ]
    )
    engine = make_engine(client)

    decision = await engine.decide(contact=make_contact(), thread=make_thread(), known_fields={})

    assert decision.escalate is True
    assert decision.escalation_reason == "llm_unavailable"
    assert decision.reply == ""
    assert len(client.calls) == 2  # one retry, then give up


async def test_auth_error_escalates_immediately_without_retry():
    response = SimpleNamespace(headers={}, status_code=401, request=SimpleNamespace())
    client = FakeAnthropicClient(
        [anthropic.AuthenticationError("bad key", response=response, body=None)]
    )
    engine = make_engine(client)

    decision = await engine.decide(contact=make_contact(), thread=make_thread(), known_fields={})

    assert decision.escalation_reason == "llm_unavailable"
    assert len(client.calls) == 1  # no retry — same bad key would fail identically


async def test_link_is_injected_only_after_validation_passes():
    invite_input = {
        "reply": "Join us Saturday! [[WEBINAR_LINK]]",
        "stage": "invited",
        "extracted": {},
        "escalate": False,
    }
    client = FakeAnthropicClient([tool_use_response(invite_input)])
    engine = make_engine(client)

    decision = await engine.decide(
        contact=make_contact(tags={"wa-stage-4"}),
        thread=make_thread(),
        known_fields={"wa_aum": "6 crore", "wa_problem_category": "lead_gen"},
    )

    assert decision.stage == "invited"
    assert "[[WEBINAR_LINK]]" not in decision.reply
    assert "https://real-link.example/webinar" in decision.reply


async def test_request_uses_forced_tool_choice_and_cache_control():
    client = FakeAnthropicClient([tool_use_response(VALID_BASICS_INPUT)])
    engine = make_engine(client)

    await engine.decide(contact=make_contact(), thread=make_thread(), known_fields={})

    call = client.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "respond"}
    assert call["tools"][0]["name"] == "respond"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["max_tokens"] == 1000

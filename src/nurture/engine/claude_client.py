"""ClaudeEngine: the real Claude-calling conversation engine (DESIGN.md
Section 7.3, Section 9).

Only this module (and `build_claude_engine`, its factory) knows how to
call the Anthropic API. Everything else in `engine/` (prompt assembly,
validation, state machine) is pure and independently testable.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic
import pydantic

from nurture.engine.prompt import build_user_message, compute_prompt_version, render_system_prompt
from nurture.engine.state import current_stage_from_tags
from nurture.engine.validation import (
    ValidationResult,
    describe_failed_rules,
    inject_link,
    normalise,
    validate,
)
from nurture.ghl.models import Contact, Message
from nurture.settings import Settings
from nurture.worker.engine_interface import ConversationEngine, EngineDecision
from nurture.worker.extracted_fields import known_fields_from_ghl

logger = logging.getLogger("nurture.engine.claude")

MAX_TOKENS = 1000
DEFAULT_TIMEOUT_SECONDS = 30.0
# DESIGN.md Section 7.3: "Timeout 30 s; one retry on timeout/overload".
TRANSPORT_RETRY_EXCEPTIONS = (
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
)


@dataclass
class _ClaudeCallResult:
    decision: EngineDecision | None  # None: no valid tool call (Section 12: treated as a validation failure)
    raw_input: dict | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    latency_ms: int | None
    transport_failed: bool  # True: timeout/overload/auth-failure after retry -> llm_unavailable


class ClaudeEngine(ConversationEngine):
    def __init__(
        self,
        *,
        client: anthropic.AsyncAnthropic,
        model: str,
        system_prompt: str,
        prompt_version: str,
        respond_tool_schema: dict,
        webinar_link: str,
        max_diagnosis_turns: int,
        banned_phrases: list[str],
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._client = client
        self._model = model
        self._system_prompt = system_prompt
        self._prompt_version = prompt_version
        self._respond_tool_schema = respond_tool_schema
        self._webinar_link = webinar_link
        self._max_diagnosis_turns = max_diagnosis_turns
        self._banned_phrases = banned_phrases
        self._timeout = timeout

    async def decide(
        self, *, contact: Contact, thread: list[Message], known_fields: dict[str, str]
    ) -> EngineDecision:
        current_stage = current_stage_from_tags(contact.tags)
        diagnosis_turns_so_far = int(known_fields.get("wa_diagnosis_turns") or 0)
        known_for_prompt = known_fields_from_ghl(known_fields)

        user_message = build_user_message(
            contact=contact,
            thread=thread,
            current_stage=current_stage,
            known_fields=known_for_prompt,
            diagnosis_turns_so_far=diagnosis_turns_so_far,
        )

        result = await self._call(user_message)
        if result.transport_failed:
            return self._llm_unavailable()

        has_aum = bool(known_fields.get("wa_aum"))
        has_problem_category = bool(known_fields.get("wa_problem_category"))
        # Already in "invited" means an invite was already sent in an
        # earlier turn — V3 shouldn't demand the link token again.
        link_already_sent = current_stage == "invited"

        decision, validation_result = self._normalise_and_validate(
            result,
            stage_before=current_stage,
            diagnosis_turns_so_far=diagnosis_turns_so_far,
            has_aum=has_aum,
            has_problem_category=has_problem_category,
            link_already_sent=link_already_sent,
        )

        regenerated = False
        if not validation_result.ok:
            regenerated = True
            feedback = describe_failed_rules(validation_result.failed_rules)
            regen_message = (
                f"{user_message}\n\nYour previous response was rejected for: {feedback}. "
                "Call respond again, fixing these."
            )
            result = await self._call(regen_message)
            if result.transport_failed:
                return self._llm_unavailable(regenerated=True)

            has_aum2 = has_aum or bool(
                (result.decision.extracted.get("aum") if result.decision else None)
            )
            has_problem_category2 = has_problem_category or bool(
                (result.decision.extracted.get("problem_category") if result.decision else None)
            )
            decision, validation_result = self._normalise_and_validate(
                result,
                stage_before=current_stage,
                diagnosis_turns_so_far=diagnosis_turns_so_far,
                has_aum=has_aum2,
                has_problem_category=has_problem_category2,
                link_already_sent=link_already_sent,
            )
            if not validation_result.ok:
                return EngineDecision(
                    reply="",
                    stage="escalated",
                    extracted={},
                    escalate=True,
                    escalation_reason=f"validation_failed:{','.join(validation_result.failed_rules)}",
                    model=self._model,
                    prompt_version=self._prompt_version,
                    tool_output=result.raw_input,
                    validation_errors=validation_result.failed_rules,
                    regenerated=True,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cache_read_tokens=result.cache_read_tokens,
                    latency_ms=result.latency_ms,
                )

        assert decision is not None  # validation_result.ok implies a decision exists
        decision = inject_link(decision, self._webinar_link)
        return decision.model_copy(
            update={
                "model": self._model,
                "prompt_version": self._prompt_version,
                "tool_output": result.raw_input,
                "validation_errors": None,
                "regenerated": regenerated,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cache_read_tokens": result.cache_read_tokens,
                "latency_ms": result.latency_ms,
            }
        )

    def _normalise_and_validate(self, result, **validate_kwargs):
        if result.decision is None:
            return None, ValidationResult(ok=False, failed_rules=["no_tool_call"])
        decision = normalise(result.decision)
        validation_result = validate(
            decision,
            wa_diagnosis_turns=validate_kwargs["diagnosis_turns_so_far"],
            max_diagnosis_turns=self._max_diagnosis_turns,
            stage_before=validate_kwargs["stage_before"],
            has_aum=validate_kwargs["has_aum"],
            has_problem_category=validate_kwargs["has_problem_category"],
            link_already_sent=validate_kwargs["link_already_sent"],
            banned_phrases=self._banned_phrases,
        )
        return decision, validation_result

    def _llm_unavailable(self, *, regenerated: bool = False) -> EngineDecision:
        # DESIGN.md Section 7.3/12: no message to the lead, tag only.
        return EngineDecision(
            reply="",
            stage="escalated",
            extracted={},
            escalate=True,
            escalation_reason="llm_unavailable",
            model=self._model,
            prompt_version=self._prompt_version,
            regenerated=regenerated,
        )

    async def _call(self, user_content: str) -> _ClaudeCallResult:
        attempt = 0
        start = time.monotonic()
        response = None
        while response is None:
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=MAX_TOKENS,
                    system=[
                        {
                            "type": "text",
                            "text": self._system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": user_content}],
                    tools=[self._respond_tool_schema],
                    tool_choice={"type": "tool", "name": "respond"},
                    timeout=self._timeout,
                )
            except TRANSPORT_RETRY_EXCEPTIONS:
                if attempt >= 1:
                    logger.warning("Claude call failed after retry (timeout/overload)")
                    return _ClaudeCallResult(
                        decision=None,
                        raw_input=None,
                        input_tokens=None,
                        output_tokens=None,
                        cache_read_tokens=None,
                        latency_ms=None,
                        transport_failed=True,
                    )
                attempt += 1
                continue
            except anthropic.APIStatusError:
                # e.g. auth/permission errors — retrying with the same
                # request would fail identically, so don't retry.
                logger.exception("Claude call failed (non-retryable API error)")
                return _ClaudeCallResult(
                    decision=None,
                    raw_input=None,
                    input_tokens=None,
                    output_tokens=None,
                    cache_read_tokens=None,
                    latency_ms=None,
                    transport_failed=True,
                )

        latency_ms = int((time.monotonic() - start) * 1000)
        usage = response.usage
        tool_use = next(
            (
                block
                for block in response.content
                if getattr(block, "type", None) == "tool_use" and block.name == "respond"
            ),
            None,
        )
        if tool_use is None:
            return _ClaudeCallResult(
                decision=None,
                raw_input=None,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", None),
                latency_ms=latency_ms,
                transport_failed=False,
            )

        raw_input = tool_use.input if isinstance(tool_use.input, dict) else json.loads(tool_use.input)
        try:
            decision = EngineDecision.model_validate(raw_input)
        except pydantic.ValidationError:
            return _ClaudeCallResult(
                decision=None,
                raw_input=raw_input,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", None),
                latency_ms=latency_ms,
                transport_failed=False,
            )

        return _ClaudeCallResult(
            decision=decision,
            raw_input=raw_input,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", None),
            latency_ms=latency_ms,
            transport_failed=False,
        )


def build_claude_engine(settings: Settings) -> ClaudeEngine:
    """Factory used by main.py: renders the prompt from files/config,
    loads the respond tool schema and banned phrases, and constructs a
    real ClaudeEngine wired to the real Anthropic API."""

    system_prompt = render_system_prompt(
        prompts_dir=settings.prompts_dir,
        config_dir=settings.config_dir,
        session_name=settings.session_name,
        session_when=settings.session_when,
        session_cost=settings.session_cost,
        max_diagnosis_turns=settings.max_diagnosis_turns,
    )
    prompt_version = compute_prompt_version(system_prompt)
    respond_tool_schema = json.loads((settings.prompts_dir / "respond_tool.json").read_text())
    banned_phrases = _load_banned_phrases(settings.config_dir / "banned_phrases.yaml")

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    return ClaudeEngine(
        client=client,
        model=settings.claude_model,
        system_prompt=system_prompt,
        prompt_version=prompt_version,
        respond_tool_schema=respond_tool_schema,
        webinar_link=settings.webinar_link,
        max_diagnosis_turns=settings.max_diagnosis_turns,
        banned_phrases=banned_phrases,
    )


def _load_banned_phrases(path: Path) -> list[str]:
    import yaml

    data = yaml.safe_load(path.read_text()) or {}
    return [str(p) for p in data.get("phrases", [])]

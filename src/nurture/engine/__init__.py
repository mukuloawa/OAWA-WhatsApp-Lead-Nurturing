"""The conversation engine (DESIGN.md Section 9, Section 17 Phase 4).

- prompt.py: system prompt rendering (Appendix A token substitution) and
  user message assembly (Section 9.1), plus the prompt_version hash.
- validation.py: post-LLM output validation V1-V7 (Section 9.2) and
  [[WEBINAR_LINK]] injection (Section 9.3).
- state.py: the stage<->tag data table and transition legality
  (Section 5, Section 5.1) — DESIGN.md Section 4 assigns both to this
  module.
- claude_client.py: ClaudeEngine, the real Claude-calling
  ConversationEngine implementation, with the regenerate-once-on-
  validation-failure flow (Section 9.4) and the retry-once-then-
  llm_unavailable flow (Section 7.3/12).
"""

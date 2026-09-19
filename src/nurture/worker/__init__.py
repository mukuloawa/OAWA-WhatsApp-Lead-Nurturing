"""Webhook scheduling, debounce, startup recovery, and the pipeline
itself (DESIGN.md Section 8, Section 17 Phase 3).

- pipeline.py: process(event_id) and run_decision() — guards + the
  (stubbed, until Phase 4) engine call + send-mode action.
- scheduler.py: debounced scheduling and startup recovery of pending events.
- locks.py: per-contact locking (Postgres advisory lock / SQLite asyncio.Lock).
- actions.py: applying a decision according to SEND_MODE.
- stage_tags.py: the stage<->tag data table (not transition validation —
  that's engine/state.py, Phase 4).
- engine_interface.py: the seam to the Phase 4 conversation engine, plus
  a safe AlwaysEscalateEngine placeholder used until it exists.
"""

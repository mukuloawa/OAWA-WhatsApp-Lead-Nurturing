"""Error types raised by RealGHLClient, per DESIGN.md Section 12's error table.

Kept distinguishable so a later caller (the Phase 3 pipeline) can branch
on them exactly as Section 12 describes, without needing to inspect HTTP
status codes itself.
"""

from __future__ import annotations


class GHLError(Exception):
    """Base class for all GHL adapter errors."""


class GHLAuthError(GHLError):
    """401/403 — DESIGN.md Section 12: fail the event, no retry."""


class GHLNotFoundError(GHLError):
    """404 — DESIGN.md Section 12: e.g. skipped: contact_not_found."""


class GHLRateLimitedError(GHLError):
    """429/5xx with retries exhausted — DESIGN.md Section 12: fail the event."""

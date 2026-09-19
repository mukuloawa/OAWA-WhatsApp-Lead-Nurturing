"""GHLClient protocol, RealGHLClient, FakeGHLClient (DESIGN.md Section 7.2).

This is the ONLY module allowed to make GHL HTTP calls (DESIGN.md
Section 0, rule 4). See docs/phase0-findings.md for the operations
verified against the real account, and real.py's module docstring for
the one place this adapter's endpoints deviate from DESIGN.md's
original assumptions (get_thread's underlying endpoint).
"""

from nurture.ghl.client import GHLClient
from nurture.ghl.errors import GHLAuthError, GHLError, GHLNotFoundError, GHLRateLimitedError
from nurture.ghl.fake import FakeGHLClient
from nurture.ghl.fields import WA_CUSTOM_FIELD_KEYS, from_ghl_field_key, to_ghl_field_key
from nurture.ghl.models import Contact, Message
from nurture.ghl.real import RealGHLClient

__all__ = [
    "GHLClient",
    "RealGHLClient",
    "FakeGHLClient",
    "Contact",
    "Message",
    "GHLError",
    "GHLAuthError",
    "GHLNotFoundError",
    "GHLRateLimitedError",
    "WA_CUSTOM_FIELD_KEYS",
    "to_ghl_field_key",
    "from_ghl_field_key",
]

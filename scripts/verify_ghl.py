#!/usr/bin/env python3
"""Phase 0 GHL verification probe (DESIGN.md Section 17, Phase 0).

Not implemented as a script yet: the actual Phase 0 read-only verification
for this project was performed interactively against the real Synamate
account (see docs/phase0-findings.md for full results) rather than through
this script, since RealGHLClient (Phase 2) did not exist at the time.

Once Phase 2 builds `nurture.ghl.RealGHLClient`, this script should be
filled in to re-run the same read-only checks reproducibly, and to save
fresh anonymised fixtures under tests/fixtures/ghl/.
"""

raise SystemExit(
    "Not implemented yet — see docs/phase0-findings.md for the Phase 0 "
    "verification results, and DESIGN.md Section 17 Phase 2 for when this "
    "script is meant to be built."
)

from __future__ import annotations

import time
from typing import Any


def remaining_deadline_seconds(deadline_at: Any) -> float | None:
    """Return seconds until a Unix deadline timestamp, or None if absent/invalid."""
    if deadline_at is None:
        return None
    try:
        return float(deadline_at) - time.time()
    except (TypeError, ValueError):
        return None

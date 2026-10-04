"""Policy numbers kept together so they can be tuned without archaeology."""

LIMITS = {
    "headline_chars": 120,
    "outline_chars": 600,
    "status_chars": 3000,
    "from_chars": 1500,
    "inherited_items": 3,
    "inherited_chars": 160,
    "recent_events": 5,
    "unsynced_nudge": 8,
    "release_events": 3,
    "stale_claim_hours": 4,
    "artifact_index": 25,
    "register_bytes": 5 * 1024 * 1024,
    "inactive_days": 14,
    "context_inactive": 10,
    "old_scratch_days": 30,
    "orientation_chars": 1500,
}

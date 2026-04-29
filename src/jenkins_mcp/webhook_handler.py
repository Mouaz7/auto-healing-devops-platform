"""Webhook handler for Agent 1 — receives Jenkins build events, filters duplicates."""
from __future__ import annotations

import logging
from datetime import datetime, UTC

from src.shared.models import BuildEvent

logger = logging.getLogger(__name__)


class WebhookHandler:
    """Receives Jenkins webhooks, deduplicates by build_id, creates BuildEvents.

    Deduplication is in-memory. Restarts clear the set — acceptable for
    the current single-instance design.
    """

    def __init__(self) -> None:
        self._seen_builds: set[str] = set()

    def handle(self, payload: dict) -> BuildEvent | None:
        """Parse a webhook payload into a BuildEvent.

        Returns None if:
        - build_id is missing or empty
        - build_id was already processed (duplicate)
        - status is not a failure state

        Args:
            payload: Raw JSON dict from Jenkins webhook.

        Returns:
            BuildEvent on first valid failure, None otherwise.
        """
        build_id = payload.get("build_id", "").strip()
        if not build_id:
            logger.warning("webhook_rejected reason=missing_build_id")
            return None

        if build_id in self._seen_builds:
            logger.info("webhook_duplicate build_id=%s", build_id)
            return None

        status = payload.get("status", "").upper()
        if status not in {"FAILED", "FAILURE", "ERROR", "ABORTED"}:
            logger.info("webhook_ignored build_id=%s status=%s", build_id, status)
            return None

        self._seen_builds.add(build_id)
        event = BuildEvent(
            build_id=build_id,
            repo=payload.get("repo", ""),
            branch=payload.get("branch", ""),
            timestamp=datetime.now(UTC),
            job_name=payload.get("job_name", ""),
            status=status,
            log_url=payload.get("log_url", ""),
        )
        logger.info("webhook_accepted build_id=%s repo=%s branch=%s",
                    build_id, event.repo, event.branch)
        return event

    def reset(self) -> None:
        """Clear deduplication state (for testing)."""
        self._seen_builds.clear()

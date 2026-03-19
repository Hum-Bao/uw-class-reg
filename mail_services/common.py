"""Shared mail service utilities and constants."""

# ruff: noqa: T201

import re
import time
from collections.abc import Callable

DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
SLN_REGEX = re.compile(r"SLN\s*:\s*(\d{5})", flags=re.IGNORECASE)


def normalize_markers(markers: list[str]) -> list[str]:
    """Return lowercase, non-empty sender marker strings."""
    return [marker.lower() for marker in markers if marker]


def extract_sln_from_text(content: str) -> str:
    """Extract first 5-digit SLN from message content."""
    match = SLN_REGEX.search(content)
    return match.group(1) if match else ""


def render_poll_countdown(*, last_poll_epoch: float, seconds_remaining: int) -> None:
    """Render a single-line countdown until next poll."""
    last_poll_time = time.strftime("%H:%M:%S", time.localtime(last_poll_epoch))
    print(
        (f"Last polled at {last_poll_time} | Next poll in {seconds_remaining:02d}s"),
        end="\r",
    )


def countdown_to_next_poll(
    *,
    poll_interval_seconds: int,
    last_poll_epoch: float,
    maintenance_callback: Callable[[], bool] | None = None,
) -> bool:
    """Wait until next poll while rendering a live countdown."""
    for seconds_remaining in range(poll_interval_seconds, 0, -1):
        if maintenance_callback is not None and not maintenance_callback():
            return False
        render_poll_countdown(
            last_poll_epoch=last_poll_epoch,
            seconds_remaining=seconds_remaining,
        )
        time.sleep(1)
    return True

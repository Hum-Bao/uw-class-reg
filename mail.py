"""Central mail interface for scheduler and menu integrations.

This module exposes a stable, high-level API while delegating concrete
implementations to the internal mail_services package.
"""

from collections.abc import Callable

from mail_services.gmail import (
    validate_gmail_api_credentials,
    wait_for_notifyuw_sln_gmail_api,
)
from mail_services.imap import (
    parse_imap_server,
    validate_imap_credentials,
    wait_for_notifyuw_sln,
    wait_for_trigger_email,
)

__all__ = [
    "parse_imap_server",
    "validate_gmail_api_credentials",
    "validate_imap_credentials",
    "wait_for_notifyuw_sln",
    "wait_for_notifyuw_sln_gmail_api",
    "wait_for_trigger_email",
    "wait_for_notifyuw_sln_via_gmail_api",
]


def wait_for_notifyuw_sln_via_gmail_api(
    *,
    username: str,
    sender_markers: list[str],
    poll_interval_seconds: int,
    maintenance_callback: Callable[[], bool] | None = None,
) -> str:
    """Facade alias for Gmail API Notify.UW listener flow."""
    return wait_for_notifyuw_sln_gmail_api(
        username=username,
        sender_markers=sender_markers,
        poll_interval_seconds=poll_interval_seconds,
        maintenance_callback=maintenance_callback,
    )

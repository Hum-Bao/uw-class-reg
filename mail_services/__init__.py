"""Mail package exports for scheduling and email-trigger workflows."""

from .imap import (
    parse_imap_server,
    validate_imap_credentials,
    wait_for_notifyuw_sln,
    wait_for_trigger_email,
)

__all__ = [
    "parse_imap_server",
    "validate_imap_credentials",
    "wait_for_notifyuw_sln",
    "wait_for_trigger_email",
]

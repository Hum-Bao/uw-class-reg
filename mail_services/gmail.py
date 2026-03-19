"""Gmail API read-only polling utilities for Notify.UW trigger emails."""

# ruff: noqa: T201

import base64
import importlib
import time
from collections.abc import Callable
from typing import Protocol, cast

from . import oauth2
from .common import (
    countdown_to_next_poll,
    extract_sln_from_text,
    normalize_markers,
)

GMAIL_LIST_MAX_RESULTS = 25


class _ExecutableRequest(Protocol):
    def execute(self) -> object: ...


def _load_gmail_build_function() -> Callable[..., object]:
    """Load googleapiclient discovery.build lazily at runtime."""
    module = importlib.import_module("googleapiclient.discovery")
    build_function = module.build
    return cast("Callable[..., object]", build_function)


def _looks_like_gmail_http_error(error: Exception) -> bool:
    """Return True when exception originated from googleapiclient HTTP layer."""
    return error.__class__.__module__.startswith("googleapiclient")


def _call_method(target: object, method_name: str, **kwargs: object) -> object:
    """Invoke a named method via dynamic lookup and return the call result."""
    method = cast("Callable[..., object]", getattr(target, method_name))
    return method(**kwargs)


def _execute_request(request: _ExecutableRequest) -> dict[str, object]:
    """Execute a googleapiclient request object and normalize dict output."""
    execute = request.execute
    result = execute()
    if isinstance(result, dict):
        return cast("dict[str, object]", result)
    return {}


def _build_gmail_service() -> object:
    """Build Gmail API service using env-backed OAuth credentials."""
    credentials = oauth2.get_google_credentials_from_env()
    build = _load_gmail_build_function()
    return build(
        "gmail",
        "v1",
        credentials=credentials,
        cache_discovery=False,
    )


def _list_unread_message_ids(*, service: object) -> list[str]:
    """Return unread Gmail message IDs."""
    users = _call_method(service, "users")
    messages = _call_method(users, "messages")
    request = _call_method(
        messages,
        "list",
        userId="me",
        q="is:unread",
        maxResults=GMAIL_LIST_MAX_RESULTS,
    )
    listing = _execute_request(cast("_ExecutableRequest", request))

    messages_raw = listing.get("messages", [])
    if not isinstance(messages_raw, list):
        return []
    message_items = cast("list[object]", messages_raw)

    message_ids: list[str] = []
    for message_raw in message_items:
        if not isinstance(message_raw, dict):
            continue
        message = cast("dict[str, object]", message_raw)
        message_id = str(message.get("id", "")).strip()
        if message_id:
            message_ids.append(message_id)
    return message_ids


def _decode_base64url(text: str) -> str:
    """Decode Gmail API base64url-encoded content into UTF-8 text."""
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="ignore")


def _extract_text_from_gmail_payload(payload: dict[str, object]) -> str:
    """Extract readable text content from Gmail message payload."""
    mime_type = str(payload.get("mimeType", "")).lower()
    body = payload.get("body", {})
    if isinstance(body, dict):
        body_dict = cast("dict[str, object]", body)
        encoded_data = str(body_dict.get("data", "") or "")
        if encoded_data and mime_type in {"text/plain", "text/html"}:
            return _decode_base64url(encoded_data)

    parts = payload.get("parts", [])
    if not isinstance(parts, list):
        return ""
    part_items = cast("list[object]", parts)

    text_parts: list[str] = []
    for part_raw in part_items:
        if not isinstance(part_raw, dict):
            continue
        part = cast("dict[str, object]", part_raw)
        part_text = _extract_text_from_gmail_payload(part)
        if part_text:
            text_parts.append(part_text)

    return "\n".join(text_parts)


def _message_from_header(headers: list[dict[str, object]]) -> str:
    """Return lowercase From header value from Gmail message headers."""
    for header in headers:
        name = str(header.get("name", ""))
        if name.lower() != "from":
            continue
        return str(header.get("value", "")).lower()
    return ""


def _extract_sender_and_body_from_message(
    *,
    service: object,
    message_id: str,
) -> tuple[str, str]:
    """Fetch message details and return lowercase sender plus decoded body text."""
    users = _call_method(service, "users")
    messages = _call_method(users, "messages")
    request = _call_method(
        messages,
        "get",
        userId="me",
        id=message_id,
        format="full",
    )
    details = _execute_request(cast("_ExecutableRequest", request))
    payload_raw = details.get("payload", {})
    if not isinstance(payload_raw, dict):
        return "", ""

    payload = cast("dict[str, object]", payload_raw)
    headers_raw = payload.get("headers", [])
    sender_header = ""
    if isinstance(headers_raw, list):
        header_values = cast("list[object]", headers_raw)
        header_items = [
            cast("dict[str, object]", header_raw)
            for header_raw in header_values
            if isinstance(header_raw, dict)
        ]
        sender_header = _message_from_header(header_items)

    body_text = _extract_text_from_gmail_payload(payload)
    return sender_header, body_text


def validate_gmail_api_credentials(*, username: str) -> bool:
    """Validate Gmail API auth by fetching profile for the authenticated user."""
    if not username:
        print("Missing IMAP_USERNAME (used as Gmail address for API mode).")
        return False

    try:
        service = _build_gmail_service()
        users = _call_method(service, "users")
        request = _call_method(users, "getProfile", userId="me")
        profile = _execute_request(cast("_ExecutableRequest", request))
        email_address = str(profile.get("emailAddress", ""))
        print(f"Gmail API credentials validated for {email_address or username}.")
    except (ValueError, TimeoutError) as error:
        print(f"Gmail API validation failed: {error}")
        return False
    except Exception as error:
        if _looks_like_gmail_http_error(error):
            print(f"Gmail API validation failed: {error}")
            return False
        raise
    else:
        return True


def wait_for_notifyuw_sln_gmail_api(
    *,
    username: str,
    sender_markers: list[str],
    poll_interval_seconds: int,
    maintenance_callback: Callable[[], bool] | None = None,
) -> str:
    """Wait for Notify.UW-style Gmail message and return extracted SLN."""
    if not username:
        print("Missing IMAP_USERNAME (used as Gmail address for API mode).")
        return ""

    normalized_markers = normalize_markers(sender_markers)

    print("\nListening for Notify.UW trigger message...")
    print(f"Gmail user: {username}")
    print("Press Ctrl+C to cancel.")

    seen_message_ids: set[str] = set()
    try:
        # Build initial baseline of unread messages so we only react to new arrivals.
        service = _build_gmail_service()
        seen_message_ids.update(_list_unread_message_ids(service=service))

        while True:
            service = _build_gmail_service()
            unread_ids = _list_unread_message_ids(service=service)
            last_poll_epoch = time.time()
            extracted_sln = _extract_sln_from_unread_messages(
                service=service,
                unread_ids=unread_ids,
                seen_message_ids=seen_message_ids,
                normalized_markers=normalized_markers,
            )
            if extracted_sln:
                return extracted_sln

            if not countdown_to_next_poll(
                poll_interval_seconds=poll_interval_seconds,
                last_poll_epoch=last_poll_epoch,
                maintenance_callback=maintenance_callback,
            ):
                print("\nStopping email listener due to failed re-authentication.")
                return ""
    except KeyboardInterrupt:
        print("\nEmail listener cancelled.")
        return ""
    except (ValueError, TimeoutError) as error:
        print(f"Gmail API error: {error}")
        return ""
    except Exception as error:
        if _looks_like_gmail_http_error(error):
            print(f"Gmail API error: {error}")
            return ""
        raise


def _extract_sln_from_unread_messages(
    *,
    service: object,
    unread_ids: list[str],
    seen_message_ids: set[str],
    normalized_markers: list[str],
) -> str:
    """Process unread messages and return the first matched SLN, if found."""
    for message_id in unread_ids:
        if message_id in seen_message_ids:
            continue
        seen_message_ids.add(message_id)

        sender_header, body_text = _extract_sender_and_body_from_message(
            service=service,
            message_id=message_id,
        )
        if normalized_markers and not any(
            marker in sender_header for marker in normalized_markers
        ):
            continue

        sln = extract_sln_from_text(body_text)
        if sln:
            print(f"\nTrigger email matched. Extracted SLN: {sln}")
            return sln

        print("\nTrigger email matched but no SLN found; continuing to listen.")

    return ""

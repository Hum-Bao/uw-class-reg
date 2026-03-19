"""IMAP email trigger utilities for registration workflows."""

# ruff: noqa: T201

import email
import imaplib
import time
from collections.abc import Callable
from urllib.parse import urlparse

from . import oauth2
from .common import (
    countdown_to_next_poll,
    extract_sln_from_text,
    normalize_markers,
)

DEFAULT_IMAP_PORT = 993
DEFAULT_MAILBOX_NAME = "INBOX"
INVALID_IMAP_SERVER_MESSAGE = (
    "Invalid IMAP server. Example: imap.gmail.com or imap.gmail.com:993"
)


def _imap_escape(value: str) -> str:
    """Escape double quotes for use in IMAP SEARCH quoted strings."""
    return value.replace('"', "")


def _build_imap_search_query(sender: str, subject_keyword: str) -> str:
    """Build IMAP search query for unseen trigger email messages."""
    clauses = ["UNSEEN"]
    if sender:
        clauses.append(f'FROM "{_imap_escape(sender)}"')
    if subject_keyword:
        clauses.append(f'SUBJECT "{_imap_escape(subject_keyword)}"')
    return "(" + " ".join(clauses) + ")"


def _search_imap_uids(mailbox: imaplib.IMAP4_SSL, query: str) -> set[str]:
    """Run IMAP SEARCH and return matching UID strings."""
    status, data = mailbox.search(None, query)
    if status != "OK" or not data:
        return set()
    raw_ids = data[0].decode("utf-8", errors="ignore").strip()
    if not raw_ids:
        return set()
    return set(raw_ids.split())


def _fetch_message_bytes(mailbox: imaplib.IMAP4_SSL, message_id: str) -> bytes | None:
    """Fetch raw RFC822 bytes for a message ID from the selected mailbox."""
    status, data = mailbox.fetch(message_id, "(RFC822)")
    if status != "OK" or not data:
        return None

    for item in data:
        if isinstance(item, tuple) and len(item) >= 2:
            payload = item[1]
            if isinstance(payload, bytes):
                return payload
    return None


def _extract_text_content(message_obj: email.message.Message) -> str:
    """Extract readable text from an email message."""
    if message_obj.is_multipart():
        parts: list[str] = []
        for part in message_obj.walk():
            content_type = part.get_content_type().lower()
            if content_type != "text/plain":
                continue
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                continue
            charset = part.get_content_charset() or "utf-8"
            parts.append(payload.decode(charset, errors="ignore"))
        return "\n".join(parts)

    payload = message_obj.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = message_obj.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="ignore")
    if isinstance(payload, str):
        return payload
    return ""


def parse_imap_server(server: str) -> tuple[str, int]:
    """Parse IMAP server input into host and port.

    Accepts values like:
    - imap.gmail.com
    - imap.gmail.com:993
    - imaps://imap.gmail.com
    - imaps://imap.gmail.com:993
    """
    normalized = server.strip()
    if not normalized:
        return "", 0

    if "://" not in normalized:
        normalized = f"imaps://{normalized}"

    parsed = urlparse(normalized)
    host = parsed.hostname or ""
    try:
        port = parsed.port or DEFAULT_IMAP_PORT
    except ValueError:
        return "", 0
    return host, port


def _imap_login(
    mailbox: imaplib.IMAP4_SSL,
    *,
    username: str,
    password: str,
    use_google_oauth2: bool,
) -> None:
    """Authenticate against IMAP using password or Google OAuth2 XOAUTH2."""
    if not use_google_oauth2:
        mailbox.login(username, password)
        return

    access_token = oauth2.get_google_access_token_from_env()
    xoauth2_payload = oauth2.build_google_xoauth2_payload(username, access_token)
    mailbox.authenticate("XOAUTH2", lambda _: xoauth2_payload)


def _connect_and_select_mailbox(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    mailbox_name: str,
    use_google_oauth2: bool,
) -> imaplib.IMAP4_SSL:
    """Create an IMAP connection, authenticate, and select the mailbox."""
    mailbox = imaplib.IMAP4_SSL(host, port)
    try:
        _imap_login(
            mailbox,
            username=username,
            password=password,
            use_google_oauth2=use_google_oauth2,
        )
        status, _ = mailbox.select(mailbox_name)
        if status != "OK":
            error_message = f"Could not access mailbox '{mailbox_name}'."
            raise imaplib.IMAP4.error(error_message)
    except Exception:
        try:
            mailbox.logout()
        except imaplib.IMAP4.error:
            pass
        raise
    return mailbox


def wait_for_trigger_email(
    *,
    imap_server: str,
    username: str,
    password: str,
    sender: str,
    subject_keyword: str,
    poll_interval_seconds: int,
    mailbox_name: str = DEFAULT_MAILBOX_NAME,
    use_google_oauth2: bool = False,
) -> bool:
    """Wait for a matching unseen IMAP message and return when one arrives."""
    host, port = parse_imap_server(imap_server)
    if not host:
        print(INVALID_IMAP_SERVER_MESSAGE)
        return False

    query = _build_imap_search_query(sender, subject_keyword)
    print("\nListening for trigger message...")
    print(f"IMAP: {host}:{port} | Mailbox: {mailbox_name}")
    print(f"Query: {query}")
    print("Press Ctrl+C to cancel.")

    mailbox: imaplib.IMAP4_SSL | None = None
    try:
        mailbox = _connect_and_select_mailbox(
            host=host,
            port=port,
            username=username,
            password=password,
            mailbox_name=mailbox_name,
            use_google_oauth2=use_google_oauth2,
        )

        baseline_uids = _search_imap_uids(mailbox, query)

        while True:
            current_uids = _search_imap_uids(mailbox, query)
            last_poll_epoch = time.time()
            new_uids = current_uids - baseline_uids
            if new_uids:
                print("\nTrigger email detected. Starting registration now...")
                return True

            if not countdown_to_next_poll(
                poll_interval_seconds=poll_interval_seconds,
                last_poll_epoch=last_poll_epoch,
            ):
                return False
    except KeyboardInterrupt:
        print("\nEmail listener cancelled.")
        return False
    except imaplib.IMAP4.error as error:
        print(f"IMAP error: {error}")
        return False
    except OSError as error:
        print(f"IMAP network error: {error}")
        return False
    finally:
        if mailbox is not None:
            try:
                mailbox.logout()
            except imaplib.IMAP4.error:
                pass


def wait_for_notifyuw_sln(
    *,
    imap_server: str,
    username: str,
    password: str,
    sender_markers: list[str],
    poll_interval_seconds: int,
    mailbox_name: str = DEFAULT_MAILBOX_NAME,
    maintenance_callback: Callable[[], bool] | None = None,
    use_google_oauth2: bool = False,
) -> str:
    """Wait for a Notify.UW-style email and return extracted SLN.

    Returns empty string if cancelled or on error.
    """
    host, port = parse_imap_server(imap_server)
    if not host:
        print(INVALID_IMAP_SERVER_MESSAGE)
        return ""

    normalized_markers = normalize_markers(sender_markers)
    query = "(UNSEEN)"

    print("\nListening for Notify.UW trigger message...")
    print(f"IMAP: {host}:{port} | Mailbox: {mailbox_name}")
    print("Press Ctrl+C to cancel.")

    mailbox: imaplib.IMAP4_SSL | None = None
    try:
        mailbox = _connect_and_select_mailbox(
            host=host,
            port=port,
            username=username,
            password=password,
            mailbox_name=mailbox_name,
            use_google_oauth2=use_google_oauth2,
        )

        baseline_ids = _search_imap_uids(mailbox, query)

        while True:
            current_ids = _search_imap_uids(mailbox, query)
            last_poll_epoch = time.time()
            new_ids = current_ids - baseline_ids
            for message_id in sorted(new_ids, key=lambda item: int(item)):
                message_bytes = _fetch_message_bytes(mailbox, message_id)
                if not message_bytes:
                    baseline_ids.add(message_id)
                    continue

                message_obj = email.message_from_bytes(message_bytes)
                sender_header = str(message_obj.get("From", "")).lower()
                if normalized_markers and not any(
                    marker in sender_header for marker in normalized_markers
                ):
                    baseline_ids.add(message_id)
                    continue

                body_text = _extract_text_content(message_obj)
                sln = extract_sln_from_text(body_text)
                if sln:
                    print(f"\nTrigger email matched. Extracted SLN: {sln}")
                    return sln

                print("\nTrigger email matched but no SLN found; continuing to listen.")
                baseline_ids.add(message_id)

            baseline_ids.update(new_ids)
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
    except imaplib.IMAP4.error as error:
        print(f"IMAP error: {error}")
        return ""
    except OSError as error:
        print(f"IMAP network error: {error}")
        return ""
    finally:
        if mailbox is not None:
            try:
                mailbox.logout()
            except imaplib.IMAP4.error:
                pass


def validate_imap_credentials(
    *,
    imap_server: str,
    username: str,
    password: str,
    mailbox_name: str = DEFAULT_MAILBOX_NAME,
    use_google_oauth2: bool = False,
) -> bool:
    """Validate IMAP server and credentials by connecting, logging in, and selecting a mailbox."""
    host, port = parse_imap_server(imap_server)
    if not host:
        print(INVALID_IMAP_SERVER_MESSAGE)
        return False

    mailbox: imaplib.IMAP4_SSL | None = None
    try:
        mailbox = _connect_and_select_mailbox(
            host=host,
            port=port,
            username=username,
            password=password,
            mailbox_name=mailbox_name,
            use_google_oauth2=use_google_oauth2,
        )
        print(f"IMAP credentials validated for {host}:{port} ({mailbox_name}).")
        return True
    except imaplib.IMAP4.error as error:
        print(f"IMAP validation failed: {error}")
        return False
    except OSError as error:
        print(f"IMAP validation failed: {error}")
        return False
    finally:
        if mailbox is not None:
            try:
                mailbox.logout()
            except imaplib.IMAP4.error:
                pass

"""Main entry point for UW class registration application.

This module handles authentication and launches the interactive menu.
"""
# ruff: noqa: T201

import os

from dotenv import load_dotenv, set_key

import uw_selenium
import UWAPI
from menu import run_menu


def build_authenticated_client() -> UWAPI.UWAPI | None:
    """Build an authenticated API client, refreshing session token when needed.

    Returns:
        Authenticated UWAPI client instance, or None if authentication fails.

    """
    load_dotenv()
    session_id = os.getenv("UW_SESSION_ID", "")
    client = UWAPI.UWAPI(session_id=session_id)

    if client.authenticate():
        print(f"Authenticated successfully as Student #{client.student_number}")
        return client

    print(
        "Could not establish an authenticated session. Attempting to get a new token.",
    )
    session_id = uw_selenium.get_fresh_session_token_hybrid(verbose=True)

    if len(session_id) == 0:
        print("Could not retrieve a new session id")
        return None

    set_key(
        dotenv_path=".env",
        key_to_set="UW_SESSION_ID",
        value_to_set=session_id,
    )
    print("New session id obtained, re-authenticating now")

    refreshed_client = UWAPI.UWAPI(session_id=session_id)
    if refreshed_client.authenticate():
        print(
            f"Authenticated successfully as Student #{refreshed_client.student_number}",
        )
        return refreshed_client

    print("Could not authenticate even after refreshing session id")
    return None


def main() -> None:
    """Execute main application logic."""
    client = build_authenticated_client()
    if client is None:
        return

    run_menu(client)


if __name__ == "__main__":
    main()

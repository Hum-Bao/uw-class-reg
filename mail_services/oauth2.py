"""OAuth2 helpers for Google IMAP authentication."""

# pyright: reportMissingTypeStubs=false
# ruff: noqa: T201

import os
from typing import Protocol, cast

from dotenv import set_key
from google.auth.transport import Request as GoogleAuthRequestProtocol
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials as GoogleCredentials
from google_auth_oauthlib.flow import (
    InstalledAppFlow,  # type: ignore[reportMissingTypeStubs]
)

GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105
GOOGLE_IMAP_SCOPE = "https://mail.google.com/"
LOCAL_CALLBACK_HOST = "127.0.0.1"
LOCAL_CALLBACK_PORT = 8765


class _InstalledAppFlowProtocol(Protocol):
    """Small protocol surface used by this module for OAuth web flow."""

    def run_local_server(
        self,
        *,
        host: str,
        port: int,
        open_browser: bool,
        authorization_prompt_message: str,
        success_message: str,
        **kwargs: object,
    ) -> "_GoogleOAuthCredentialsProtocol": ...


class _InstalledAppFlowFactoryProtocol(Protocol):
    """Factory protocol for creating installed app OAuth flows."""

    def from_client_config(
        self,
        client_config: dict[str, object],
        scopes: list[str],
        **kwargs: object,
    ) -> _InstalledAppFlowProtocol: ...


class _GoogleOAuthCredentialsProtocol(Protocol):
    """Credential fields/methods used in this module."""

    refresh_token: str | None
    token: str | None

    def refresh(self, request: GoogleAuthRequestProtocol) -> None: ...


def build_google_xoauth2_payload(username: str, access_token: str) -> bytes:
    """Build XOAUTH2 auth payload bytes for imaplib.authenticate."""
    return f"user={username}\x01auth=Bearer {access_token}\x01\x01".encode()


def _get_env(name: str) -> str:
    """Get a stripped environment variable value, or empty string if missing."""
    return os.getenv(name, "").strip()


def _require_env(name: str) -> str:
    """Require a non-empty environment variable value."""
    value = _get_env(name)
    if value:
        return value
    error_message = f"Missing required environment variable: {name}"
    raise ValueError(error_message)


def _get_google_scope_from_env() -> str:
    """Return OAuth scope from env, defaulting to Gmail full scope for IMAP."""
    return _get_env("GOOGLE_OAUTH_SCOPE") or GOOGLE_IMAP_SCOPE


def _build_client_config(*, client_id: str, client_secret: str) -> dict[str, object]:
    """Build OAuth client config dict for InstalledAppFlow."""
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": GOOGLE_TOKEN_ENDPOINT,
        },
    }


def _ensure_google_refresh_token_via_flow(
    *,
    client_id: str,
    client_secret: str,
    scope: str,
) -> str:
    """Run browser OAuth flow via official client and persist refresh token."""
    flow_factory = cast("_InstalledAppFlowFactoryProtocol", InstalledAppFlow)
    flow = flow_factory.from_client_config(
        _build_client_config(client_id=client_id, client_secret=client_secret),
        scopes=[scope],
    )
    credentials = flow.run_local_server(
        host=LOCAL_CALLBACK_HOST,
        port=LOCAL_CALLBACK_PORT,
        open_browser=True,
        authorization_prompt_message=(
            "\nGOOGLE_REFRESH_TOKEN is missing. Opening browser for OAuth consent..."
        ),
        success_message="Authorization received. You can close this window.",
    )

    refresh_token = (credentials.refresh_token or "").strip()
    if not refresh_token:
        error_message = "OAuth completed but no refresh token was returned by Google."
        raise ValueError(error_message)

    os.environ["GOOGLE_REFRESH_TOKEN"] = refresh_token
    set_key(".env", "GOOGLE_REFRESH_TOKEN", refresh_token)
    set_key(".env", "GOOGLE_TOKEN_ENDPOINT", GOOGLE_TOKEN_ENDPOINT)
    set_key(".env", "GOOGLE_OAUTH_SCOPE", scope)
    print("Saved GOOGLE_REFRESH_TOKEN to .env")
    return refresh_token


def ensure_google_refresh_token_from_env() -> str:
    """Return refresh token from env, or run local consent flow to obtain one."""
    refresh_token = _get_env("GOOGLE_REFRESH_TOKEN")
    if refresh_token:
        return refresh_token

    client_id = _get_env("GOOGLE_CLIENT_ID")
    client_secret = _get_env("GOOGLE_CLIENT_SECRET")
    scope = _get_google_scope_from_env()
    if not client_id or not client_secret:
        error_message = (
            "Missing GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET and no GOOGLE_REFRESH_TOKEN."
        )
        raise ValueError(error_message)
    return _ensure_google_refresh_token_via_flow(
        client_id=client_id,
        client_secret=client_secret,
        scope=scope,
    )


def get_google_credentials_from_env() -> GoogleCredentials:
    """Return refreshed Google credentials from env-backed OAuth fields."""
    client_id = _require_env("GOOGLE_CLIENT_ID")
    client_secret = _require_env("GOOGLE_CLIENT_SECRET")
    refresh_token = ensure_google_refresh_token_from_env()
    token_endpoint = _get_env("GOOGLE_TOKEN_ENDPOINT") or GOOGLE_TOKEN_ENDPOINT
    scope = _get_google_scope_from_env()

    credentials = GoogleCredentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=token_endpoint,
        client_id=client_id,
        client_secret=client_secret,
        scopes=[scope],
    )
    typed_credentials = cast("_GoogleOAuthCredentialsProtocol", credentials)
    typed_credentials.refresh(
        cast("GoogleAuthRequestProtocol", GoogleAuthRequest()),
    )
    return credentials


def get_google_access_token_from_env() -> str:
    """Get a Google access token using OAuth2 credentials from environment vars."""
    credentials = cast(
        "_GoogleOAuthCredentialsProtocol",
        get_google_credentials_from_env(),
    )
    return credentials.token or ""

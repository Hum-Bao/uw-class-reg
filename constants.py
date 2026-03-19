"""Shared constants for UW class registration system."""

from typing import Final

# API Configuration
API_BASE_URL: Final[str] = "https://register-app-api.sps.sis.uw.edu"
API_SESSION_ENDPOINT: Final[str] = f"{API_BASE_URL}/api/session"
REGISTER_BASE_URL: Final[str] = "https://register.uw.edu"
UW_IDP_URL: Final[str] = "idp.u.washington.edu"

# Cookie and Session Configuration
SESSION_COOKIE_NAME: Final[str] = "sessionId"
SESSION_COOKIE_DOMAIN: Final[str] = "register-app-api.sps.sis.uw.edu"

# HTTP Headers
DEFAULT_HEADERS: Final[dict[str, str]] = {
    "accept": "application/json, text/plain, */*",
    "origin": REGISTER_BASE_URL,
    "referer": f"{REGISTER_BASE_URL}/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

HEADER_CHECKSUM: Final[str] = "x-sis-api-checksum"
HEADER_CSRF: Final[str] = "x-csrf-token"

# Registration Configuration
DEFAULT_GRADING_SYSTEM: Final[str] = "0"
REGISTRATION_ACTION_ADD: Final[str] = "A"
REGISTRATION_ACTION_DROP: Final[str] = "D"

# Quarter Configuration
QUARTER_LABELS: Final[dict[str, str]] = {
    "1": "Winter",
    "2": "Spring",
    "3": "Summer",
    "4": "Autumn",
}

# Cache Configuration
CACHE_DIRECTORY: Final[str] = ".cache"
CACHE_FILE_NAME: Final[str] = "registration_cache.json"
DEFAULT_CACHE_MAX_AGE_SECONDS: Final[int] = 300

# Selenium Configuration
CHROME_PROFILE_DIRECTORY: Final[str] = "Default"
TRUST_BROWSER_BUTTON_ID: Final[str] = "trust-browser-button"

# Timeouts (in seconds)
SELENIUM_IMPLICIT_WAIT: Final[int] = 2
SELENIUM_2FA_TIMEOUT: Final[int] = 120
SELENIUM_PAGE_LOAD_TIMEOUT: Final[int] = 10

# Error Messages
ERROR_NOT_AUTHENTICATED: Final[str] = (
    "Client is not authenticated. Call authenticate() first."
)
ERROR_MISSING_SECURITY_TOKENS: Final[str] = (
    "Missing required security tokens in session response."
)
ERROR_EMPTY_SLN_LIST: Final[str] = "At least one SLN is required."
ERROR_EMPTY_PAYLOAD: Final[str] = "Registration payload must not be empty."
ERROR_SWAP_MISSING_SLNS: Final[str] = "Both drop SLN and add SLN are required."
ERROR_UNEXPECTED_MYPLAN_FORMAT: Final[str] = (
    "Unexpected MyPlan response format: expected a list."
)
ERROR_SESSION_ID_MISSING: Final[str] = (
    "JSON parsed successfully, but 'sessionId' key was missing."
)
ERROR_SESSION_JSON_PARSE: Final[str] = (
    "Failed to parse page text as JSON. The endpoint might not have loaded correctly."
)

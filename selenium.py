"""Selenium automation for UW authentication and session token retrieval."""

# ruff: noqa: T201

import json
import os
import re
import time
from html import unescape
from typing import Any, Protocol, cast
from urllib.parse import urljoin, urlparse

import requests
from dotenv import load_dotenv
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver as ChromeWebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait
from seleniumwire import webdriver as wire_webdriver

import UWAPI
from constants import (
    API_SESSION_ENDPOINT,
    DEFAULT_HEADERS,
    ERROR_SESSION_ID_MISSING,
    ERROR_SESSION_JSON_PARSE,
    REGISTER_BASE_URL,
    SELENIUM_2FA_TIMEOUT,
    SELENIUM_IMPLICIT_WAIT,
    SELENIUM_PAGE_LOAD_TIMEOUT,
    SESSION_COOKIE_NAME,
    TRUST_BROWSER_BUTTON_ID,
    UW_IDP_URL,
)

# Use an absolute path explicitly to avoid working directory confusion
path_userdata: str = os.getenv("APPDATA", "") + "\\HumBao\\ChromeDriver"
HTTP_OK = 200


def set_browser_options() -> Options:
    """Create and configure Chrome browser options.

    Returns:
        Configured ChromeOptions instance for browser automation.

    """
    chrome_options = Options()

    # Resolve the path to an absolute string to prevent silent failures
    chrome_options.add_argument(f"--user-data-dir={path_userdata}")
    chrome_options.add_argument("--profile-directory=Default")

    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")
    return chrome_options


def _log(*, enabled: bool, message: str) -> None:
    """Print a diagnostic message when verbose mode is enabled."""
    if enabled:
        print(message, flush=True)


def _build_hybrid_browser_options() -> Options:
    """Create browser options for the hybrid requests plus browser handoff flow."""
    chrome_options = set_browser_options()
    chrome_options.set_capability("pageLoadStrategy", "none")
    return chrome_options


def _build_http_session() -> requests.Session:
    """Create a requests session with browser-like headers."""
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    session.headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        },
    )
    return session


def _get_idp_redirect_url(
    session: requests.Session,
    session_api: str,
    relay_state: str,
) -> str:
    """Get a fresh IdP redirect URL from the API login bootstrap endpoint."""
    probe = session.get(session_api, timeout=30)
    if probe.status_code not in (200, 401):
        return ""

    api_base = probe.url.split("/api/")[0]
    login_bootstrap_api = f"{api_base}/api/login"
    response = session.get(
        login_bootstrap_api,
        params={"type": "washington.edu"},
        headers={
            "x-sis-relaystate": relay_state,
            "origin": REGISTER_BASE_URL,
            "referer": f"{REGISTER_BASE_URL}/",
            "accept": "*/*",
        },
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()
    url_value = data.get("url")
    return str(url_value) if isinstance(url_value, str) else ""


def _extract_login_payload(response: requests.Response) -> tuple[str, dict[str, str]]:
    """Extract the IdP login target and credentials payload scaffold."""
    login_page = response.text
    action_match = re.search(
        r'<form[^>]+action="([^"]+)"',
        login_page,
        flags=re.IGNORECASE,
    )
    action_url = action_match.group(1) if action_match else response.url
    login_url = (
        action_url
        if action_url.startswith("http")
        else urljoin(f"https://{UW_IDP_URL}", action_url)
    )

    execution_match = re.search(
        r'name="execution"\s+value="([^"]+)"',
        login_page,
        flags=re.IGNORECASE,
    )
    event_match = re.search(
        r'name="(_eventId(?:_proceed)?)"\s+value="([^"]*)"',
        login_page,
        flags=re.IGNORECASE,
    )

    payload: dict[str, str] = {
        "j_username": os.getenv("UW_USERNAME", ""),
        "j_password": os.getenv("UW_PASSWORD", ""),
        (event_match.group(1) if event_match else "_eventId_proceed"): (
            event_match.group(2) if event_match else ""
        ),
    }
    if execution_match:
        payload["execution"] = execution_match.group(1)

    return login_url, payload


def _walk_redirects_until_duo(
    session: requests.Session,
    start_url: str,
    max_hops: int = 20,
) -> tuple[str | None, requests.Response | None]:
    """Follow redirects manually and return first Duo URL or terminal response."""
    current_url = start_url
    response = session.get(current_url, allow_redirects=False, timeout=30)

    for _ in range(max_hops):
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location", "")
            if not location:
                return None, response

            next_url = urljoin(current_url, location)
            host = (urlparse(next_url).hostname or "").lower()
            if host.endswith("duosecurity.com"):
                return next_url, response

            current_url = next_url
            response = session.get(current_url, allow_redirects=False, timeout=30)
            continue

        return None, response

    return None, response


def _copy_selenium_cookies_to_requests(
    session: requests.Session,
    selenium_cookies: list[dict[str, Any]],
) -> None:
    """Copy Selenium cookie list back into requests.Session."""
    for cookie in selenium_cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue

        session.cookies.set(
            str(name),
            str(value),
            domain=str(cookie.get("domain", "")).lstrip("."),
            path=str(cookie.get("path", "/")),
        )


class _DuoRequestGate:
    """Intercept browser traffic and deny IdP handoff requests."""

    def __init__(self, *, verbose: bool) -> None:
        self.verbose = verbose
        self.idp_handoff_url = ""

    @staticmethod
    def _is_duo_url(url: str) -> bool:
        return bool(re.search(r"duo", url, flags=re.IGNORECASE))

    class _InterceptedRequest(Protocol):
        url: str

        def abort(self) -> None: ...

    def intercept(self, request: _InterceptedRequest) -> None:
        """Allow Duo requests and abort the IdP handoff request."""
        url = str(getattr(request, "url", ""))
        host = (urlparse(url).hostname or "").lower()

        if host == UW_IDP_URL:
            self.idp_handoff_url = url
            _log(enabled=self.verbose, message=f"[gate] DENY idp url={url[:180]}")
            _log(
                enabled=self.verbose,
                message=(f"Captured IdP handoff URL: {self.idp_handoff_url[:120]}..."),
            )
            request.abort()
            return

        if self._is_duo_url(url):
            _log(enabled=self.verbose, message=f"[gate] ALLOW duo url={url[:180]}")
            return

        _log(enabled=self.verbose, message=f"[gate] ALLOW other url={url[:180]}")


def _capture_idp_handoff_via_browser(
    handoff_url: str,
    *,
    timeout_seconds: int,
    verbose: bool,
) -> tuple[str, list[dict[str, Any]]]:
    """Use Selenium Wire to allow Duo pages and abort the first IdP callback."""
    driver = cast(
        "Any",
        wire_webdriver.Chrome(
            options=_build_hybrid_browser_options(),
            seleniumwire_options={"verify_ssl": False},
        ),
    )
    gate = _DuoRequestGate(verbose=verbose)
    driver.request_interceptor = gate.intercept

    try:
        _log(enabled=verbose, message="[gate] Starting Selenium gate")
        _log(enabled=verbose, message="[gate] Request interceptor enabled")
        _log(
            enabled=verbose,
            message=f"[gate] Navigating to handoff URL: {handoff_url[:120]}...",
        )
        driver.get(handoff_url)
        _log(enabled=verbose, message="[gate] Navigation started")

        credentials_submitted = False
        last_login_probe = 0.0
        deadline = time.time() + timeout_seconds
        while time.time() < deadline and not gate.idp_handoff_url:
            now = time.time()

            if not credentials_submitted and now - last_login_probe >= 1.0:
                last_login_probe = now
                username_fields = driver.find_elements(By.NAME, "j_username")
                password_fields = driver.find_elements(By.NAME, "j_password")
                submit_fields = driver.find_elements(By.NAME, "_eventId_proceed")
                _log(
                    enabled=verbose,
                    message=(
                        "[gate] Login form probe "
                        f"u={len(username_fields)} "
                        f"p={len(password_fields)} "
                        f"s={len(submit_fields)}"
                    ),
                )
                if username_fields and password_fields and submit_fields:
                    _log(
                        enabled=verbose,
                        message="[gate] Found credential fields, submitting",
                    )
                    username_fields[0].send_keys(os.getenv("UW_USERNAME", ""))
                    password_fields[0].send_keys(os.getenv("UW_PASSWORD", ""))
                    submit_fields[0].click()
                    credentials_submitted = True

            _log(enabled=verbose, message="[gate] Polling... no IdP handoff yet")
            time.sleep(0.25)

        if not gate.idp_handoff_url:
            message = "Timed out waiting for IdP handoff URL after Duo flow"
            raise TimeoutError(message)

        cookies = cast("list[dict[str, Any]]", driver.get_cookies())
        return gate.idp_handoff_url, cookies
    finally:
        time.sleep(1)
        driver.quit()


def _extract_client_redirect_url(current_url: str, html: str) -> str:
    """Extract client-side redirect URL from HTML if present."""
    meta_match = re.search(
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^;]+;\s*url=([^"\']+)',
        html,
        flags=re.IGNORECASE,
    )
    if meta_match:
        return urljoin(current_url, meta_match.group(1).strip())

    script_match = re.search(
        r'(?:window\.)?location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )
    if script_match:
        return urljoin(current_url, script_match.group(1).strip())

    return ""


def _complete_idp_callback_flow(
    session: requests.Session,
    callback_url: str,
    *,
    verbose: bool,
    max_hops: int = 25,
) -> str:
    """Complete IdP and SAML return flow using requests only."""
    current_url = callback_url
    _log(
        enabled=verbose,
        message=f"[requests] Starting callback flow at: {current_url[:140]}",
    )
    response = session.get(current_url, allow_redirects=False, timeout=30)

    for _ in range(max_hops):
        _log(
            enabled=verbose,
            message=f"[requests] {response.status_code} {current_url[:140]}",
        )

        if response.is_redirect or response.is_permanent_redirect:
            next_url = urljoin(current_url, response.headers.get("Location", ""))
            _log(
                enabled=verbose,
                message=f"[requests] redirect -> {next_url[:140]}",
            )
            current_url = next_url
            response = session.get(current_url, allow_redirects=False, timeout=30)
            continue

        html = response.text or ""
        form_match = re.search(
            r'<form[^>]+action="([^"]+)"[^>]*>(.*?)</form>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if form_match:
            action_url = urljoin(current_url, unescape(form_match.group(1)))
            form_html = form_match.group(2)
            fields = {
                unescape(name): unescape(value)
                for name, value in re.findall(
                    r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"',
                    form_html,
                    flags=re.IGNORECASE,
                )
            }
            _log(
                enabled=verbose,
                message=f"[requests] form POST -> {action_url[:140]}",
            )
            response = session.post(
                action_url,
                data=fields,
                allow_redirects=False,
                timeout=30,
            )
            current_url = action_url
            continue

        client_redirect_url = _extract_client_redirect_url(current_url, html)
        if client_redirect_url:
            _log(
                enabled=verbose,
                message=f"[requests] client redirect -> {client_redirect_url[:140]}",
            )
            current_url = client_redirect_url
            response = session.get(current_url, allow_redirects=False, timeout=30)
            continue

        return current_url

    return current_url


def _fetch_authenticated_session_response(
    session: requests.Session,
    session_api: str,
    relay_state: str,
    *,
    verbose: bool,
    timeout_seconds: int = 30,
) -> requests.Response | None:
    """Prime register frontend and poll until session authentication succeeds."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            session.get(REGISTER_BASE_URL, timeout=30)
            session.get(f"{REGISTER_BASE_URL}/register/", timeout=30)
            response = session.get(
                session_api,
                headers={
                    **DEFAULT_HEADERS,
                    "x-sis-relaystate": relay_state,
                },
                timeout=30,
            )
            _log(
                enabled=verbose,
                message=f"[requests] session probe -> {response.status_code}",
            )
            if response.status_code == HTTP_OK:
                return response
        except requests.RequestException as error:
            _log(
                enabled=verbose,
                message=f"[requests] session probe error: {error}",
            )

        time.sleep(2)

    return None


def _extract_session_token(
    session: requests.Session,
    response: requests.Response,
) -> str:
    """Extract a likely session token from cookies or the session payload."""
    session_token = (
        session.cookies.get(SESSION_COOKIE_NAME)
        or session.cookies.get("sessionid")
        or session.cookies.get("JSESSIONID")
        or session.cookies.get("__Host-JSESSIONID")
    )
    if session_token:
        return session_token

    data = response.json()
    return str(data.get("sessionId", ""))


def _validate_session_token(session_id: str, *, verbose: bool) -> str:
    """Validate a session token using the same UWAPI path as the main app."""
    if not session_id:
        return ""

    validation_client = UWAPI.UWAPI(session_id=session_id)
    if validation_client.authenticate():
        _log(
            enabled=verbose,
            message=(
                f"✓ UWAPI authenticated as Student #{validation_client.student_number}"
            ),
        )
        return session_id

    _log(
        enabled=verbose,
        message="❌ Session token extracted but UWAPI authentication failed",
    )
    return ""


def _looks_like_idp_login_response(response: requests.Response) -> bool:
    """Return True when the response looks like the IdP sign-in page."""
    return "sign-in" in response.text.lower() and "j_username" in response.text


def _handle_duo_mfa_handoff(
    session: requests.Session,
    duo_url: str,
    relay_state: str,
    *,
    verbose: bool,
) -> requests.Response | None:
    """Run Duo in Selenium, finish the callback in requests, and probe the API."""
    _log(
        enabled=verbose,
        message="⚠ MFA challenge detected at Duo. Switching to Selenium...",
    )
    idp_handoff_url, selenium_cookies = _capture_idp_handoff_via_browser(
        duo_url,
        timeout_seconds=SELENIUM_2FA_TIMEOUT + 60,
        verbose=verbose,
    )
    if not idp_handoff_url:
        _log(
            enabled=verbose,
            message="❌ Selenium MFA handoff failed before IdP return",
        )
        return None

    _copy_selenium_cookies_to_requests(session, selenium_cookies)
    final_callback_url = _complete_idp_callback_flow(
        session,
        idp_handoff_url,
        verbose=verbose,
    )
    _log(
        enabled=verbose,
        message=f"[requests] Final callback landing URL: {final_callback_url[:140]}",
    )

    session_response = _fetch_authenticated_session_response(
        session,
        API_SESSION_ENDPOINT,
        relay_state,
        verbose=verbose,
    )
    if session_response is not None:
        return session_response

    _log(
        enabled=verbose,
        message="Session still shows next=idp; refreshing login bootstrap once...",
    )
    refreshed_idp = _get_idp_redirect_url(session, API_SESSION_ENDPOINT, relay_state)
    if not refreshed_idp:
        _log(
            enabled=verbose,
            message="❌ Session remained unauthenticated after Selenium MFA",
        )
        return None

    session_response = _fetch_authenticated_session_response(
        session,
        API_SESSION_ENDPOINT,
        relay_state,
        verbose=verbose,
    )
    if session_response is None:
        _log(
            enabled=verbose,
            message="❌ Session remained unauthenticated after re-bootstrap",
        )

    return session_response


def get_fresh_session_token() -> str:
    """Use Selenium to log in and extract the underlying API session cookie.

    Returns:
        Session token string if successful, empty string otherwise.

    """
    options = set_browser_options()
    driver = cast("Any", ChromeWebDriver(options=options))

    try:
        print("Opening UW Login...")
        driver.get(REGISTER_BASE_URL)
        time.sleep(SELENIUM_IMPLICIT_WAIT)

        # Smart Wait: Check if the persistent profile bypassed the login
        if UW_IDP_URL in driver.current_url:
            print(
                (
                    "First run or session expired. Please log in and complete "
                    "2FA in the browser window."
                ),
            )

            # Find and enter username and password
            element = driver.find_element(By.NAME, "j_username")
            element.send_keys(os.getenv("UW_USERNAME", ""))
            element = driver.find_element(By.NAME, "j_password")
            element.send_keys(os.getenv("UW_PASSWORD", ""))
            element = driver.find_element(By.NAME, "_eventId_proceed")
            element.click()
            # Sleep to allow page to load
            time.sleep(3)
            if len(driver.find_elements(By.ID, TRUST_BROWSER_BUTTON_ID)) > 0:
                WebDriverWait(driver, SELENIUM_2FA_TIMEOUT).until(
                    expected_conditions.element_to_be_clickable(
                        (By.ID, TRUST_BROWSER_BUTTON_ID),
                    ),
                ).click()
                print("Clicked trust button")

            # Wait until we are back on the register domain and the UW SSO domain is gone.
            WebDriverWait(driver, SELENIUM_2FA_TIMEOUT).until(
                lambda d: (
                    "register.uw.edu" in d.current_url
                    and UW_IDP_URL not in d.current_url
                ),
            )
        else:
            print("Persistent session found! Skipping manual login.")

        # Ensure the dashboard has fully loaded
        WebDriverWait(driver, SELENIUM_2FA_TIMEOUT).until(
            expected_conditions.url_contains("register.uw.edu"),
        )
        print("Login detected. Fetching API session cookie...")

        driver.get(API_SESSION_ENDPOINT)

        WebDriverWait(driver, SELENIUM_PAGE_LOAD_TIMEOUT).until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        page_text = str(driver.find_element(By.TAG_NAME, "body").text)

        try:
            session_data = json.loads(page_text)
            if not isinstance(session_data, dict):
                raise TypeError(ERROR_SESSION_JSON_PARSE)

            typed_session_data = cast("dict[str, object]", session_data)
            session_token = typed_session_data.get("sessionId")

            if not isinstance(session_token, str) or not session_token:
                raise ValueError(ERROR_SESSION_ID_MISSING)

        except json.JSONDecodeError as decode_error:
            raise ValueError(ERROR_SESSION_JSON_PARSE) from decode_error
        else:
            return session_token

    finally:
        # Give Chrome a moment to sync its cookie database to disk before killing it
        time.sleep(1)
        driver.quit()


def get_fresh_session_token_hybrid(*, verbose: bool = True) -> str:
    """Authenticate mostly with requests and use Selenium only for Duo MFA handoff.

    Returns:
        A validated session token if authentication succeeds, otherwise an empty string.

    """
    load_dotenv()

    if not os.getenv("UW_USERNAME") or not os.getenv("UW_PASSWORD"):
        _log(enabled=verbose, message="Missing UW_USERNAME or UW_PASSWORD env vars")
        return ""

    session = _build_http_session()
    relay_state = f"{REGISTER_BASE_URL}/register/"
    session_response: requests.Response | None = None

    try:
        session.get(f"{REGISTER_BASE_URL}/", timeout=30)

        _log(enabled=verbose, message="Getting SAML redirect URL...")
        idp_url = _get_idp_redirect_url(session, API_SESSION_ENDPOINT, relay_state)
        if not idp_url:
            _log(enabled=verbose, message="❌ No IdP URL in response")
            return ""

        _log(enabled=verbose, message="✓ Got IdP URL")
        _log(enabled=verbose, message="Getting login form...")
        login_page_response = session.get(idp_url, timeout=30)
        login_page_response.raise_for_status()

        login_url, credentials = _extract_login_payload(login_page_response)
        _log(enabled=verbose, message="Submitting credentials...")
        response = session.post(
            login_url,
            data=credentials,
            allow_redirects=False,
            timeout=30,
        )
        response.raise_for_status()

        duo_url = None
        if response.is_redirect or response.is_permanent_redirect:
            first_hop = urljoin(login_url, response.headers.get("Location", ""))
            duo_url, terminal_response = _walk_redirects_until_duo(session, first_hop)
        else:
            terminal_response = response

        if duo_url:
            session_response = _handle_duo_mfa_handoff(
                session,
                duo_url,
                relay_state,
                verbose=verbose,
            )
            if session_response is None:
                return ""
        elif terminal_response is not None and _looks_like_idp_login_response(
            terminal_response,
        ):
            _log(
                enabled=verbose,
                message="❌ Credential step returned to IdP login page",
            )
            return ""

        _log(enabled=verbose, message="Validating session...")
        final_response = session_response or session.get(
            API_SESSION_ENDPOINT,
            headers={
                **DEFAULT_HEADERS,
                "x-sis-relaystate": relay_state,
            },
            timeout=30,
        )
        if final_response.status_code != HTTP_OK:
            _log(enabled=verbose, message="❌ Still not authenticated")
            return ""

        session_token = _extract_session_token(session, final_response)
        if session_token:
            _log(
                enabled=verbose,
                message=f"✓ Got session token: {session_token[:20]}...",
            )
        else:
            _log(
                enabled=verbose,
                message="⚠ Token not in cookies, checking response...",
            )
            _log(enabled=verbose, message=f"Session response: {final_response.json()}")

        return _validate_session_token(session_token, verbose=verbose)
    except requests.RequestException as error:
        _log(enabled=verbose, message=f"❌ Request failed: {error}")
        return ""

"""Scheduling workflows for time-based and email-triggered registration."""

# ruff: noqa: T201, I001

import datetime
import os
import secrets
import subprocess
import time
from collections.abc import Callable
from typing import Any, cast

from dotenv import set_key

from constants import SESSION_COOKIE_DOMAIN, SESSION_COOKIE_NAME
import mail
import UWAPI
import uw_selenium

SCHEDULE_STATUS_UPDATE_INTERVAL = 60  # seconds
EMAIL_POLL_INTERVAL_SECONDS = 15
SESSION_CHECK_MIN_SECONDS = 30 * 60
SESSION_CHECK_MAX_SECONDS = 60 * 60
NOTIFY_UW_SENDER_MARKERS = [
    "notify-noreply@uw.edu",
    "us-west-2.amazonses.com",
]

QuarterSelector = Callable[[str], tuple[str, str, str] | None]
RegisterFromMyPlan = Callable[[UWAPI.UWAPI, str], None]
RegisterAddCoursesWithRetry = Callable[
    [UWAPI.UWAPI, str, list[str], dict[str, str]],
    None,
]


def _clear_console() -> None:
    """Clear terminal output for step-by-step scheduling status screens."""
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "cls"], check=False)  # noqa: S607
    else:
        subprocess.run(["clear"], check=False)  # noqa: S607


class _SessionMonitor:
    """Periodically validates session and refreshes token when expired."""

    def __init__(self, client: UWAPI.UWAPI) -> None:
        self._client = client
        self._next_check_epoch = time.time() + self._next_interval_seconds()

    @staticmethod
    def _next_interval_seconds() -> int:
        span = SESSION_CHECK_MAX_SECONDS - SESSION_CHECK_MIN_SECONDS + 1
        return SESSION_CHECK_MIN_SECONDS + secrets.randbelow(span)

    def maybe_refresh(self) -> bool:
        """Check session on randomized cadence and refresh if authentication fails."""
        now = time.time()
        if now < self._next_check_epoch:
            return True

        self._next_check_epoch = now + self._next_interval_seconds()
        print("\nChecking session token health...")

        if self._client.authenticate():
            print("Session token is still valid.")
            return True

        print("Session token appears expired. Attempting re-authentication...")
        new_session_id = uw_selenium.get_fresh_session_token_hybrid(verbose=True)
        if not new_session_id:
            print("Could not refresh session token.")
            return False

        cookie_jar = cast("Any", self._client.session.cookies)
        cookie_jar.set(
            SESSION_COOKIE_NAME,
            new_session_id,
            domain=SESSION_COOKIE_DOMAIN,
        )

        os.environ["UW_SESSION_ID"] = new_session_id
        set_key(
            dotenv_path=".env",
            key_to_set="UW_SESSION_ID",
            value_to_set=new_session_id,
        )

        if self._client.authenticate():
            print("Session refreshed and re-authenticated successfully.")
            return True

        print("Failed to re-authenticate even after token refresh.")
        return False


def _parse_scheduled_time(time_input: str) -> datetime.datetime | None:
    """Parse user time input and return a datetime object for scheduling."""
    formats = ["%H:%M:%S", "%H:%M"]
    parsed_time = None

    for fmt in formats:
        try:
            parsed_time = datetime.datetime.strptime(  # noqa: DTZ007
                time_input.strip(),
                fmt,
            ).time()
            break
        except ValueError:
            continue

    if parsed_time is None:
        return None

    now = datetime.datetime.now()  # noqa: DTZ005
    scheduled = now.replace(
        hour=parsed_time.hour,
        minute=parsed_time.minute,
        second=parsed_time.second,
        microsecond=0,
    )

    # If the scheduled time is in the past, schedule for tomorrow.
    if scheduled < now:
        scheduled += datetime.timedelta(days=1)

    return scheduled


def _wait_until_scheduled_time(
    scheduled_time: datetime.datetime,
    *,
    session_monitor: _SessionMonitor,
) -> bool:
    """Wait until the scheduled time, displaying countdown."""
    now = datetime.datetime.now()  # noqa: DTZ005
    wait_seconds = (scheduled_time - now).total_seconds()

    if wait_seconds <= 0:
        print("Scheduled time is already in the past.")
        return True

    time_formatted = scheduled_time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\nScheduled registration for {time_formatted}")
    print(f"Waiting {int(wait_seconds)} seconds...")

    while True:
        if not session_monitor.maybe_refresh():
            print("Stopping scheduled wait due to failed re-authentication.")
            return False

        now = datetime.datetime.now()  # noqa: DTZ005
        remaining = (scheduled_time - now).total_seconds()

        if remaining <= 0:
            print("\nScheduled time reached! Executing registration...")
            return True

        if remaining <= SCHEDULE_STATUS_UPDATE_INTERVAL:
            print(f"Executing in {int(remaining)} seconds...", end="\r")
            time.sleep(1)
        else:
            minutes_remaining = int(remaining // 60)
            seconds_remaining = int(remaining % 60)
            print(
                f"Time until registration: {minutes_remaining}m {seconds_remaining}s",
                end="\r",
            )
            time.sleep(5)


def _collect_scheduled_registration_data() -> dict[str, Any] | None:
    """Collect registration method and data for scheduled/triggered runs."""
    print("\nSelect registration method:")
    print("1. Import from MyPlan")
    print("2. Enter SLN(s)")
    method_choice = input("Enter option number (1-2): ").strip()

    if method_choice == "1":
        return {"method": "myplan"}
    if method_choice == "2":
        raw_slns = input(
            "Enter SLNs separated by commas (e.g. 12345,23456): ",
        ).strip()
        slns = [sln.strip() for sln in raw_slns.split(",") if sln.strip()]
        if not slns:
            print("No SLNs entered.")
            return None
        return {"method": "manual_slns", "slns": slns}

    print("Invalid option. Please enter 1 or 2.")
    return None


def _execute_registration_data(
    *,
    client: UWAPI.UWAPI,
    quarter_code: str,
    registration_data: dict[str, Any],
    register_from_myplan: RegisterFromMyPlan,
    register_add_courses_with_retry: RegisterAddCoursesWithRetry,
) -> None:
    """Execute registration using pre-collected registration data."""
    if registration_data["method"] == "myplan":
        register_from_myplan(client, quarter_code)
    elif registration_data["method"] == "manual_slns":
        slns = cast("list[str]", registration_data["slns"])
        sln_labels = {sln: f"SLN {sln}" for sln in slns}
        register_add_courses_with_retry(client, quarter_code, slns, sln_labels)


def handle_schedule_registration(
    *,
    client: UWAPI.UWAPI,
    select_current_year_quarter: QuarterSelector,
    register_from_myplan: RegisterFromMyPlan,
    register_add_courses_with_retry: RegisterAddCoursesWithRetry,
) -> None:
    """Handle scheduled course registration process."""
    selected_quarter = select_current_year_quarter("scheduled registration")
    if selected_quarter is None:
        return

    quarter_choice, quarter_name, quarter_code = selected_quarter
    print(f"Selected Quarter {quarter_choice} ({quarter_name}) - {quarter_code}")

    print("\nEnter the time you want to register for classes.")
    print("Format: HH:MM or HH:MM:SS (e.g., 14:30 or 14:30:45)")
    time_input = input("Enter scheduled time: ").strip()

    scheduled_time = _parse_scheduled_time(time_input)
    if scheduled_time is None:
        print("Invalid time format. Please use HH:MM or HH:MM:SS.")
        return

    registration_data = _collect_scheduled_registration_data()
    if registration_data is None:
        return

    session_monitor = _SessionMonitor(client)
    if not _wait_until_scheduled_time(
        scheduled_time,
        session_monitor=session_monitor,
    ):
        return

    _execute_registration_data(
        client=client,
        quarter_code=quarter_code,
        registration_data=registration_data,
        register_from_myplan=register_from_myplan,
        register_add_courses_with_retry=register_add_courses_with_retry,
    )


def handle_schedule_registration_on_email(
    *,
    client: UWAPI.UWAPI,
    select_current_year_quarter: QuarterSelector,
    register_add_courses_with_retry: RegisterAddCoursesWithRetry,
) -> None:
    """Handle email-triggered registration with Gmail API or IMAP polling."""
    selected_quarter = select_current_year_quarter("email-triggered registration")
    if selected_quarter is None:
        return

    quarter_choice, quarter_name, quarter_code = selected_quarter
    _clear_console()
    print("Email Trigger Registration")
    print(f"Selected Quarter {quarter_choice} ({quarter_name}) - {quarter_code}")
    print("\nChoose email trigger method:")
    print("1. Gmail API")
    print("2. Other (IMAP)")
    print("0. Back")
    method_choice = input("Enter option number (0-2): ").strip()

    if method_choice == "0":
        return
    if method_choice == "1":
        _handle_email_trigger_gmail_api(
            client=client,
            quarter_code=quarter_code,
            quarter_choice=quarter_choice,
            quarter_name=quarter_name,
            register_add_courses_with_retry=register_add_courses_with_retry,
        )
        return
    if method_choice == "2":
        _handle_email_trigger_imap(
            client=client,
            quarter_code=quarter_code,
            quarter_choice=quarter_choice,
            quarter_name=quarter_name,
            register_add_courses_with_retry=register_add_courses_with_retry,
        )
        return

    print("Invalid option. Please enter 0, 1, or 2.")


def _handle_email_trigger_gmail_api(
    *,
    client: UWAPI.UWAPI,
    quarter_code: str,
    quarter_choice: str,
    quarter_name: str,
    register_add_courses_with_retry: RegisterAddCoursesWithRetry,
) -> None:
    """Run email-trigger registration using Gmail API polling."""
    _clear_console()
    print("Email Trigger Registration Setup")
    print(f"Selected Quarter {quarter_choice} ({quarter_name}) - {quarter_code}")
    print("\nPreparing Gmail API validation...")

    username = os.getenv("IMAP_USERNAME", "").strip()
    if not username:
        print("Missing IMAP_USERNAME (used as Gmail address for API mode).")
        return

    print("\nUsing Gmail API settings from .env")
    print(f"Gmail user: {username}")
    print("Gmail API auth mode: oauth2")

    print("\nValidating Gmail API credentials...")
    if not mail.validate_gmail_api_credentials(username=username):
        print("Cannot start listener until Gmail API credentials are valid.")
        return

    _clear_console()

    session_monitor = _SessionMonitor(client)
    extracted_sln = mail.wait_for_notifyuw_sln_via_gmail_api(
        username=username,
        sender_markers=NOTIFY_UW_SENDER_MARKERS,
        poll_interval_seconds=EMAIL_POLL_INTERVAL_SECONDS,
        maintenance_callback=session_monitor.maybe_refresh,
    )
    if not extracted_sln:
        return

    sln_labels = {extracted_sln: f"SLN {extracted_sln} (Notify.UW trigger)"}
    register_add_courses_with_retry(
        client,
        quarter_code,
        [extracted_sln],
        sln_labels,
    )


def _handle_email_trigger_imap(
    *,
    client: UWAPI.UWAPI,
    quarter_code: str,
    quarter_choice: str,
    quarter_name: str,
    register_add_courses_with_retry: RegisterAddCoursesWithRetry,
) -> None:
    """Run email-trigger registration using IMAP polling."""
    _clear_console()
    print("Email Trigger Registration Setup")
    print(f"Selected Quarter {quarter_choice} ({quarter_name}) - {quarter_code}")
    print("\nPreparing IMAP validation...")

    imap_server = os.getenv("IMAP_SERVER", "imap.gmail.com").strip()
    imap_username = os.getenv("IMAP_USERNAME", "").strip()
    imap_password = os.getenv("IMAP_PASSWORD", "").strip()
    auth_mode = os.getenv("IMAP_AUTH_MODE", "password").strip().lower()
    use_google_oauth2 = auth_mode == "oauth2"

    if not imap_server or not imap_username:
        print("Missing IMAP server or username/email.")
        print("Set IMAP_SERVER and IMAP_USERNAME in .env.")
        return

    if not use_google_oauth2 and not imap_password:
        print("Missing IMAP password for password auth mode.")
        print("Set IMAP_PASSWORD in .env or set IMAP_AUTH_MODE=oauth2.")
        return

    print("\nUsing IMAP settings from .env")
    print(f"IMAP server: {imap_server}")
    print(f"IMAP username: {imap_username}")
    print(f"IMAP auth mode: {'oauth2' if use_google_oauth2 else 'password'}")

    print("\nValidating IMAP credentials...")
    if not mail.validate_imap_credentials(
        imap_server=imap_server,
        username=imap_username,
        password=imap_password,
        use_google_oauth2=use_google_oauth2,
    ):
        print("Cannot start listener until IMAP credentials are valid.")
        return

    _clear_console()

    session_monitor = _SessionMonitor(client)

    extracted_sln = mail.wait_for_notifyuw_sln(
        imap_server=imap_server,
        username=imap_username,
        password=imap_password,
        sender_markers=NOTIFY_UW_SENDER_MARKERS,
        poll_interval_seconds=EMAIL_POLL_INTERVAL_SECONDS,
        maintenance_callback=session_monitor.maybe_refresh,
        use_google_oauth2=use_google_oauth2,
    )
    if not extracted_sln:
        return

    sln_labels = {extracted_sln: f"SLN {extracted_sln} (Notify.UW trigger)"}
    register_add_courses_with_retry(
        client,
        quarter_code,
        [extracted_sln],
        sln_labels,
    )

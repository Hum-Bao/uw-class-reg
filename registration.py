"""Registration logic and data utilities for UW class registration."""

# ruff: noqa: T201

import datetime
import html
import re
from typing import Any, cast

import UWAPI
from constants import QUARTER_LABELS

TIME_FORMAT_LENGTH = 6
WINTER_QUARTER_END_MONTH = 3
SPRING_QUARTER_END_MONTH = 6
SUMMER_QUARTER_END_MONTH = 9


def detect_current_quarter_code(reference_date: datetime.date | None = None) -> str:
    """Return current quarter code in YYYYQ format."""
    if reference_date is None:
        reference_date = datetime.datetime.now(tz=datetime.timezone.utc).date()

    month = reference_date.month
    if month <= WINTER_QUARTER_END_MONTH:
        quarter = 1
    elif month <= SPRING_QUARTER_END_MONTH:
        quarter = 2
    elif month <= SUMMER_QUARTER_END_MONTH:
        quarter = 3
    else:
        quarter = 4

    return f"{reference_date.year}{quarter}"


def select_current_year_quarter(action_label: str) -> tuple[str, str, str] | None:
    """Prompt user to select a quarter for the current year."""
    current_year = str(datetime.datetime.now(tz=datetime.timezone.utc).year)
    print(f"Select a quarter for {action_label} in {current_year}:")
    print("1. Quarter 1 (Winter)")
    print("2. Quarter 2 (Spring)")
    print("3. Quarter 3 (Summer)")

    quarter_choice = input("Enter quarter number (1-3): ").strip()
    if quarter_choice not in QUARTER_LABELS:
        print("Invalid quarter choice. Please enter 1, 2, or 3.")
        return None

    quarter_code = f"{current_year}{quarter_choice}"
    quarter_name = QUARTER_LABELS[quarter_choice]
    return quarter_choice, quarter_name, quarter_code


def _typed_registration_items(registrations_raw: object) -> list[dict[str, Any]]:
    """Normalize a raw registrations payload into a typed dict list."""
    if not isinstance(registrations_raw, list):
        return []

    registration_items = cast("list[object]", registrations_raw)
    return [
        cast("dict[str, Any]", registration)
        for registration in registration_items
        if isinstance(registration, dict)
    ]


def _registration_section(registration: dict[str, Any]) -> dict[str, Any]:
    """Return the typed section payload for a registration item."""
    section_raw = registration.get("section", {})
    if not isinstance(section_raw, dict):
        return {}
    return cast("dict[str, Any]", section_raw)


def _course_label(section: dict[str, Any]) -> str:
    """Build a short course label from a registration section."""
    course_abbreviation = str(section.get("courseAbbreviation", "")).strip()
    course_number = str(section.get("courseNumber", "")).strip()
    section_id = str(section.get("sectionId", "")).strip()
    return f"{course_abbreviation} {course_number} {section_id}".strip()


def _registration_display_line(registration: dict[str, Any]) -> str:
    """Build a single-line registration display string."""
    section = _registration_section(registration)
    course_title = str(section.get("courseTitle", "")).strip()
    sln = str(section.get("sln", "")).strip()
    return f"{_course_label(section)} - {course_title} (SLN: {sln})"


def _format_registration_start_time(raw_time: str | None) -> str:
    """Format HHMMSS registration start time into HH:MM:SS."""
    if not raw_time:
        return "Not found"

    cleaned = raw_time.strip()
    if len(cleaned) != TIME_FORMAT_LENGTH or not cleaned.isdigit():
        return cleaned

    return f"{cleaned[0:2]}:{cleaned[2:4]}:{cleaned[4:6]}"


def _extract_myplan_registration_items(
    myplan_payload: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Extract registerable items from MyPlan payload."""
    extracted: list[dict[str, str]] = []
    seen_codes: set[str] = set()

    for term_entry in myplan_payload:
        planned_list = term_entry.get("plannedList", [])
        if not isinstance(planned_list, list):
            continue
        planned_items = cast("list[object]", planned_list)

        for planned_item_raw in planned_items:
            if not isinstance(planned_item_raw, dict):
                continue
            planned_item = cast("dict[str, Any]", planned_item_raw)

            plan_activities = planned_item.get("planActivities", [])
            if not isinstance(plan_activities, list):
                continue
            activity_items = cast("list[object]", plan_activities)

            for activity_raw in activity_items:
                if not isinstance(activity_raw, dict):
                    continue
                activity = cast("dict[str, Any]", activity_raw)

                registration_code = str(activity.get("registrationCode", "")).strip()
                if not registration_code or registration_code in seen_codes:
                    continue

                seen_codes.add(registration_code)
                extracted.append(
                    {
                        "registrationCode": registration_code,
                        "courseCode": str(activity.get("courseCode", "")).strip(),
                        "instructor": str(activity.get("instructor", "")).strip(),
                        "credits": str(activity.get("credits", "")).strip(),
                        "enrollStatus": str(activity.get("enrollStatus", "")).strip(),
                    },
                )

    return extracted


def _clean_message_text(raw_text: str) -> str:
    """Convert HTML-rich message text into readable plain text."""
    text = html.unescape(raw_text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s*More information\.\.\.\s*$", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _print_message_list(messages: object, indent: str = "") -> None:
    """Print a list of registration messages."""
    if not isinstance(messages, list):
        return

    message_items = cast("list[object]", messages)
    for message_raw in message_items:
        if not isinstance(message_raw, dict):
            continue
        message = cast("dict[str, Any]", message_raw)
        message_text = _clean_message_text(str(message.get("messageText", "")))
        if message_text:
            print(f"{indent}- {message_text}")


def _is_success_action(action: object) -> bool:
    """Return True when an API action string represents success."""
    action_text = str(action).strip().lower()
    return action_text in {"success", "succeeded", "ok"}


def _is_failure_action(action: object) -> bool:
    """Return True when an API action string represents failure."""
    action_text = str(action).strip().lower()
    return action_text in {"fail", "failed", "error"}


def _change_succeeded(
    change_dict: dict[str, Any],
    *,
    overall_next_action: object,
) -> bool:
    """Resolve per-class success from change action, messages, and overall status."""
    change_next_action = change_dict.get("nextAction", "")
    if str(change_next_action).strip():
        if _is_success_action(change_next_action):
            return True
        if _is_failure_action(change_next_action):
            return False

    change_messages = change_dict.get("messages", [])
    if isinstance(change_messages, list):
        change_message_items = cast("list[object]", change_messages)
        if change_message_items:
            return False

    return not _is_failure_action(overall_next_action)


def _print_registration_response(
    response: object,
    sln_labels: dict[str, str] | None = None,
) -> None:
    """Print registration API response in a cleaner, per-class format."""
    if not isinstance(response, dict):
        print("Registration response:")
        print(response)
        return

    response_dict = cast("dict[str, Any]", response)
    sln_labels = sln_labels or {}
    next_action = response_dict.get("nextAction", "unknown")
    trans_msg = str(response_dict.get("transMsg", "")).strip()
    overall_messages = response_dict.get("messages", [])
    registration_changes = response_dict.get("registrationChanges", [])

    print("Registration Result:")
    print(f"Overall status: {next_action}")
    if trans_msg:
        print(f"Transaction message: {_clean_message_text(trans_msg)}")

    if isinstance(overall_messages, list) and overall_messages:
        print("General messages:")
        _print_message_list(cast("list[object]", overall_messages))

    if not isinstance(registration_changes, list) or not registration_changes:
        print("No per-class registration changes were returned.")
        return

    print("\nPer-class status:")
    registration_change_items = cast("list[object]", registration_changes)
    change_items = [
        cast("dict[str, Any]", change)
        for change in registration_change_items
        if isinstance(change, dict)
    ]
    for index, change_dict in enumerate(change_items, start=1):
        section = _registration_section(change_dict)
        sln = str(section.get("sln", "")).strip()
        change_messages = change_dict.get("messages", [])
        if isinstance(change_messages, list):
            change_message_items = cast("list[object]", change_messages)
        else:
            change_message_items = []

        success = _change_succeeded(
            change_dict,
            overall_next_action=next_action,
        )

        item_label = sln_labels.get(sln, f"SLN {sln}" if sln else "Unknown SLN")
        status = "SUCCESS" if success else "FAILED"
        print(f"{index}. {item_label} - {status}")
        _print_message_list(change_message_items, indent="   ")


def _print_current_registration_summary(reg_data: dict[str, Any]) -> None:
    """Print formatted registration summary."""
    registrations = reg_data.get("registrations", [])
    registration_start_time = _format_registration_start_time(
        reg_data.get("registrationStartTime"),
    )
    ready_to_register = reg_data.get("isReadyToRegister")
    term = reg_data.get("term", {})

    term_year = term.get("year", "?")
    term_quarter_name = term.get("quarterName", "")
    term_quarter = term.get("quarter", "?")

    print("Registration Info:")
    print(f"Term: {term_year} {term_quarter_name} (quarter {term_quarter})")
    if not registrations:
        print("No registrations found.")
    else:
        for index, registration in enumerate(registrations, start=1):
            section = _registration_section(registration)
            course_title = section.get("courseTitle", "")
            sln = section.get("sln", "")
            meeting_days = registration.get("meetingDays", "")
            meeting_time = registration.get("meetingTime", "")
            instructor = registration.get("Instructor", "")
            course_credits = registration.get("credits", "")

            print(f"{index}. {_course_label(section)} - {course_title}")
            print(
                f"   SLN: {sln} | Credits: {course_credits} | "
                f"Meeting: {meeting_days} {meeting_time} | Professor: {instructor}",
            )

    print("\nRegistration Opens:")
    print(registration_start_time)
    print("\nReady To Register:")
    print("Yes" if ready_to_register is True else "No")


def _print_data_source(source: str) -> None:
    """Print the source used for registration data."""
    print(f"Data source: {source}")


def _extract_failed_slns_from_response(response: object) -> set[str]:
    """Extract SLNs that failed from a registration API response."""
    if not isinstance(response, dict):
        return set()

    response_dict = cast("dict[str, Any]", response)
    failed_slns: set[str] = set()
    next_action = response_dict.get("nextAction", "unknown")
    registration_changes = response_dict.get("registrationChanges", [])
    if not isinstance(registration_changes, list):
        return failed_slns

    for change_raw in cast("list[object]", registration_changes):
        if not isinstance(change_raw, dict):
            continue

        change_dict = cast("dict[str, Any]", change_raw)
        section = _registration_section(change_dict)
        sln = str(section.get("sln", "")).strip()
        if sln and not _change_succeeded(
            change_dict,
            overall_next_action=next_action,
        ):
            failed_slns.add(sln)

    return failed_slns


def register_add_courses_with_retry(
    client: UWAPI.UWAPI,
    quarter_code: str,
    slns: list[str],
    sln_labels: dict[str, str],
) -> None:
    """Register SLNs and retry once without any failed classes."""
    result = client.add_courses(quarter_code=quarter_code, slns=slns)
    _print_registration_response(result, sln_labels=sln_labels)

    failed_slns = _extract_failed_slns_from_response(result)
    if not failed_slns:
        return

    retry_slns = [sln for sln in slns if sln not in failed_slns]
    if not retry_slns:
        print("\nNo retry candidates remain after excluding failed courses.")
        return

    failed_labels = [sln_labels.get(sln, f"SLN {sln}") for sln in failed_slns]
    print("\nDetected failed courses in batch. Retrying immediately without these:")
    for label in failed_labels:
        print(f"- {label}")

    retry_labels = {sln: sln_labels.get(sln, f"SLN {sln}") for sln in retry_slns}
    retry_result = client.add_courses(quarter_code=quarter_code, slns=retry_slns)
    print("\nRetry Result:")
    _print_registration_response(retry_result, sln_labels=retry_labels)


def register_with_manual_slns(client: UWAPI.UWAPI, quarter_code: str) -> None:
    """Register courses by prompting user for SLNs."""
    raw_slns = input("Enter SLNs separated by commas (e.g. 12345,23456): ").strip()
    slns = [sln.strip() for sln in raw_slns.split(",") if sln.strip()]

    if not slns:
        print("No SLNs entered.")
        return

    sln_labels = {sln: f"SLN {sln}" for sln in slns}
    register_add_courses_with_retry(
        client=client,
        quarter_code=quarter_code,
        slns=slns,
        sln_labels=sln_labels,
    )


def register_from_myplan(client: UWAPI.UWAPI, quarter_code: str) -> None:
    """Register courses by importing from MyPlan."""
    myplan_payload = client.get_myplan_terms(
        term_id=quarter_code,
        validate=True,
        include_academic_history=True,
    )
    register_items = _extract_myplan_registration_items(myplan_payload)

    if not register_items:
        print("No registerable courses found in MyPlan for this term.")
        return

    print("MyPlan courses to import:")
    for index, item in enumerate(register_items, start=1):
        print(
            f"{index}. {item['courseCode']} | SLN: {item['registrationCode']} | "
            f"Credits: {item['credits']} | Status: {item['enrollStatus']} | "
            f"Professor: {item['instructor']}",
        )

    extra_sln_input = input(
        "\nOptional: enter additional SLNs to include, "
        "separated by commas (or press Enter to skip): ",
    ).strip()
    extra_slns = [sln.strip() for sln in extra_sln_input.split(",") if sln.strip()]

    if extra_slns:
        print("Additional SLNs to include:")
        for sln in extra_slns:
            print(f"- SLN {sln}")

    confirm = (
        input("\nImport these courses and attempt registration? (y/n): ")
        .strip()
        .lower()
    )
    if confirm != "y":
        print("Import cancelled.")
        return

    slns = [item["registrationCode"] for item in register_items]
    for extra_sln in extra_slns:
        if extra_sln not in slns:
            slns.append(extra_sln)

    sln_labels = {
        item["registrationCode"]: item["courseCode"]
        for item in register_items
        if item.get("registrationCode")
    }
    for extra_sln in extra_slns:
        sln_labels.setdefault(extra_sln, f"Manual SLN {extra_sln}")

    register_add_courses_with_retry(
        client=client,
        quarter_code=quarter_code,
        slns=slns,
        sln_labels=sln_labels,
    )


def _load_registered_courses(
    client: UWAPI.UWAPI,
    quarter_code: str,
    *,
    empty_message: str,
) -> list[dict[str, Any]]:
    """Fetch typed registration items for a quarter or print an empty-state message."""
    reg_data, _ = client.get_registration_with_source(
        quarter_code=quarter_code,
        use_cache=False,
    )
    registrations = _typed_registration_items(reg_data.get("registrations", []))
    if not registrations:
        print(empty_message)
    return registrations


def _print_registration_choices(
    registrations: list[dict[str, Any]],
    *,
    heading: str,
) -> None:
    """Print numbered registration choices for drop/swap selection."""
    print(heading)
    for index, registration in enumerate(registrations, start=1):
        print(f"{index}. {_registration_display_line(registration)}")


def _parse_and_validate_selection(raw_input: str, max_index: int) -> list[int] | None:
    """Parse and validate a comma-separated list of menu indexes."""
    if not raw_input:
        print("No class numbers entered.")
        return None

    try:
        selected_indexes = [
            int(value.strip()) for value in raw_input.split(",") if value.strip()
        ]
    except ValueError:
        print("Invalid input. Please enter numbers separated by commas.")
        return None

    if not selected_indexes:
        print("No valid class numbers entered.")
        return None

    if any(index < 1 or index > max_index for index in selected_indexes):
        print("One or more class numbers are out of range.")
        return None

    unique_indexes: list[int] = []
    for index in selected_indexes:
        if index not in unique_indexes:
            unique_indexes.append(index)

    return unique_indexes


def drop_classes(client: UWAPI.UWAPI, quarter_code: str) -> None:
    """Drop selected courses from registration."""
    registrations = _load_registered_courses(
        client,
        quarter_code,
        empty_message="No currently registered classes found to drop.",
    )
    if not registrations:
        return

    _print_registration_choices(registrations, heading="Select class(es) to drop:")

    raw_selection = input("Enter class numbers to drop (e.g. 1,3): ").strip()
    unique_indexes = _parse_and_validate_selection(raw_selection, len(registrations))
    if unique_indexes is None:
        return

    slns: list[str] = []
    sln_labels: dict[str, str] = {}
    selected_registrations: list[dict[str, Any]] = []
    for index in unique_indexes:
        registration = registrations[index - 1]
        section = _registration_section(registration)
        sln = str(section.get("sln", "")).strip()
        if not sln:
            continue

        selected_registrations.append(registration)
        slns.append(sln)
        sln_labels[sln] = f"Drop {_course_label(section)}"

    if not slns:
        print("Could not find SLNs for selected classes.")
        return

    result = client.drop_courses(
        quarter_code=quarter_code,
        slns=slns,
        drop_registrations=selected_registrations,
    )
    _print_registration_response(result, sln_labels=sln_labels)


def swap_classes(client: UWAPI.UWAPI, quarter_code: str) -> None:
    """Swap one course for another in registration."""
    registrations = _load_registered_courses(
        client,
        quarter_code,
        empty_message="No currently registered classes found to swap.",
    )
    if not registrations:
        return

    _print_registration_choices(
        registrations,
        heading="Select class to drop for the swap:",
    )

    drop_selection = input("Enter class number to drop: ").strip()
    try:
        selected_index = int(drop_selection)
    except ValueError:
        print("Invalid input. Please enter a class number.")
        return

    if selected_index < 1 or selected_index > len(registrations):
        print("Class number is out of range.")
        return

    selected_registration = registrations[selected_index - 1]
    selected_section = _registration_section(selected_registration)
    drop_sln = str(selected_section.get("sln", "")).strip()
    add_sln = input("Enter SLN to add: ").strip()

    if not drop_sln or not add_sln:
        print("Both drop SLN and add SLN are required.")
        return

    result = client.swap_classes(
        quarter_code=quarter_code,
        drop_sln=drop_sln,
        add_sln=add_sln,
        drop_registration=selected_registration,
    )

    sln_labels = {
        drop_sln: f"Drop {_course_label(selected_section)}",
        add_sln: f"Add SLN {add_sln}",
    }
    _print_registration_response(result, sln_labels=sln_labels)


def show_registration_summary(
    client: UWAPI.UWAPI,
    *,
    quarter_code: str,
    success_message: str,
) -> None:
    """Fetch and print a registration summary for a specific quarter."""
    reg_data, source = client.get_registration_with_source(quarter_code)
    print(success_message)
    _print_data_source(source)
    _print_current_registration_summary(reg_data)

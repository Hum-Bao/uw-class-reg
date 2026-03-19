"""Interactive menu interface for UW class registration."""

# ruff: noqa: T201

import os
import subprocess
from collections.abc import Callable
from functools import partial

import scheduler
import UWAPI
from menu_layout import (
    BACK_OUTCOME,
    CONTINUE_OUTCOME,
    EXIT_OUTCOME,
    MenuDefinition,
    MenuOption,
    MenuOutcome,
    run_configured_menu,
)
from registration import (
    detect_current_quarter_code,
    drop_classes,
    register_add_courses_with_retry,
    register_from_myplan,
    register_with_manual_slns,
    select_current_year_quarter,
    show_registration_summary,
    swap_classes,
)


def _clear_console() -> None:
    """Clear the console using a platform-specific command."""
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "cls"], check=False)  # noqa: S607
    else:
        subprocess.run(["clear"], check=False)  # noqa: S607


def _run_action(action: Callable[[], None]) -> MenuOutcome:
    """Execute an action and return the standard continue outcome."""
    action()
    return CONTINUE_OUTCOME


def _run_submenu(menu: MenuDefinition) -> MenuOutcome:
    """Clear the screen and execute one submenu interaction."""
    _clear_console()
    return run_configured_menu(menu)


def _go_back() -> MenuOutcome:
    """Return to the previous menu without pausing."""
    return BACK_OUTCOME


def _exit_menu() -> MenuOutcome:
    """Exit the interactive menu loop."""
    print("Exiting program.")
    return EXIT_OUTCOME


def handle_view_current_registration(client: UWAPI.UWAPI) -> None:
    """Handle viewing current quarter registration."""
    current_quarter = detect_current_quarter_code()
    show_registration_summary(
        client,
        quarter_code=current_quarter,
        success_message="Successfully fetched current registration summary.",
    )


def handle_view_previous_registrations(client: UWAPI.UWAPI) -> None:
    """Handle viewing registration for previous quarters."""
    selected_quarter = select_current_year_quarter("viewing")
    if selected_quarter is None:
        return

    quarter_choice, quarter_name, quarter_code = selected_quarter
    show_registration_summary(
        client,
        quarter_code=quarter_code,
        success_message=(
            "Successfully fetched registration summary for "
            f"Quarter {quarter_choice} ({quarter_name})."
        ),
    )


def handle_register_for_classes(client: UWAPI.UWAPI) -> None:
    """Handle course registration process."""
    selected_quarter = select_current_year_quarter("registration")
    if selected_quarter is None:
        return

    quarter_choice, quarter_name, quarter_code = selected_quarter
    print(f"Selected Quarter {quarter_choice} ({quarter_name}) - {quarter_code}")

    print("\nSelect registration method:")
    print("1. Import from MyPlan")
    print("2. Enter SLN(s)")
    method_choice = input("Enter option number (1-2): ").strip()

    if method_choice == "1":
        register_from_myplan(client, quarter_code)
    elif method_choice == "2":
        register_with_manual_slns(client, quarter_code)
    else:
        print("Invalid option. Please enter 1 or 2.")


def handle_edit_registration(client: UWAPI.UWAPI) -> None:
    """Handle editing existing registration (drop or swap)."""
    selected_quarter = select_current_year_quarter("editing registration")
    if selected_quarter is None:
        return

    quarter_choice, quarter_name, quarter_code = selected_quarter
    print(f"Selected Quarter {quarter_choice} ({quarter_name}) - {quarter_code}")

    print("\nSelect edit action:")
    print("1. Drop Class")
    print("2. Swap Class")
    action_choice = input("Enter option number (1-2): ").strip()

    if action_choice == "1":
        drop_classes(client, quarter_code)
    elif action_choice == "2":
        swap_classes(client, quarter_code)
    else:
        print("Invalid option. Please enter 1 or 2.")


def _build_view_menu(client: UWAPI.UWAPI) -> MenuDefinition:
    """Create the View submenu definition."""
    return MenuDefinition(
        title="View options:",
        options=(
            MenuOption(
                key="1",
                label="View Current Registration",
                action=partial(
                    _run_action,
                    partial(handle_view_current_registration, client),
                ),
            ),
            MenuOption(
                key="2",
                label="View Registrations (Current Year)",
                action=partial(
                    _run_action,
                    partial(handle_view_previous_registrations, client),
                ),
            ),
        ),
        zero_label="Back",
        zero_action=_go_back,
    )


def _build_register_menu(client: UWAPI.UWAPI) -> MenuDefinition:
    """Create the Register submenu definition."""
    return MenuDefinition(
        title="Register options:",
        options=(
            MenuOption(
                key="1",
                label="Register For Classes",
                action=partial(
                    _run_action,
                    partial(handle_register_for_classes, client),
                ),
            ),
        ),
        zero_label="Back",
        zero_action=_go_back,
    )


def _build_schedule_menu(client: UWAPI.UWAPI) -> MenuDefinition:
    """Create the Schedule submenu definition."""
    return MenuDefinition(
        title="Schedule options:",
        options=(
            MenuOption(
                key="1",
                label="Schedule Registration by Time",
                action=partial(
                    _run_action,
                    partial(
                        scheduler.handle_schedule_registration,
                        client=client,
                        select_current_year_quarter=select_current_year_quarter,
                        register_from_myplan=register_from_myplan,
                        register_add_courses_with_retry=register_add_courses_with_retry,
                    ),
                ),
            ),
            MenuOption(
                key="2",
                label="Register on Email Trigger",
                action=partial(
                    _run_action,
                    partial(
                        scheduler.handle_schedule_registration_on_email,
                        client=client,
                        select_current_year_quarter=select_current_year_quarter,
                        register_add_courses_with_retry=register_add_courses_with_retry,
                    ),
                ),
            ),
        ),
        zero_label="Back",
        zero_action=_go_back,
    )


def _build_manage_menu(client: UWAPI.UWAPI) -> MenuDefinition:
    """Create the Manage submenu definition."""
    return MenuDefinition(
        title="Manage options:",
        options=(
            MenuOption(
                key="1",
                label="Edit Registration",
                action=partial(_run_action, partial(handle_edit_registration, client)),
            ),
        ),
        zero_label="Back",
        zero_action=_go_back,
    )


def _build_main_menu(client: UWAPI.UWAPI) -> MenuDefinition:
    """Create the top-level menu definition."""
    return MenuDefinition(
        title="Select a category:",
        options=(
            MenuOption(
                key="1",
                label="View",
                action=partial(_run_submenu, _build_view_menu(client)),
            ),
            MenuOption(
                key="2",
                label="Register",
                action=partial(_run_submenu, _build_register_menu(client)),
            ),
            MenuOption(
                key="3",
                label="Schedule",
                action=partial(_run_submenu, _build_schedule_menu(client)),
            ),
            MenuOption(
                key="4",
                label="Manage",
                action=partial(_run_submenu, _build_manage_menu(client)),
            ),
        ),
        zero_label="Exit",
        zero_action=_exit_menu,
    )


def run_menu(client: UWAPI.UWAPI) -> None:
    """Run the main interactive menu loop."""
    while True:
        _clear_console()

        try:
            outcome = run_configured_menu(_build_main_menu(client))
        except (
            ConnectionError,
            TimeoutError,
            ValueError,
            TypeError,
            UWAPI.NotAuthenticatedError,
            UWAPI.MissingSecurityTokensError,
            UWAPI.EmptySLNListError,
            UWAPI.EmptyPayloadError,
            UWAPI.SwapMissingSLNsError,
            UWAPI.UnexpectedMyPlanFormatError,
        ) as error:
            print(f"Action failed: {error}")
            outcome = CONTINUE_OUTCOME

        if outcome.should_exit:
            break

        if outcome.should_pause:
            try:
                input("\nPress Enter to return to menu...")
            except EOFError:
                print("\nInput stream closed. Exiting program.")
                break

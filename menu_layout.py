"""Reusable menu rendering and dispatch helpers."""

# ruff: noqa: T201

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

SINGLE_ALLOWED_VALUE_COUNT: Final[int] = 1
ALLOWED_VALUE_PAIR_COUNT: Final[int] = 2


@dataclass(frozen=True)
class MenuOutcome:
    """Represents what the main menu loop should do after an action."""

    should_exit: bool = False
    should_pause: bool = True


CONTINUE_OUTCOME: Final[MenuOutcome] = MenuOutcome()
BACK_OUTCOME: Final[MenuOutcome] = MenuOutcome(should_pause=False)
EXIT_OUTCOME: Final[MenuOutcome] = MenuOutcome(should_exit=True, should_pause=False)


@dataclass(frozen=True)
class MenuOption:
    """Single menu option with a selection key and action."""

    key: str
    label: str
    action: Callable[[], MenuOutcome]


@dataclass(frozen=True)
class MenuDefinition:
    """Menu configuration for a title, options, and zero-key behavior."""

    title: str
    options: tuple[MenuOption, ...]
    zero_label: str
    zero_action: Callable[[], MenuOutcome]
    prompt: str = "Enter option number: "


def _format_allowed_values(options: tuple[MenuOption, ...]) -> str:
    """Format allowed menu keys for invalid-input messaging."""
    allowed_values = [option.key for option in options]
    allowed_values.append("0")

    if len(allowed_values) == SINGLE_ALLOWED_VALUE_COUNT:
        return allowed_values[0]
    if len(allowed_values) == ALLOWED_VALUE_PAIR_COUNT:
        return f"{allowed_values[0]} or {allowed_values[1]}"

    return ", ".join(allowed_values[:-1]) + f", or {allowed_values[-1]}"


def run_configured_menu(menu: MenuDefinition) -> MenuOutcome:
    """Render a menu, prompt once, and execute the selected action."""
    print(menu.title)
    for option in menu.options:
        print(f"{option.key}. {option.label}")
    print(f"0. {menu.zero_label}")

    try:
        choice = input(menu.prompt).strip()
    except EOFError:
        print("\nInput stream closed. Exiting program.")
        return EXIT_OUTCOME

    if choice == "0":
        return menu.zero_action()

    for option in menu.options:
        if option.key == choice:
            return option.action()

    print(f"Invalid option. Please enter {_format_allowed_values(menu.options)}.")
    return CONTINUE_OUTCOME

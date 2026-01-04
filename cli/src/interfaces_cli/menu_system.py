"""Menu navigation system with stack-based navigation."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, List, Optional

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from interfaces_cli.styles import Colors, hacker_style

if TYPE_CHECKING:
    from interfaces_cli.app import PhiApplication


class MenuResult(Enum):
    """Result of menu action."""

    CONTINUE = "continue"  # Stay in current menu
    BACK = "back"  # Go back one level
    EXIT = "exit"  # Exit application


class MenuSystem:
    """Stack-based menu navigation system."""

    def __init__(self):
        self._stack: List[Callable[[], MenuResult]] = []

    def push(self, menu_func: Callable[[], MenuResult]) -> None:
        """Push menu onto stack."""
        self._stack.append(menu_func)

    def pop(self) -> Optional[Callable[[], MenuResult]]:
        """Pop menu from stack."""
        if self._stack:
            return self._stack.pop()
        return None

    def clear(self) -> None:
        """Clear the menu stack."""
        self._stack.clear()

    @property
    def depth(self) -> int:
        """Current stack depth."""
        return len(self._stack)

    def run(self, initial_menu: Callable[[], MenuResult]) -> None:
        """Run the menu loop."""
        self.push(initial_menu)

        while self._stack:
            current_menu = self._stack[-1]

            try:
                result = current_menu()
            except KeyboardInterrupt:
                # Ctrl+C at top level = exit, otherwise = back
                if self.depth <= 1:
                    print(f"\n{Colors.muted('Interrupted.')}")
                    break
                result = MenuResult.BACK

            if result == MenuResult.BACK:
                self.pop()
            elif result == MenuResult.EXIT:
                break
            # CONTINUE: loop continues with same menu


class BaseMenu(ABC):
    """Base class for all menus."""

    BACK_VALUE = "__BACK__"
    show_back = True  # Override to False in main menu

    def __init__(self, app: "PhiApplication"):
        self.app = app
        self.api = app.api

    @property
    @abstractmethod
    def title(self) -> str:
        """Menu title shown in prompt."""
        pass

    @abstractmethod
    def get_choices(self) -> List[Choice]:
        """Get menu choices (without back option)."""
        pass

    @abstractmethod
    def handle_choice(self, choice: Any) -> MenuResult:
        """Handle selected choice."""
        pass

    def before_show(self) -> None:
        """Called before showing menu. Override for setup."""
        pass

    def show(self) -> MenuResult:
        """Display menu and handle selection."""
        self.before_show()

        choices = self.get_choices()
        if self.show_back:
            choices.append(Choice(value=self.BACK_VALUE, name="« 戻る"))

        try:
            selected = inquirer.select(
                message=f"[{self.title}]",
                choices=choices,
                style=hacker_style,
                qmark="",
                amark="",
                pointer="❯",
            ).execute()
        except KeyboardInterrupt:
            return MenuResult.BACK

        if selected == self.BACK_VALUE:
            return MenuResult.BACK

        return self.handle_choice(selected)

    def submenu(self, menu_class: type) -> MenuResult:
        """Push a submenu onto the stack."""
        submenu = menu_class(self.app)
        self.app.menu.push(submenu.show)
        return MenuResult.CONTINUE

    def confirm(self, message: str, default: bool = False) -> bool:
        """Show confirmation prompt."""
        try:
            return inquirer.confirm(
                message=message,
                default=default,
                style=hacker_style,
                qmark="",
                amark="",
            ).execute()
        except KeyboardInterrupt:
            return False

    def input(self, message: str, default: str = "") -> Optional[str]:
        """Show text input prompt."""
        try:
            return inquirer.text(
                message=message,
                default=default,
                style=hacker_style,
                qmark="",
                amark="",
            ).execute()
        except KeyboardInterrupt:
            return None

    def wait_for_enter(self, message: str = "Enterキーで戻る...") -> None:
        """Wait for user to press Enter."""
        input(f"\n{Colors.muted(message)}")

    def print_success(self, message: str) -> None:
        """Print success message."""
        print(f"{Colors.success('✓')} {message}")

    def print_error(self, message: str) -> None:
        """Print error message."""
        print(f"{Colors.error('✗')} {message}")

    def print_info(self, message: str) -> None:
        """Print info message."""
        print(f"{Colors.info('ℹ')} {message}")

    def print_warning(self, message: str) -> None:
        """Print warning message."""
        print(f"{Colors.warning('⚠')} {message}")

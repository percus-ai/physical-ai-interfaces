"""Phi Application - Main application coordinator."""

from typing import Optional

from interfaces_cli.banner import clear_screen, show_banner, show_device_status_panel
from interfaces_cli.client import PhiClient
from interfaces_cli.menu_system import MenuSystem


class PhiApplication:
    """Main application class that coordinates all components."""

    def __init__(self, backend_url: Optional[str] = None):
        """Initialize application.

        Args:
            backend_url: Optional backend URL override
        """
        self.api = PhiClient(base_url=backend_url)
        self.menu = MenuSystem()
        self._current_project: Optional[str] = None

    @property
    def current_project(self) -> Optional[str]:
        """Get currently selected project."""
        return self._current_project

    @current_project.setter
    def current_project(self, value: Optional[str]) -> None:
        """Set current project."""
        self._current_project = value

    def check_backend(self) -> str:
        """Check backend connection status.

        Returns:
            'ok', 'error', or 'unknown'
        """
        try:
            health = self.api.health()
            return "ok" if health.get("status") in ("ok", "healthy") else "unknown"
        except Exception:
            return "error"

    def get_device_count(self) -> int:
        """Get number of connected devices."""
        try:
            devices = self.api.list_devices()
            return devices.get("total", 0)
        except Exception:
            return 0

    def show_header(self) -> None:
        """Display application header with banner and status."""
        clear_screen()
        show_banner()
        show_device_status_panel(backend_status=self.check_backend())

    def run(self) -> None:
        """Run the application main loop."""
        from interfaces_cli.menus.main_menu import MainMenu

        self.show_header()
        main_menu = MainMenu(self)
        self.menu.run(main_menu.show)

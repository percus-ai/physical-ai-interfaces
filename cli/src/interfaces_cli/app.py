"""Phi Application - Main application coordinator."""

from typing import Optional

import getpass

from interfaces_cli.banner import clear_screen, show_banner, show_device_status_panel
from interfaces_cli.client import PhiClient
from interfaces_cli.menu_system import MenuSystem
from interfaces_cli.styles import Colors


class PhiApplication:
    """Main application class that coordinates all components."""

    def __init__(self, backend_url: Optional[str] = None):
        """Initialize application.

        Args:
            backend_url: Optional backend URL override
        """
        self.api = PhiClient(base_url=backend_url)
        self.menu = MenuSystem()

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

    def check_auth(self) -> str:
        """Check auth status for Supabase session."""
        try:
            status = self.api.auth_status()
        except Exception:
            return "unknown"
        return "ok" if status.get("authenticated") else "error"

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
        show_device_status_panel(
            backend_status=self.check_backend(),
            auth_status=self.check_auth(),
        )

    def _prompt_login(self) -> bool:
        email = input(f"{Colors.info('Email')}: ").strip()
        if not email:
            return False
        password = getpass.getpass(f"{Colors.info('Password')}: ")
        if not password:
            return False
        try:
            self.api.auth_login(email=email, password=password)
        except Exception:
            print(Colors.error("✗ ログインに失敗しました。メール/パスワードを確認してください。"))
            return False
        return True

    def ensure_login(self) -> bool:
        """Ensure Supabase session is available before entering menus."""
        try:
            status = self.api.auth_status()
        except Exception:
            print(Colors.error("✗ Auth状態の取得に失敗しました。バックエンドを確認してください。"))
            return False

        if status.get("authenticated"):
            return True

        print(Colors.warning("⚠ ログインが必要です。"))
        while True:
            if self._prompt_login():
                return True
            retry = input(Colors.muted("再試行しますか？ (y/N): ")).strip().lower()
            if retry != "y":
                return False

    def logout_and_relogin(self) -> bool:
        """Logout and prompt for login again."""
        try:
            self.api.auth_logout()
        except Exception:
            print(Colors.error("✗ ログアウトに失敗しました。"))
            return False
        print(Colors.info("ℹ ログアウトしました。再ログインしてください。"))
        return self.ensure_login()

    def run(self) -> None:
        """Run the application main loop."""
        from interfaces_cli.menus.main_menu import MainMenu

        self.show_header()
        if not self.ensure_login():
            print(Colors.muted("ログインをキャンセルしました。"))
            return
        main_menu = MainMenu(self)
        self.menu.run(main_menu.show)

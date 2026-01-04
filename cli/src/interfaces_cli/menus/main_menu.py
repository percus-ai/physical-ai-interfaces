"""Main menu implementation."""

from typing import TYPE_CHECKING, Any, List

from InquirerPy.base.control import Choice

from interfaces_cli.menu_system import BaseMenu, MenuResult

if TYPE_CHECKING:
    from interfaces_cli.app import PhiApplication


class MainMenu(BaseMenu):
    """Main menu - entry point for all operations."""

    title = "メインメニュー"
    show_back = False  # Main menu doesn't show back option

    def get_choices(self) -> List[Choice]:
        """Get main menu choices."""
        return [
            Choice(value="operate", name="🎮 [OPERATE] テレオペ / 推論実行"),
            Choice(value="record", name="📹 [RECORD] データ録画"),
            Choice(value="train", name="☁️  [TRAIN] モデル学習"),
            Choice(value="storage", name="📦 [STORAGE] データ管理"),
            Choice(value="setup", name="🔧 [SETUP] デバイス・プロジェクト設定"),
            Choice(value="info", name="📊 [INFO] システム情報"),
            Choice(value="config", name="⚙️  [CONFIG] 環境設定"),
            Choice(value="exit", name="❌ [EXIT] 終了"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        """Handle main menu selection."""
        if choice == "exit":
            return MenuResult.EXIT

        if choice == "operate":
            from interfaces_cli.menus.operate import OperateMenu
            return self.submenu(OperateMenu)

        if choice == "record":
            from interfaces_cli.menus.record import RecordMenu
            return self.submenu(RecordMenu)

        if choice == "train":
            from interfaces_cli.menus.train import TrainMenu
            return self.submenu(TrainMenu)

        if choice == "storage":
            from interfaces_cli.menus.storage import StorageMenu
            return self.submenu(StorageMenu)

        if choice == "setup":
            from interfaces_cli.menus.setup import SetupMenu
            return self.submenu(SetupMenu)

        if choice == "info":
            from interfaces_cli.menus.info import InfoMenu
            return self.submenu(InfoMenu)

        if choice == "config":
            from interfaces_cli.menus.config import ConfigMenu
            return self.submenu(ConfigMenu)

        return MenuResult.CONTINUE

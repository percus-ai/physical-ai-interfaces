"""Storage menu - Data management operations."""

from typing import TYPE_CHECKING, Any, List

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from interfaces_cli.banner import format_size, show_section_header
from interfaces_cli.menu_system import BaseMenu, MenuResult
from interfaces_cli.styles import Colors, hacker_style

if TYPE_CHECKING:
    from interfaces_cli.app import PhiApplication


class StorageMenu(BaseMenu):
    """Storage menu - Data management operations."""

    title = "データ管理"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="datasets", name="📁 [DATASETS] データセット管理"),
            Choice(value="models", name="🤖 [MODELS] モデル管理"),
            Choice(value="sync", name="🔄 [SYNC] R2クラウド同期"),
            Choice(value="hub", name="🌐 [HUB] HuggingFace連携"),
            Choice(value="archive", name="📦 [ARCHIVE] アーカイブ一覧"),
            Choice(value="usage", name="📊 [USAGE] ストレージ使用量"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "datasets":
            return self.submenu(DatasetsMenu)
        if choice == "models":
            return self.submenu(ModelsMenu)
        if choice == "sync":
            return self.submenu(R2SyncMenu)
        if choice == "hub":
            return self.submenu(HuggingFaceMenu)
        if choice == "archive":
            return self._show_archive()
        if choice == "usage":
            return self._show_usage()
        return MenuResult.CONTINUE

    def _show_usage(self) -> MenuResult:
        """Show storage usage statistics."""
        show_section_header("Storage Usage")

        try:
            usage = self.api.get_storage_usage()

            print(f"{Colors.CYAN}Local Storage:{Colors.RESET}")
            print(f"  Datasets: {format_size(usage.get('datasets_size_bytes', 0))}")
            print(f"  Models: {format_size(usage.get('models_size_bytes', 0))}")
            print(f"  Total: {format_size(usage.get('total_size_bytes', 0))}")

            print(f"\n{Colors.CYAN}Counts:{Colors.RESET}")
            print(f"  Datasets: {usage.get('datasets_count', 0)}")
            print(f"  Models: {usage.get('models_count', 0)}")

            if usage.get("r2_usage"):
                print(f"\n{Colors.CYAN}R2 Cloud:{Colors.RESET}")
                print(f"  Used: {format_size(usage.get('r2_usage', 0))}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_archive(self) -> MenuResult:
        """Show archived items."""
        show_section_header("Archived Items")

        try:
            result = self.api.list_archive()
            datasets = result.get("datasets", [])
            models = result.get("models", [])

            print(f"{Colors.CYAN}Archived Datasets:{Colors.RESET}")
            if datasets:
                for d in datasets[:10]:
                    name = d.get("id", "unknown")
                    size = format_size(d.get("size_bytes", 0))
                    print(f"  - {name} ({size})")
            else:
                print(f"  {Colors.muted('No archived datasets')}")

            print(f"\n{Colors.CYAN}Archived Models:{Colors.RESET}")
            if models:
                for m in models[:10]:
                    name = m.get("id", "unknown")
                    size = format_size(m.get("size_bytes", 0))
                    print(f"  - {name} ({size})")
            else:
                print(f"  {Colors.muted('No archived models')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class DatasetsMenu(BaseMenu):
    """Datasets management."""

    title = "データセット"

    def get_choices(self) -> List[Choice]:
        choices = []
        try:
            result = self.api.list_datasets()
            datasets = result.get("datasets", [])
            for d in datasets[:15]:
                if isinstance(d, dict):
                    name = d.get("id", d.get("name", "unknown"))
                    size = format_size(d.get("size_bytes", 0))
                    source = d.get("source", "local")
                    choices.append(Choice(value=name, name=f"{name} ({size}) [{source}]"))
                else:
                    choices.append(Choice(value=d, name=d))
        except Exception:
            pass

        if not choices:
            choices.append(Choice(value="__none__", name="(No datasets)"))

        return choices

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "__none__":
            return MenuResult.BACK

        return self._show_dataset_actions(choice)

    def _show_dataset_actions(self, dataset_id: str) -> MenuResult:
        """Show actions for a specific dataset."""
        show_section_header(f"Dataset: {dataset_id}")

        try:
            dataset = self.api.get_dataset(dataset_id)
            print(f"  ID: {dataset.get('id', 'N/A')}")
            print(f"  Source: {dataset.get('source', 'N/A')}")
            print(f"  Size: {format_size(dataset.get('size_bytes', 0))}")
            print(f"  Episodes: {dataset.get('episode_count', 'N/A')}")
            print(f"  Created: {dataset.get('created_at', 'N/A')}")

            # Check sync status
            try:
                sync = self.api.get_dataset_sync_status(dataset_id)
                synced = sync.get("is_synced", False)
                sync_icon = Colors.success("synced") if synced else Colors.warning("not synced")
                print(f"  R2: {sync_icon}")
            except Exception:
                pass

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        action = inquirer.select(
            message="Action:",
            choices=[
                Choice(value="upload", name="Upload to R2"),
                Choice(value="download", name="Download from R2"),
                Choice(value="publish", name="Publish to HuggingFace"),
                Choice(value="delete", name="Delete (archive)"),
                Choice(value="back", name="« Back"),
            ],
            style=hacker_style,
        ).execute()

        if action == "upload":
            try:
                self.api.upload_dataset(dataset_id)
                print(f"{Colors.success('Uploaded to R2')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "download":
            try:
                self.api.download_dataset(dataset_id)
                print(f"{Colors.success('Downloaded from R2')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "publish":
            try:
                repo_id = inquirer.text(
                    message="HuggingFace repo ID (e.g., username/dataset-name):",
                    style=hacker_style,
                ).execute()
                if repo_id:
                    private = inquirer.confirm(
                        message="Make private?",
                        default=False,
                        style=hacker_style,
                    ).execute()
                    self.api.publish_dataset(dataset_id, repo_id=repo_id, private=private)
                    print(f"{Colors.success('Published to HuggingFace')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "delete":
            confirm = inquirer.confirm(
                message=f"Archive dataset {dataset_id}?",
                default=False,
                style=hacker_style,
            ).execute()
            if confirm:
                try:
                    self.api.delete_dataset(dataset_id)
                    print(f"{Colors.success('Dataset archived')}")
                except Exception as e:
                    print(f"{Colors.error('Error:')} {e}")

        if action != "back":
            input(f"\n{Colors.muted('Press Enter to continue...')}")

        return MenuResult.CONTINUE


class ModelsMenu(BaseMenu):
    """Models management."""

    title = "モデル"

    def get_choices(self) -> List[Choice]:
        choices = []
        try:
            result = self.api.list_models()
            models = result.get("models", [])
            for m in models[:15]:
                if isinstance(m, dict):
                    name = m.get("id", m.get("name", "unknown"))
                    size = format_size(m.get("size_bytes", 0))
                    policy = m.get("policy_type", "?")
                    choices.append(Choice(value=name, name=f"{name} [{policy}] ({size})"))
                else:
                    choices.append(Choice(value=m, name=m))
        except Exception:
            pass

        if not choices:
            choices.append(Choice(value="__none__", name="(No models)"))

        return choices

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "__none__":
            return MenuResult.BACK

        return self._show_model_actions(choice)

    def _show_model_actions(self, model_id: str) -> MenuResult:
        """Show actions for a specific model."""
        show_section_header(f"Model: {model_id}")

        try:
            model = self.api.get_model(model_id)
            print(f"  ID: {model.get('id', 'N/A')}")
            print(f"  Policy: {model.get('policy_type', 'N/A')}")
            print(f"  Source: {model.get('source', 'N/A')}")
            print(f"  Size: {format_size(model.get('size_bytes', 0))}")
            print(f"  Created: {model.get('created_at', 'N/A')}")

            # Check sync status
            try:
                sync = self.api.get_model_sync_status(model_id)
                synced = sync.get("is_synced", False)
                sync_icon = Colors.success("synced") if synced else Colors.warning("not synced")
                print(f"  R2: {sync_icon}")
            except Exception:
                pass

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        action = inquirer.select(
            message="Action:",
            choices=[
                Choice(value="upload", name="Upload to R2"),
                Choice(value="download", name="Download from R2"),
                Choice(value="publish", name="Publish to HuggingFace"),
                Choice(value="delete", name="Delete (archive)"),
                Choice(value="back", name="« Back"),
            ],
            style=hacker_style,
        ).execute()

        if action == "upload":
            try:
                self.api.upload_model(model_id)
                print(f"{Colors.success('Uploaded to R2')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "download":
            try:
                self.api.download_model(model_id)
                print(f"{Colors.success('Downloaded from R2')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "publish":
            try:
                repo_id = inquirer.text(
                    message="HuggingFace repo ID (e.g., username/model-name):",
                    style=hacker_style,
                ).execute()
                if repo_id:
                    private = inquirer.confirm(
                        message="Make private?",
                        default=False,
                        style=hacker_style,
                    ).execute()
                    self.api.publish_model(model_id, repo_id=repo_id, private=private)
                    print(f"{Colors.success('Published to HuggingFace')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "delete":
            confirm = inquirer.confirm(
                message=f"Archive model {model_id}?",
                default=False,
                style=hacker_style,
            ).execute()
            if confirm:
                try:
                    self.api.delete_model(model_id)
                    print(f"{Colors.success('Model archived')}")
                except Exception as e:
                    print(f"{Colors.error('Error:')} {e}")

        if action != "back":
            input(f"\n{Colors.muted('Press Enter to continue...')}")

        return MenuResult.CONTINUE


class R2SyncMenu(BaseMenu):
    """R2 synchronization."""

    title = "R2クラウド同期"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="push", name="📤 [PUSH] マニフェストをR2にアップロード"),
            Choice(value="pull", name="📥 [PULL] R2からマニフェストをダウンロード"),
            Choice(value="usage", name="📊 [USAGE] R2使用量"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        show_section_header(f"R2 Sync: {choice}")

        if choice == "push":
            try:
                confirm = inquirer.confirm(
                    message="Push local manifest to R2?",
                    default=True,
                    style=hacker_style,
                ).execute()
                if confirm:
                    result = self.api.push_manifest()
                    print(f"{Colors.success('Manifest pushed to R2')}")
                    print(f"  Datasets: {result.get('datasets_count', 0)}")
                    print(f"  Models: {result.get('models_count', 0)}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif choice == "pull":
            try:
                confirm = inquirer.confirm(
                    message="Pull manifest from R2? (This will update local manifest)",
                    default=True,
                    style=hacker_style,
                ).execute()
                if confirm:
                    result = self.api.pull_manifest()
                    print(f"{Colors.success('Manifest pulled from R2')}")
                    print(f"  Datasets: {result.get('datasets_count', 0)}")
                    print(f"  Models: {result.get('models_count', 0)}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif choice == "usage":
            try:
                usage = self.api.get_storage_usage()
                print(f"{Colors.CYAN}R2 Storage:{Colors.RESET}")
                print(f"  Total: {format_size(usage.get('r2_size', 0))}")
                print(f"  Datasets: {format_size(usage.get('r2_datasets_size', 0))}")
                print(f"  Models: {format_size(usage.get('r2_models_size', 0))}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class HuggingFaceMenu(BaseMenu):
    """HuggingFace Hub integration."""

    title = "HuggingFace"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="import_dataset", name="📥 [IMPORT] データセットをダウンロード"),
            Choice(value="import_model", name="📥 [IMPORT] モデルをダウンロード"),
            Choice(value="search", name="🔍 [SEARCH] Hubを検索"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "import_dataset":
            return self._import_dataset()
        if choice == "import_model":
            return self._import_model()
        if choice == "search":
            return self._search_hub()
        return MenuResult.CONTINUE

    def _import_dataset(self) -> MenuResult:
        """Import dataset from HuggingFace Hub."""
        show_section_header("Import Dataset from HuggingFace")

        try:
            repo_id = inquirer.text(
                message="Repository ID (e.g., lerobot/pusht):",
                style=hacker_style,
            ).execute()

            if not repo_id:
                return MenuResult.CONTINUE

            print(f"{Colors.muted('Importing dataset...')}")
            result = self.api.import_dataset(repo_id)
            print(f"{Colors.success('Dataset imported!')}")
            print(f"  ID: {result.get('dataset_id', repo_id)}")
            print(f"  Size: {format_size(result.get('size_bytes', 0))}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _import_model(self) -> MenuResult:
        """Import model from HuggingFace Hub."""
        show_section_header("Import Model from HuggingFace")

        try:
            repo_id = inquirer.text(
                message="Repository ID (e.g., lerobot/act_pusht):",
                style=hacker_style,
            ).execute()

            if not repo_id:
                return MenuResult.CONTINUE

            print(f"{Colors.muted('Importing model...')}")
            result = self.api.import_model(repo_id)
            print(f"{Colors.success('Model imported!')}")
            print(f"  ID: {result.get('model_id', repo_id)}")
            print(f"  Policy: {result.get('policy_type', 'N/A')}")
            print(f"  Size: {format_size(result.get('size_bytes', 0))}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _search_hub(self) -> MenuResult:
        """Search HuggingFace Hub."""
        show_section_header("Search HuggingFace Hub")

        try:
            query = inquirer.text(
                message="Search query:",
                style=hacker_style,
            ).execute()

            if not query:
                return MenuResult.CONTINUE

            # Search datasets
            print(f"\n{Colors.CYAN}Searching datasets...{Colors.RESET}")
            datasets = self.api.search_datasets(query)
            ds_list = datasets.get("results", [])
            if ds_list:
                for d in ds_list[:5]:
                    print(f"  - {d.get('id', 'unknown')}")
            else:
                print(f"  {Colors.muted('No datasets found')}")

            # Search models
            print(f"\n{Colors.CYAN}Searching models...{Colors.RESET}")
            models = self.api.search_models(query)
            m_list = models.get("results", [])
            if m_list:
                for m in m_list[:5]:
                    print(f"  - {m.get('id', 'unknown')}")
            else:
                print(f"  {Colors.muted('No models found')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

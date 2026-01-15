"""Storage menu - DB-backed data management operations."""

from typing import TYPE_CHECKING, Any, List, Optional

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator

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
            Separator("─── データ ───"),
            Choice(value="datasets", name="📁 データセット管理"),
            Choice(value="models", name="🤖 モデル管理"),
            Choice(value="huggingface", name="🌐 HuggingFace連携"),
            Separator("─── 情報 ───"),
            Choice(value="archive", name="📦 アーカイブ一覧"),
            Choice(value="usage", name="📊 ストレージ使用量"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "datasets":
            return self.submenu(DatasetsMenu)
        if choice == "models":
            return self.submenu(ModelsMenu)
        if choice == "archive":
            return self._show_archive()
        if choice == "usage":
            return self._show_usage()
        if choice == "huggingface":
            return self.submenu(HuggingFaceMenu)
        return MenuResult.CONTINUE

    def _show_usage(self) -> MenuResult:
        """Show storage usage statistics."""
        show_section_header("Storage Usage")

        try:
            usage = self.api.get_storage_usage()
            print(f"{Colors.CYAN}📁 データセット:{Colors.RESET}")
            print(f"  サイズ: {format_size(usage.get('datasets_size_bytes', 0))}")
            print(f"  件数: {usage.get('datasets_count', 0)}")

            print(f"\n{Colors.CYAN}🤖 モデル:{Colors.RESET}")
            print(f"  サイズ: {format_size(usage.get('models_size_bytes', 0))}")
            print(f"  件数: {usage.get('models_count', 0)}")

            print(f"\n{Colors.CYAN}📦 アーカイブ:{Colors.RESET}")
            print(f"  サイズ: {format_size(usage.get('archive_size_bytes', 0))}")
            print(f"  件数: {usage.get('archive_count', 0)}")

            print(f"\n{Colors.CYAN}合計:{Colors.RESET} {format_size(usage.get('total_size_bytes', 0))}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_archive(self) -> MenuResult:
        """Show archived items."""
        return self.submenu(ArchiveMenu)


class DatasetsMenu(BaseMenu):
    """Datasets management."""

    title = "データセット"

    def get_choices(self) -> List[Choice]:
        choices = []
        try:
            result = self.api.list_datasets()
            datasets = result.get("datasets", [])
            for d in datasets[:15]:
                name = d.get("id", d.get("name", "unknown"))
                size = format_size(d.get("size_bytes", 0))
                source = d.get("source", "r2")
                choices.append(Choice(value=name, name=f"{name} ({size}) [{source}]"))
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
            print(f"  Project: {dataset.get('project_id', 'N/A')}")
            print(f"  Type: {dataset.get('dataset_type', 'N/A')}")
            print(f"  Status: {dataset.get('status', 'N/A')}")
            print(f"  Source: {dataset.get('source', 'N/A')}")
            print(f"  Size: {format_size(dataset.get('size_bytes', 0))}")
            print(f"  Episodes: {dataset.get('episode_count', 'N/A')}")
            print(f"  Created: {dataset.get('created_at', 'N/A')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        action = inquirer.select(
            message="Action:",
            choices=[
                Choice(value="archive", name="Archive"),
                Choice(value="restore", name="Restore"),
                Choice(value="back", name="« Back"),
            ],
            style=hacker_style,
        ).execute()

        if action == "archive":
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

        elif action == "restore":
            try:
                self.api.restore_dataset(dataset_id)
                print(f"{Colors.success('Dataset restored')}")
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
                name = m.get("id", m.get("name", "unknown"))
                size = format_size(m.get("size_bytes", 0))
                source = m.get("source", "r2")
                choices.append(Choice(value=name, name=f"{name} ({size}) [{source}]"))
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
            print(f"  Project: {model.get('project_id', 'N/A')}")
            print(f"  Status: {model.get('status', 'N/A')}")
            print(f"  Source: {model.get('source', 'N/A')}")
            print(f"  Size: {format_size(model.get('size_bytes', 0))}")
            print(f"  Policy: {model.get('policy_type', 'N/A')}")
            print(f"  Created: {model.get('created_at', 'N/A')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        action = inquirer.select(
            message="Action:",
            choices=[
                Choice(value="archive", name="Archive"),
                Choice(value="restore", name="Restore"),
                Choice(value="back", name="« Back"),
            ],
            style=hacker_style,
        ).execute()

        if action == "archive":
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

        elif action == "restore":
            try:
                self.api.restore_model(model_id)
                print(f"{Colors.success('Model restored')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        if action != "back":
            input(f"\n{Colors.muted('Press Enter to continue...')}")

        return MenuResult.CONTINUE


class HuggingFaceMenu(BaseMenu):
    """HuggingFace Hub integration."""

    title = "HuggingFace連携"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="import_dataset", name="📥 データセットをインポート"),
            Choice(value="import_model", name="📥 モデルをインポート"),
            Choice(value="export_dataset", name="📤 データセットをエクスポート"),
            Choice(value="export_model", name="📤 モデルをエクスポート"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "import_dataset":
            return self._import_dataset()
        if choice == "import_model":
            return self._import_model()
        if choice == "export_dataset":
            return self._export_dataset()
        if choice == "export_model":
            return self._export_model()
        return MenuResult.CONTINUE


class ArchiveMenu(BaseMenu):
    """Archive management menu."""

    title = "アーカイブ一覧"

    def get_choices(self) -> List[Choice]:
        choices: List[Choice] = []
        try:
            result = self.api.list_archive()
            datasets = result.get("datasets", [])
            models = result.get("models", [])
            for d in datasets:
                item_id = d.get("id")
                if not item_id:
                    continue
                size = format_size(d.get("size_bytes", 0))
                choices.append(Choice(value=("dataset", item_id), name=f"📁 {item_id} ({size})"))
            for m in models:
                item_id = m.get("id")
                if not item_id:
                    continue
                size = format_size(m.get("size_bytes", 0))
                choices.append(Choice(value=("model", item_id), name=f"🤖 {item_id} ({size})"))
        except Exception:
            pass

        choices.append(Choice(value="bulk_restore", name="♻️  一括復元"))
        choices.append(Choice(value="bulk_delete", name="🧹 一括削除"))
        return choices

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "bulk_restore":
            return self._bulk_restore()
        if choice == "bulk_delete":
            return self._bulk_delete()
        if isinstance(choice, tuple) and len(choice) == 2:
            return self._show_item_detail(choice[0], choice[1])
        return MenuResult.CONTINUE

    def _select_items(self, label: str) -> List[tuple]:
        try:
            result = self.api.list_archive()
            datasets = result.get("datasets", [])
            models = result.get("models", [])
        except Exception:
            datasets = []
            models = []

        choices: List[Choice] = []
        for d in datasets:
            item_id = d.get("id")
            if not item_id:
                continue
            choices.append(Choice(value=("dataset", item_id), name=f"📁 {item_id}"))
        for m in models:
            item_id = m.get("id")
            if not item_id:
                continue
            choices.append(Choice(value=("model", item_id), name=f"🤖 {item_id}"))

        if not choices:
            print(f"{Colors.muted('アーカイブがありません。')}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return []

        selected = inquirer.checkbox(
            message=label,
            choices=choices,
            style=hacker_style,
        ).execute()

        return selected or []

    def _bulk_restore(self) -> MenuResult:
        items = self._select_items("復元する項目を選択:")
        if not items:
            return MenuResult.CONTINUE

        dataset_ids = [item_id for item_type, item_id in items if item_type == "dataset"]
        model_ids = [item_id for item_type, item_id in items if item_type == "model"]

        confirm = inquirer.confirm(
            message="選択した項目を復元しますか?",
            default=False,
            style=hacker_style,
        ).execute()
        if not confirm:
            return MenuResult.CONTINUE

        try:
            result = self.api.restore_archives({
                "dataset_ids": dataset_ids,
                "model_ids": model_ids,
            })
            restored = result.get("restored", [])
            errors = result.get("errors", [])
            if restored:
                print(f"{Colors.success('Restored')}: {len(restored)} items")
            if errors:
                print(f"{Colors.warning('Errors')}: {len(errors)}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _bulk_delete(self) -> MenuResult:
        items = self._select_items("削除する項目を選択:")
        if not items:
            return MenuResult.CONTINUE

        dataset_ids = [item_id for item_type, item_id in items if item_type == "dataset"]
        model_ids = [item_id for item_type, item_id in items if item_type == "model"]

        confirm = inquirer.confirm(
            message="選択した項目を完全に削除しますか?",
            default=False,
            style=hacker_style,
        ).execute()
        if not confirm:
            return MenuResult.CONTINUE

        try:
            result = self.api.delete_archives({
                "dataset_ids": dataset_ids,
                "model_ids": model_ids,
            })
            deleted = result.get("deleted", [])
            errors = result.get("errors", [])
            if deleted:
                print(f"{Colors.success('Deleted')}: {len(deleted)} items")
            if errors:
                print(f"{Colors.warning('Errors')}: {len(errors)}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_item_detail(self, item_type: str, item_id: str) -> MenuResult:
        show_section_header(f"Archived {item_type}: {item_id}")
        try:
            if item_type == "dataset":
                item = self.api.get_dataset(item_id)
            else:
                item = self.api.get_model(item_id)
            print(f"  ID: {item.get('id', 'N/A')}")
            print(f"  Project: {item.get('project_id', 'N/A')}")
            print(f"  Status: {item.get('status', 'N/A')}")
            print(f"  Size: {format_size(item.get('size_bytes', 0))}")
            print(f"  Created: {item.get('created_at', 'N/A')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        action = inquirer.select(
            message="Action:",
            choices=[
                Choice(value="restore", name="復元"),
                Choice(value="delete", name="削除"),
                Choice(value="back", name="« 戻る"),
            ],
            style=hacker_style,
        ).execute()

        if action == "restore":
            try:
                if item_type == "dataset":
                    self.api.restore_dataset(item_id)
                else:
                    self.api.restore_model(item_id)
                print(f"{Colors.success('Restored')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")
        elif action == "delete":
            confirm = inquirer.confirm(
                message="完全に削除しますか?",
                default=False,
                style=hacker_style,
            ).execute()
            if confirm:
                try:
                    if item_type == "dataset":
                        self.api.delete_archived_dataset(item_id)
                    else:
                        self.api.delete_archived_model(item_id)
                    print(f"{Colors.success('Deleted')}")
                except Exception as e:
                    print(f"{Colors.error('Error:')} {e}")

        if action != "back":
            input(f"\n{Colors.muted('Press Enter to continue...')}")

        return MenuResult.CONTINUE

    def _select_project(self) -> Optional[str]:
        try:
            result = self.api.list_projects()
            projects = result.get("projects", [])
        except Exception:
            projects = []

        if not projects:
            print(f"{Colors.warning('No projects found.')}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return None

        choices = [Choice(value=p, name=p) for p in projects]
        choices.append(Choice(value="__back__", name="« Cancel"))
        selected = inquirer.select(
            message="Select project:",
            choices=choices,
            style=hacker_style,
        ).execute()
        if selected == "__back__":
            return None
        return selected

    def _import_dataset(self) -> MenuResult:
        show_section_header("HuggingFace Dataset Import")
        repo_id = inquirer.text(
            message="HuggingFace repo_id (e.g., username/dataset):",
            style=hacker_style,
        ).execute()
        if not repo_id:
            return MenuResult.CONTINUE

        project_id = self._select_project()
        if not project_id:
            return MenuResult.CONTINUE

        default_name = repo_id.split("/")[-1]
        dataset_name = inquirer.text(
            message="Dataset name:",
            default=default_name,
            style=hacker_style,
        ).execute()
        if not dataset_name:
            return MenuResult.CONTINUE

        force = inquirer.confirm(
            message="Overwrite if exists?",
            default=False,
            style=hacker_style,
        ).execute()

        dataset_id = f"{project_id}/{dataset_name}"
        payload = {
            "repo_id": repo_id,
            "project_id": project_id,
            "dataset_id": dataset_id,
            "name": dataset_name,
            "force": force,
        }

        try:
            result = self.api.import_hf_dataset(payload)
            print(f"{Colors.success('Import complete')}: {result.get('repo_url', '')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _import_model(self) -> MenuResult:
        show_section_header("HuggingFace Model Import")
        repo_id = inquirer.text(
            message="HuggingFace repo_id (e.g., username/model):",
            style=hacker_style,
        ).execute()
        if not repo_id:
            return MenuResult.CONTINUE

        project_id = self._select_project()
        if not project_id:
            return MenuResult.CONTINUE

        default_name = repo_id.split("/")[-1]
        model_name = inquirer.text(
            message="Model name:",
            default=default_name,
            style=hacker_style,
        ).execute()
        if not model_name:
            return MenuResult.CONTINUE

        dataset_id = inquirer.text(
            message="Associated dataset_id (optional):",
            default="",
            style=hacker_style,
        ).execute()
        dataset_id = dataset_id.strip() or None

        force = inquirer.confirm(
            message="Overwrite if exists?",
            default=False,
            style=hacker_style,
        ).execute()

        payload = {
            "repo_id": repo_id,
            "project_id": project_id,
            "model_id": model_name,
            "dataset_id": dataset_id,
            "name": model_name,
            "force": force,
        }

        try:
            result = self.api.import_hf_model(payload)
            print(f"{Colors.success('Import complete')}: {result.get('repo_url', '')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _export_dataset(self) -> MenuResult:
        show_section_header("HuggingFace Dataset Export")
        try:
            result = self.api.list_datasets()
            datasets = result.get("datasets", [])
        except Exception:
            datasets = []

        if not datasets:
            print(f"{Colors.warning('No datasets found.')}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        choices = [Choice(value=d.get("id"), name=d.get("id")) for d in datasets if d.get("id")]
        choices.append(Choice(value="__back__", name="« Cancel"))
        dataset_id = inquirer.select(
            message="Select dataset:",
            choices=choices,
            style=hacker_style,
        ).execute()
        if dataset_id == "__back__":
            return MenuResult.CONTINUE

        repo_id = inquirer.text(
            message="HuggingFace repo_id (e.g., username/dataset):",
            style=hacker_style,
        ).execute()
        if not repo_id:
            return MenuResult.CONTINUE

        private = inquirer.confirm(
            message="Create private repository?",
            default=False,
            style=hacker_style,
        ).execute()
        commit_message = inquirer.text(
            message="Commit message (optional):",
            default="",
            style=hacker_style,
        ).execute()
        payload = {
            "repo_id": repo_id,
            "private": private,
            "commit_message": commit_message or None,
        }

        try:
            result = self.api.export_hf_dataset(dataset_id, payload)
            print(f"{Colors.success('Export complete')}: {result.get('repo_url', '')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _export_model(self) -> MenuResult:
        show_section_header("HuggingFace Model Export")
        try:
            result = self.api.list_models()
            models = result.get("models", [])
        except Exception:
            models = []

        if not models:
            print(f"{Colors.warning('No models found.')}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        choices = [Choice(value=m.get("id"), name=m.get("id")) for m in models if m.get("id")]
        choices.append(Choice(value="__back__", name="« Cancel"))
        model_id = inquirer.select(
            message="Select model:",
            choices=choices,
            style=hacker_style,
        ).execute()
        if model_id == "__back__":
            return MenuResult.CONTINUE

        repo_id = inquirer.text(
            message="HuggingFace repo_id (e.g., username/model):",
            style=hacker_style,
        ).execute()
        if not repo_id:
            return MenuResult.CONTINUE

        private = inquirer.confirm(
            message="Create private repository?",
            default=False,
            style=hacker_style,
        ).execute()
        commit_message = inquirer.text(
            message="Commit message (optional):",
            default="",
            style=hacker_style,
        ).execute()
        payload = {
            "repo_id": repo_id,
            "private": private,
            "commit_message": commit_message or None,
        }

        try:
            result = self.api.export_hf_model(model_id, payload)
            print(f"{Colors.success('Export complete')}: {result.get('repo_url', '')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

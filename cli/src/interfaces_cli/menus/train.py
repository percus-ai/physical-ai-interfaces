"""Train menu - Model training operations.

This module implements the training CLI with:
- New training wizard (7 steps)
- Continue training wizard (6 steps)
- Training jobs management
- Training configs management
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from interfaces_cli.banner import format_size, show_section_header
from interfaces_cli.menu_system import BaseMenu, MenuResult
from interfaces_cli.styles import Colors, hacker_style

# =============================================================================
# Policy Configuration Constants
# =============================================================================


@dataclass
class PretrainedModel:
    """Pretrained model option."""

    path: str
    name: str
    description: str = ""


@dataclass
class PolicyTypeInfo:
    """Policy type configuration."""

    display_name: str
    skip_pretrained: bool = False
    pretrained_models: List[PretrainedModel] = field(default_factory=list)
    default_steps: int = 100000
    default_batch_size: int = 32
    default_save_freq: int = 5000
    recommended_storage: int = 100
    recommended_gpu: str = "H100"
    torch_nightly: bool = False
    compile_model: Optional[bool] = None
    gradient_checkpointing: Optional[bool] = None
    dtype: Optional[str] = None


POLICY_TYPES: Dict[str, PolicyTypeInfo] = {
    "act": PolicyTypeInfo(
        display_name="ACT (Action Chunking Transformer)",
        skip_pretrained=True,
        default_steps=200000,
        default_batch_size=64,
        recommended_storage=100,
    ),
    "diffusion": PolicyTypeInfo(
        display_name="Diffusion Policy",
        skip_pretrained=True,
        default_steps=200000,
        default_batch_size=32,
        recommended_storage=100,
    ),
    "pi0": PolicyTypeInfo(
        display_name="π0 (Physical Intelligence)",
        pretrained_models=[
            PretrainedModel("lerobot/pi0_base", "π0 Base (推奨)", "標準ベースモデル"),
        ],
        default_steps=100000,
        default_batch_size=32,
        recommended_storage=200,
        compile_model=True,
        gradient_checkpointing=True,
        dtype="bfloat16",
    ),
    "pi05": PolicyTypeInfo(
        display_name="π0.5 (Open-World VLA Model)",
        pretrained_models=[
            PretrainedModel("lerobot/pi05_base", "π0.5 Base (推奨)", "標準ベースモデル"),
            PretrainedModel("lerobot/pi05_libero", "π0.5 Libero", "Liberoベンチマーク向け"),
        ],
        default_steps=3000,
        default_batch_size=32,
        recommended_storage=200,
        compile_model=True,
        gradient_checkpointing=True,
        dtype="bfloat16",
    ),
    "groot": PolicyTypeInfo(
        display_name="GR00T N1.5 (NVIDIA Isaac GR00T)",
        skip_pretrained=True,  # Auto-loads base model
        default_steps=30000,
        default_batch_size=32,
        recommended_storage=200,
    ),
    "smolvla": PolicyTypeInfo(
        display_name="SmolVLA (Small VLA)",
        pretrained_models=[
            PretrainedModel("lerobot/smolvla_base", "SmolVLA Base (推奨)", "標準ベースモデル"),
        ],
        default_steps=300000,
        default_batch_size=32,
        recommended_storage=100,
    ),
    "vla0": PolicyTypeInfo(
        display_name="VLA-0 (Vision-Language-Action)",
        pretrained_models=[
            PretrainedModel("", "VLA-0 Base", "Qwen2.5-VLベース"),
        ],
        default_steps=100000,
        default_batch_size=8,
        recommended_storage=200,
    ),
}


GPU_MODELS = [
    ("B300", "262GB VRAM - Blackwell Ultra (torch nightly必須)", True),
    ("B200", "180GB VRAM - Blackwell (torch nightly必須)", True),
    ("H200", "141GB VRAM - Hopper 大容量", False),
    ("H100", "80GB VRAM - Hopper 標準 (推奨)", False),
    ("A100", "80GB VRAM - Ampere コスパ良", False),
    ("L40S", "48GB VRAM - Ada Lovelace", False),
    ("RTX6000ADA", "48GB VRAM - RTX 6000 Ada", False),
    ("RTXA6000", "48GB VRAM - RTX A6000", False),
]

GPU_COUNTS = [1, 2, 4, 8]


# =============================================================================
# Wizard State Dataclasses
# =============================================================================


@dataclass
class NewTrainingState:
    """State for new training wizard."""

    # Step 1: Policy
    policy_type: Optional[str] = None

    # Step 2: Pretrained model
    pretrained_path: Optional[str] = None
    skip_pretrained: bool = False

    # Step 3: Dataset (2-stage selection: project -> session)
    project_id: Optional[str] = None  # e.g., "0001_black_cube_to_tray"
    session_name: Optional[str] = None  # e.g., "20260107_180132_watanabe"
    dataset_id: Optional[str] = None  # Full ID: project_id/session_name
    dataset_short_id: Optional[str] = None  # 6-char alphanumeric ID for job naming

    # Step 4: Training params
    steps: int = 100000
    batch_size: int = 32
    save_freq: int = 5000

    # Step 5: Verda settings
    gpu_model: str = "H100"
    gpu_count: int = 1
    storage_size: int = 100
    is_spot: bool = True
    torch_nightly: bool = False

    # Step 6: Job naming
    job_name: Optional[str] = None

    def generate_job_name(self) -> str:
        """Generate job name from state.

        Format: {policy}_{dataset_short_id}_{YYMMDD_HHMMSS}
        Example: pi05_a1b2c3_260109_143052
        """
        parts = []
        if self.policy_type:
            parts.append(self.policy_type)
        if self.dataset_short_id:
            parts.append(self.dataset_short_id)  # 6-char short ID
        # Use 2-digit year and include time (YYMMDD_HHMMSS)
        datetime_str = datetime.now().strftime("%y%m%d_%H%M%S")
        parts.append(datetime_str)
        return "_".join(parts)


@dataclass
class ContinueTrainingState:
    """State for continue training wizard."""

    # Step 1: Policy filter
    policy_filter: Optional[str] = None

    # Step 2: Checkpoint
    checkpoint_job_name: Optional[str] = None
    checkpoint_step: Optional[int] = None
    checkpoint_policy_type: Optional[str] = None
    original_dataset_id: Optional[str] = None

    # Step 3: Dataset
    use_original_dataset: bool = True
    dataset_id: Optional[str] = None

    # Step 4: Training params
    additional_steps: int = 50000
    batch_size: int = 32
    save_freq: int = 5000

    # Step 5: Verda settings
    gpu_model: str = "H100"
    gpu_count: int = 1
    storage_size: int = 100
    is_spot: bool = True
    torch_nightly: bool = False


# =============================================================================
# Utility Functions
# =============================================================================


def download_dataset_with_progress(
    api,
    dataset_id: str,
) -> Dict[str, Any]:
    """Download a dataset with progress display.

    Args:
        api: API client instance
        dataset_id: ID of dataset to download

    Returns:
        Result dict with 'success', 'error' keys
    """
    return {
        "success": False,
        "error": "自動同期は無効です。ローカルにデータが存在する前提で実行してください。",
    }


# =============================================================================
# Main Train Menu
# =============================================================================


class TrainMenu(BaseMenu):
    """Train menu - Model training operations."""

    title = "モデル学習"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="jobs", name="📋 [JOBS] 学習ジョブ一覧"),
            Choice(value="new", name="🚀 [NEW] 新規学習"),
            Choice(value="continue", name="🔄 [CONTINUE] 継続学習"),
            Choice(value="configs", name="⚙️  [CONFIGS] 学習設定管理"),
            Choice(value="verda_storage", name="🗄️  [VERDA] Verdaストレージ管理"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "jobs":
            return self.submenu(TrainingJobsMenu)
        if choice == "new":
            return self.submenu(TrainingWizard)
        if choice == "continue":
            return self.submenu(ContinueTrainingWizard)
        if choice == "configs":
            return self.submenu(TrainingConfigsMenu)
        if choice == "verda_storage":
            return self.submenu(VerdaStorageMenu)
        return MenuResult.CONTINUE


# =============================================================================
# Training Wizard (7 Steps) - 新規学習
# =============================================================================


class VerdaStorageMenu(BaseMenu):
    """Verda storage management menu."""

    title = "Verdaストレージ管理"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="list", name="📄 ストレージ一覧"),
            Choice(
                value="delete",
                name="🗑️  ストレージ削除（論理削除・96時間で自動完全削除）",
            ),
            Choice(value="restore", name="♻️  ストレージ復活（Trashから復元）"),
            Choice(value="purge", name="🔥 ストレージ完全削除（Trashから物理削除）"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "list":
            return self._show_storage_list()
        if choice == "delete":
            return self._delete_storage()
        if choice == "restore":
            return self._restore_storage()
        if choice == "purge":
            return self._purge_storage()
        return MenuResult.CONTINUE

    def _fetch_storage_items(self) -> List[Dict[str, Any]]:
        """Fetch storage items from backend."""
        result = self.api.list_verda_storage()
        return result.get("items", [])

    def _show_storage_list(self) -> MenuResult:
        """Show Verda storage list."""
        show_section_header("Verdaストレージ一覧")

        try:
            items = self._fetch_storage_items()
        except Exception as e:
            self.print_error(f"取得に失敗しました: {e}")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        if not items:
            self.print_info("ストレージがありません")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        filter_choice = inquirer.select(
            message="表示フィルタ:",
            choices=[
                Choice(value="all", name="全件"),
                Choice(value="active", name="有効のみ"),
                Choice(value="deleted", name="削除済みのみ"),
            ],
            style=hacker_style,
        ).execute()

        if filter_choice != "all":
            items = [item for item in items if item.get("state") == filter_choice]

        if not items:
            self.print_info("対象のストレージがありません")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", style="white")
        table.add_column("名前", style="white")
        table.add_column("サイズ", style="white", justify="right")
        table.add_column("状態", style="white")
        table.add_column("削除日時", style="white")

        for item in items:
            state = item.get("state", "active")
            state_label = "削除済み" if state == "deleted" else "有効"
            status = item.get("status", "")
            status_label = f"{state_label} ({status})" if status else state_label
            table.add_row(
                item.get("id", "-"),
                item.get("name") or "-",
                f"{item.get('size_gb', 0)}GB",
                status_label,
                item.get("deleted_at") or "-",
            )

        Console().print(table)
        self.wait_for_enter()
        return MenuResult.CONTINUE

    def _select_storage_ids(self, items: List[Dict[str, Any]], state: str) -> List[str]:
        """Select storage IDs filtered by state."""
        filtered = [item for item in items if item.get("state") == state]
        if not filtered:
            return []

        choices = []
        for item in filtered:
            name = item.get("name") or item.get("id", "-")
            size = item.get("size_gb", 0)
            status = item.get("status", "")
            deleted_at = item.get("deleted_at")
            label_parts = [name, f"{size}GB"]
            if status:
                label_parts.append(status)
            if deleted_at:
                label_parts.append(f"deleted:{deleted_at}")
            label = " | ".join(label_parts)
            choices.append(Choice(value=item.get("id"), name=label))

        selected = inquirer.checkbox(
            message="対象を選択:",
            choices=choices,
            style=hacker_style,
            instruction="(Spaceで選択/解除、Enterで確定)",
            keybindings={"toggle": [{"key": "space"}]},
        ).execute()
        return [s for s in selected if s]

    def _print_action_result(self, result: Dict[str, Any]) -> None:
        """Print action result summary."""
        success_ids = result.get("success_ids", [])
        failed = result.get("failed", [])
        skipped = result.get("skipped", [])

        if success_ids:
            self.print_success(f"成功: {len(success_ids)}件")
        if failed:
            self.print_error(f"失敗: {len(failed)}件")
            for item in failed:
                print(f"  - {item.get('id')}: {item.get('reason')}")
        if skipped:
            self.print_warning(f"スキップ: {len(skipped)}件")
            for item in skipped:
                print(f"  - {item.get('id')}: {item.get('reason')}")

    def _run_storage_action_ws(self, action: str, volume_ids: List[str]) -> Dict[str, Any]:
        """Run storage action via WebSocket and show progress."""
        total = len(volume_ids)
        result: Dict[str, Any] = {}
        current = {
            "done": 0,
            "total": total,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "current_id": "",
            "last_error": "",
        }

        title_map = {
            "delete": "🗑️ Verdaストレージ削除",
            "restore": "♻️ Verdaストレージ復活",
            "purge": "🔥 Verdaストレージ完全削除",
        }

        def make_progress_panel() -> Panel:
            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("Label", style="cyan")
            table.add_column("Value")

            done = current["done"]
            total_count = current["total"] or total
            pct = (done / total_count) * 100 if total_count else 0
            table.add_row("進捗:", f"{done}/{total_count} ({pct:.1f}%)")
            table.add_row("成功:", str(current["success"]))
            table.add_row("失敗:", str(current["failed"]))
            table.add_row("スキップ:", str(current["skipped"]))
            if current["current_id"]:
                table.add_row("対象:", current["current_id"])
            if current["last_error"]:
                table.add_row("直近エラー:", current["last_error"])

            return Panel(table, title=title_map.get(action, "Verdaストレージ操作"), border_style="cyan")

        def on_message(message: Dict[str, Any]) -> None:
            msg_type = message.get("type")
            if msg_type == "start":
                current["total"] = message.get("total", total)
            elif msg_type == "progress":
                current["done"] = message.get("done", current["done"])
                current["current_id"] = message.get("id", current["current_id"])
                status = message.get("status")
                if status == "success":
                    current["success"] += 1
                elif status == "failed":
                    current["failed"] += 1
                    current["last_error"] = message.get("reason", "")[:80]
                elif status == "skipped":
                    current["skipped"] += 1
            elif msg_type == "complete":
                current["done"] = message.get("total", current["done"])
                current["current_id"] = ""

        def on_error(error: str) -> None:
            self.print_error(error)

        console = Console()
        with Live(make_progress_panel(), console=console, refresh_per_second=4) as live:
            def update_display(message: Dict[str, Any]) -> None:
                on_message(message)
                live.update(make_progress_panel())

            result = self.api.verda_storage_action_ws(
                action=action,
                volume_ids=volume_ids,
                on_message=update_display,
                on_error=on_error,
            )

        return result

    def _delete_storage(self) -> MenuResult:
        """Logical delete Verda storage."""
        show_section_header("ストレージ削除（論理削除・96時間で自動完全削除）")

        try:
            items = self._fetch_storage_items()
        except Exception as e:
            self.print_error(f"取得に失敗しました: {e}")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        selected = self._select_storage_ids(items, "active")
        if not selected:
            self.print_info("対象がありません")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        print(f"{Colors.CYAN}注意:{Colors.RESET}")
        print("  - 削除済み領域（Trash）へ移動します（96時間以内なら復元可能）")
        print("  - Trashの間はストレージ枠は解放されません")

        confirm = inquirer.confirm(
            message=f"{len(selected)}件のストレージを削除しますか?",
            default=False,
            style=hacker_style,
        ).execute()
        if not confirm:
            self.print_info("キャンセルしました")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        result = self._run_storage_action_ws("delete", selected)
        if "error" in result:
            self.print_error(f"削除に失敗しました: {result['error']}")
        else:
            self._print_action_result(result)

        self.wait_for_enter()
        return MenuResult.CONTINUE

    def _restore_storage(self) -> MenuResult:
        """Restore Verda storage from trash."""
        show_section_header("ストレージ復活（Trashから復元）")

        try:
            items = self._fetch_storage_items()
        except Exception as e:
            self.print_error(f"取得に失敗しました: {e}")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        selected = self._select_storage_ids(items, "deleted")
        if not selected:
            self.print_info("対象がありません")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        print(f"{Colors.CYAN}注意:{Colors.RESET}")
        print("  - 復元にはPay As You Go料金が発生します")

        confirm = inquirer.confirm(
            message=f"{len(selected)}件のストレージを復活しますか?",
            default=False,
            style=hacker_style,
        ).execute()
        if not confirm:
            self.print_info("キャンセルしました")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        result = self._run_storage_action_ws("restore", selected)
        if "error" in result:
            self.print_error(f"復活に失敗しました: {result['error']}")
        else:
            self._print_action_result(result)

        self.wait_for_enter()
        return MenuResult.CONTINUE

    def _purge_storage(self) -> MenuResult:
        """Permanently delete Verda storage from trash."""
        show_section_header("ストレージ完全削除（Trashから物理削除）")

        try:
            items = self._fetch_storage_items()
        except Exception as e:
            self.print_error(f"取得に失敗しました: {e}")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        selected = self._select_storage_ids(items, "deleted")
        if not selected:
            self.print_info("対象がありません")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        confirm = inquirer.confirm(
            message="完全削除は取り消しできません。続行しますか?",
            default=False,
            style=hacker_style,
        ).execute()
        if not confirm:
            self.print_info("キャンセルしました")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        confirm = inquirer.confirm(
            message=f"{len(selected)}件のストレージを完全削除しますか?",
            default=False,
            style=hacker_style,
        ).execute()
        if not confirm:
            self.print_info("キャンセルしました")
            self.wait_for_enter()
            return MenuResult.CONTINUE

        result = self._run_storage_action_ws("purge", selected)
        if "error" in result:
            self.print_error(f"完全削除に失敗しました: {result['error']}")
        else:
            self._print_action_result(result)

        self.wait_for_enter()
        return MenuResult.CONTINUE


class TrainingWizard(BaseMenu):
    """Training wizard - 7 step process for new training."""

    title = "新規学習"

    def __init__(self, app: "PhiApplication"):
        super().__init__(app)
        self.state = NewTrainingState()

    def get_choices(self) -> List[Choice]:
        # This menu runs as a wizard, not a choice menu
        return []

    def show(self) -> MenuResult:
        """Override show to run wizard flow instead of choice menu."""
        return self.run()

    def run(self) -> MenuResult:
        """Run the wizard steps."""
        steps = [
            ("Step 1/7: ポリシータイプ選択", self._step1_policy_type),
            ("Step 2/7: 事前学習済みモデル選択", self._step2_pretrained_model),
            ("Step 3/7: データセット選択", self._step3_dataset),
            ("Step 4/7: 学習パラメータ設定", self._step4_training_params),
            ("Step 5/7: Verda設定", self._step5_verda_settings),
            ("Step 6/7: ジョブ名設定", self._step6_job_naming),
            ("Step 7/7: 確認", self._step7_confirmation),
        ]

        current_step = 0
        skipped_steps: set[int] = set()  # Track skipped steps for back navigation

        while current_step < len(steps):
            step_name, step_func = steps[current_step]
            show_section_header(step_name)

            result = step_func()

            if result == "back":
                if current_step == 0:
                    return MenuResult.BACK
                current_step -= 1
                # Skip over previously skipped steps when going backward
                while current_step > 0 and current_step in skipped_steps:
                    current_step -= 1
            elif result == "skip":
                skipped_steps.add(current_step)  # Remember this step was skipped
                current_step += 1
            elif result == "next":
                skipped_steps.discard(current_step)  # Clear if completed normally
                current_step += 1
            elif result == "goto_verda":
                # Go back to Step 5 (Verda settings) - index 4
                current_step = 4
            elif result == "cancel":
                return MenuResult.BACK
            elif result == "done":
                return MenuResult.BACK

        return MenuResult.BACK

    def handle_choice(self, choice: Any) -> MenuResult:
        return MenuResult.CONTINUE

    def _step1_policy_type(self) -> str:
        """Step 1: Select policy type."""
        choices = []
        for key, info in POLICY_TYPES.items():
            choices.append(Choice(value=key, name=f"  {info.display_name}"))
        choices.append(Choice(value="__back__", name="← 戻る"))

        policy = inquirer.select(
            message="ポリシータイプを選択:",
            choices=choices,
            style=hacker_style,
        ).execute()

        if policy == "__back__":
            return "back"

        self.state.policy_type = policy
        policy_info = POLICY_TYPES[policy]
        self.state.skip_pretrained = policy_info.skip_pretrained
        self.state.steps = policy_info.default_steps
        self.state.batch_size = policy_info.default_batch_size
        self.state.save_freq = policy_info.default_save_freq
        self.state.storage_size = policy_info.recommended_storage
        self.state.torch_nightly = policy_info.torch_nightly

        return "next"

    def _step2_pretrained_model(self) -> str:
        """Step 2: Select pretrained model (conditional)."""
        if not self.state.policy_type:
            return "back"

        policy_info = POLICY_TYPES[self.state.policy_type]

        # Skip for policies that don't need pretrained model
        if policy_info.skip_pretrained:
            self.state.pretrained_path = None
            print(f"{Colors.muted('このポリシーは事前学習済みモデルを使用しません。')}")
            print(f"{Colors.muted('スキップして次へ進みます...')}")
            return "skip"

        if not policy_info.pretrained_models:
            self.state.pretrained_path = None
            return "skip"

        choices = []
        for model in policy_info.pretrained_models:
            desc = f" - {model.description}" if model.description else ""
            choices.append(Choice(value=model.path, name=f"  {model.name}{desc}"))
        choices.append(Choice(value="__custom__", name="  カスタムパスを入力..."))
        choices.append(Choice(value="__back__", name="← 戻る"))

        selection = inquirer.select(
            message="事前学習済みモデルを選択:",
            choices=choices,
            style=hacker_style,
        ).execute()

        if selection == "__back__":
            return "back"

        if selection == "__custom__":
            custom_path = inquirer.text(
                message="モデルパスを入力:",
                style=hacker_style,
            ).execute()
            if not custom_path:
                return "back"
            self.state.pretrained_path = custom_path
        else:
            self.state.pretrained_path = selection

        return "next"

    def _step3_dataset(self) -> str:
        """Step 3: Select dataset (2-stage: project -> session).

        Uses DB as the source of truth for available datasets.
        Stage 1: Select a project (top-level directory)
        Stage 2: Select a session within that project
        """
        # Stage 1: Select project
        project_result = self._step3a_select_project()
        if project_result in ("back", "cancel"):
            return project_result

        # Stage 2: Select session within project
        session_result = self._step3b_select_session()
        if session_result == "back":
            # Go back to project selection
            return self._step3_dataset()
        elif session_result == "cancel":
            return "back"

        return session_result

    def _step3a_select_project(self) -> str:
        """Step 3a: Select dataset project from DB."""
        print(f"{Colors.muted('DBからプロジェクト一覧を取得中...')}")

        try:
            result = self.api.list_datasets()
            datasets = result.get("datasets", [])
        except Exception as e:
            print(f"{Colors.error('プロジェクト取得エラー:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return "back"

        if not datasets:
            print(f"{Colors.warning('利用可能なデータセットがありません。')}")
            print(f"{Colors.muted('データを収録してR2にアップロードしてください。')}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return "back"

        project_stats = {}
        for d in datasets:
            if d.get("status") == "archived":
                continue
            project_id = d.get("project_id") or "unknown"
            stats = project_stats.setdefault(project_id, {"count": 0, "size": 0})
            stats["count"] += 1
            stats["size"] += d.get("size_bytes", 0)

        choices = []
        for project_id, stats in sorted(project_stats.items()):
            session_count = stats["count"]
            total_size = format_size(stats["size"])

            # Display format: project_name (N sessions, size)
            display = f"  {project_id} ({session_count} sessions, {total_size})"
            choices.append(Choice(value=project_id, name=display))

        choices.append(Choice(value="__back__", name="← 戻る"))

        project = inquirer.select(
            message="プロジェクトを選択:",
            choices=choices,
            style=hacker_style,
        ).execute()

        if project == "__back__":
            return "back"

        self.state.project_id = project
        return "next"

    def _step3b_select_session(self) -> str:
        """Step 3b: Select session within the selected project."""
        if not self.state.project_id:
            return "back"

        print(f"{Colors.muted(f'プロジェクト {self.state.project_id} のセッション一覧を取得中...')}")

        try:
            result = self.api.list_datasets()
            datasets = result.get("datasets", [])
        except Exception as e:
            print(f"{Colors.error('セッション取得エラー:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return "back"

        sessions = []
        for d in datasets:
            if d.get("status") == "archived":
                continue
            if d.get("project_id") != self.state.project_id:
                continue
            dataset_id = d.get("id") or ""
            dataset_type = d.get("dataset_type") or ""
            if dataset_type == "eval" or "/eval_" in dataset_id:
                continue
            sessions.append(d)

        if not sessions:
            print(f"{Colors.warning('このプロジェクトには利用可能なセッションがありません。')}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return "back"

        session_lookup = {}
        choices = []
        sessions = sorted(sessions, key=lambda s: s.get("created_at") or "", reverse=True)
        for s in sessions:
            dataset_id = s.get("id", "unknown")
            session_name = dataset_id.split("/")[-1] if "/" in dataset_id else dataset_id
            size = format_size(s.get("size_bytes", 0))
            episode_count = s.get("episode_count", 0)

            display = f"  {session_name} ({episode_count} eps, {size})"

            choices.append(Choice(value=dataset_id, name=display))
            session_lookup[dataset_id] = s

        choices.append(Choice(value="__back__", name="← 戻る (プロジェクト選択へ)"))

        session = inquirer.select(
            message="セッションを選択:",
            choices=choices,
            style=hacker_style,
        ).execute()

        if session == "__back__":
            self.state.project_id = None
            return "back"

        # Store selected dataset info
        self.state.dataset_id = session
        self.state.session_name = session.split("/")[-1] if "/" in session else session
        self.state.dataset_short_id = None

        return "next"

    def _step4_training_params(self) -> str:
        """Step 4: Training parameters."""
        print(f"{Colors.muted('現在の設定 (Enterでデフォルト値を使用)')}")
        print()

        try:
            steps = inquirer.number(
                message="Training steps:",
                default=self.state.steps,
                min_allowed=100,
                max_allowed=1000000,
                style=hacker_style,
            ).execute()
            self.state.steps = int(steps)

            batch_size = inquirer.number(
                message="Batch size:",
                default=self.state.batch_size,
                min_allowed=1,
                max_allowed=256,
                style=hacker_style,
            ).execute()
            self.state.batch_size = int(batch_size)

            save_freq_max = self.state.steps
            save_freq_default = max(min(self.state.save_freq, save_freq_max), 50)
            save_freq = inquirer.number(
                message="Save frequency (steps):",
                default=save_freq_default,
                min_allowed=50,
                max_allowed=save_freq_max,
                style=hacker_style,
            ).execute()
            self.state.save_freq = int(save_freq)

        except KeyboardInterrupt:
            return "back"

        # Confirm or go back
        action = inquirer.select(
            message="",
            choices=[
                Choice(value="next", name="次へ →"),
                Choice(value="back", name="← 戻る"),
            ],
            style=hacker_style,
        ).execute()

        return action

    def _step5_verda_settings(self) -> str:
        """Step 5: Verda cloud settings."""
        # Fetch GPU availability via WebSocket with real-time display
        gpu_availability = {}  # key: (gpu_model, gpu_count) -> {"spot": bool, "ondemand": bool}
        gpu_status = {name: "?" for name, _, _ in GPU_MODELS}  # Track status for each GPU

        def get_status_icon(gpu_name: str) -> str:
            """Get status icon for a GPU."""
            key = (gpu_name, 1)
            if key in gpu_availability:
                spot_ok = gpu_availability[key]["spot"]
                ondemand_ok = gpu_availability[key]["ondemand"]
                if spot_ok:
                    return "✓"
                elif ondemand_ok:
                    return "△"
                else:
                    return "✗"
            return gpu_status.get(gpu_name, "?")

        def print_gpu_status():
            """Print current GPU availability status."""
            status_parts = []
            for gpu_name, _, _ in GPU_MODELS:
                icon = get_status_icon(gpu_name)
                status_parts.append(f"{icon} {gpu_name}")
            return " | ".join(status_parts)

        try:
            # Use Rich Live for real-time updates
            console = Console()
            with Live(console=console, refresh_per_second=4, transient=True) as live:
                live.update(f"[dim]GPU空き状況を確認中... {print_gpu_status()}[/dim]")

                def on_checking(gpu_model: str) -> None:
                    gpu_status[gpu_model] = "…"
                    live.update(f"[dim]GPU空き状況を確認中... {print_gpu_status()}[/dim]")

                def on_result(gpu_model: str, gpu_count: int, spot_available: bool, ondemand_available: bool) -> None:
                    key = (gpu_model, gpu_count)
                    gpu_availability[key] = {
                        "spot": spot_available,
                        "ondemand": ondemand_available,
                    }
                    live.update(f"[dim]GPU空き状況を確認中... {print_gpu_status()}[/dim]")

                def on_error(error: str) -> None:
                    live.update(f"[yellow]⚠ GPU空き状況の取得に失敗: {error}[/yellow]")

                self.api.get_gpu_availability_ws(
                    on_checking=on_checking,
                    on_result=on_result,
                    on_error=on_error,
                )

            # Print final status
            print(f"{Colors.muted('GPU空き状況:')} {print_gpu_status()}")

        except Exception as e:
            print(f"{Colors.warning('⚠ GPU空き状況の取得に失敗:')} {e}")

        # GPU Model selection with availability indicators
        gpu_choices = []
        for gpu_name, gpu_desc, needs_nightly in GPU_MODELS:
            nightly_note = " ⚠" if needs_nightly else ""
            is_default = " (推奨)" if gpu_name == "H100" else ""

            # Check availability for this GPU (check count=1 as default indicator)
            # Priority: spot > ondemand > none > unknown
            avail_key = (gpu_name, 1)
            if avail_key in gpu_availability:
                spot_ok = gpu_availability[avail_key]["spot"]
                ondemand_ok = gpu_availability[avail_key]["ondemand"]
                if spot_ok:
                    avail_icon = "✓"  # Spot available (best - cheapest)
                elif ondemand_ok:
                    avail_icon = "△"  # On-demand only
                else:
                    avail_icon = "✗"  # Not available
            else:
                avail_icon = "?"  # Unknown

            gpu_choices.append(Choice(
                value=gpu_name,
                name=f"{avail_icon} {gpu_name}: {gpu_desc}{nightly_note}{is_default}"
            ))
        gpu_choices.append(Choice(value="__back__", name="← 戻る"))

        print(f"{Colors.muted('✓=スポット空き △=オンデマンドのみ ✗=空きなし ?=不明')}")
        gpu_model = inquirer.select(
            message="GPUモデル:",
            choices=gpu_choices,
            default="H100",
            style=hacker_style,
        ).execute()

        if gpu_model == "__back__":
            return "back"

        self.state.gpu_model = gpu_model

        # Auto-set torch_nightly for Blackwell GPUs
        for name, _, needs_nightly in GPU_MODELS:
            if name == gpu_model and needs_nightly:
                self.state.torch_nightly = True
                print(f"{Colors.warning('⚠ Blackwell GPUのため、torch nightlyを自動有効化します')}")
                break

        # GPU Count with availability indicators
        # Priority: spot > ondemand > none > unknown
        gpu_count_choices = []
        for n in GPU_COUNTS:
            avail_key = (gpu_model, n)
            if avail_key in gpu_availability:
                spot_ok = gpu_availability[avail_key]["spot"]
                ondemand_ok = gpu_availability[avail_key]["ondemand"]
                if spot_ok:
                    avail_icon = "✓"  # Spot available
                elif ondemand_ok:
                    avail_icon = "△"  # On-demand only
                else:
                    avail_icon = "✗"  # Not available
            else:
                avail_icon = "?"  # Unknown
            gpu_count_choices.append(Choice(
                value=n,
                name=f"{avail_icon} {n} GPU{'s' if n > 1 else ''}"
            ))

        gpu_count = inquirer.select(
            message="GPU数:",
            choices=gpu_count_choices,
            default=1,
            style=hacker_style,
        ).execute()
        self.state.gpu_count = gpu_count

        # Storage size
        try:
            storage = inquirer.number(
                message="ストレージサイズ (GB):",
                default=self.state.storage_size,
                min_allowed=50,
                max_allowed=1000,
                style=hacker_style,
            ).execute()
            self.state.storage_size = int(storage)
        except KeyboardInterrupt:
            return "back"

        # Instance type with availability check
        avail_key = (gpu_model, gpu_count)
        spot_available = gpu_availability.get(avail_key, {}).get("spot", True)
        ondemand_available = gpu_availability.get(avail_key, {}).get("ondemand", True)

        instance_choices = []
        spot_label = "  スポット (低コスト、中断リスクあり)"
        ondemand_label = "  オンデマンド (高コスト、安定)"

        if not spot_available:
            spot_label = "✗ スポット (現在空きなし)"
        if not ondemand_available:
            ondemand_label = "✗ オンデマンド (現在空きなし)"

        instance_choices.append(Choice(value=True, name=spot_label))
        instance_choices.append(Choice(value=False, name=ondemand_label))

        # Default to on-demand if spot not available
        default_is_spot = True if spot_available else False

        instance_type = inquirer.select(
            message="インスタンスタイプ:",
            choices=instance_choices,
            default=default_is_spot,
            style=hacker_style,
        ).execute()
        self.state.is_spot = instance_type

        # Warn if selected type is not available
        if instance_type and not spot_available:
            print(f"{Colors.warning('⚠ 選択したスポットインスタンスは現在空きがありません。')}")
            print(f"{Colors.warning('  ジョブ作成時にエラーになる可能性があります。')}")
        elif not instance_type and not ondemand_available:
            print(f"{Colors.warning('⚠ 選択したオンデマンドインスタンスは現在空きがありません。')}")
            print(f"{Colors.warning('  ジョブ作成時にエラーになる可能性があります。')}")

        # Confirm or go back
        action = inquirer.select(
            message="",
            choices=[
                Choice(value="next", name="次へ →"),
                Choice(value="back", name="← 戻る"),
            ],
            style=hacker_style,
        ).execute()

        return action

    def _step6_job_naming(self) -> str:
        """Step 6: Job naming."""
        suggested_name = self.state.generate_job_name()
        try:
            job_name = inquirer.text(
                message="ジョブ名 (空で自動提案):",
                default="",
                style=hacker_style,
            ).execute()
            job_name = job_name.strip()
            self.state.job_name = job_name or suggested_name

        except KeyboardInterrupt:
            return "back"

        # Generate and show preview
        print(f"\n{Colors.CYAN}プレビュー:{Colors.RESET}")
        print(f"  {self.state.job_name}")

        # Confirm or go back
        action = inquirer.select(
            message="",
            choices=[
                Choice(value="next", name="確認画面へ →"),
                Choice(value="back", name="← 戻る"),
            ],
            style=hacker_style,
        ).execute()

        return action

    def _step7_confirmation(self) -> str:
        """Step 7: Confirmation and start."""
        # Display summary
        print(f"\n{Colors.CYAN}=== 学習設定 ==={Colors.RESET}")
        print(f"  ポリシー: {POLICY_TYPES.get(self.state.policy_type, {}).display_name if self.state.policy_type else 'N/A'}")
        if self.state.pretrained_path:
            print(f"  事前学習: {self.state.pretrained_path}")
        print(f"  データセット: {self.state.dataset_id}")
        print(f"  ステップ数: {self.state.steps:,}")
        print(f"  バッチサイズ: {self.state.batch_size}")
        print(f"  保存頻度: {self.state.save_freq:,} steps")

        print(f"\n{Colors.CYAN}=== Verda設定 ==={Colors.RESET}")
        print(f"  GPU: {self.state.gpu_model} x {self.state.gpu_count}")
        print(f"  ストレージ: {self.state.storage_size}GB")
        print(f"  インスタンス: {'スポット' if self.state.is_spot else 'オンデマンド'}")
        if self.state.torch_nightly:
            print(f"  torch nightly: 有効")

        print(f"\n{Colors.CYAN}=== ジョブ名 ==={Colors.RESET}")
        print(f"  {self.state.job_name}")

        # Action selection
        action = inquirer.select(
            message="",
            choices=[
                Choice(value="start", name="🚀 学習を開始"),
                Choice(value="back", name="← 編集"),
                Choice(value="cancel", name="✕ キャンセル"),
            ],
            style=hacker_style,
        ).execute()

        if action == "back":
            return "back"
        if action == "cancel":
            return "cancel"

        # Start training
        return self._start_training()

    def _start_training(self) -> str:
        """Start the training job with real-time progress via WebSocket."""
        # Build request payload
        policy_info = POLICY_TYPES.get(self.state.policy_type, PolicyTypeInfo(display_name=""))

        payload = {
            "job_name": self.state.job_name,
            "dataset": {
                "id": self.state.dataset_id,
                "source": "r2",
            },
            "policy": {
                "type": self.state.policy_type,
            },
            "training": {
                "steps": self.state.steps,
                "batch_size": self.state.batch_size,
                "save_freq": self.state.save_freq,
            },
            "cloud": {
                "gpu_model": self.state.gpu_model,
                "gpus_per_instance": self.state.gpu_count,
                "storage_size": self.state.storage_size,
                "is_spot": self.state.is_spot,
            },
            "wandb_enable": True,
        }

        # Add pretrained path if specified
        if self.state.pretrained_path:
            payload["policy"]["pretrained_path"] = self.state.pretrained_path

        # Add policy-specific settings
        if policy_info.compile_model is not None:
            payload["policy"]["compile_model"] = policy_info.compile_model
        if policy_info.gradient_checkpointing is not None:
            payload["policy"]["gradient_checkpointing"] = policy_info.gradient_checkpointing
        if policy_info.dtype:
            payload["policy"]["dtype"] = policy_info.dtype

        # Progress state for Rich Live display
        console = Console()
        # Progress phases for visual feedback
        PHASES = [
            ("validating", "1. 設定検証"),
            ("selecting", "2. インスタンス選択"),
            ("creating", "3. インスタンス作成"),
            ("waiting_ip", "4. IP割り当て待機"),
            ("connecting", "5. SSH接続"),
            ("deploying", "6. ファイル転送"),
            ("starting", "7. 学習開始"),
        ]

        current = {
            "phase_index": 0,
            "phase_name": "",
            "message": "",
            "elapsed": 0,
            "timeout": 0,
            "attempt": 0,
            "max_attempts": 0,
            "instance_type": "",
            "location": "",
            "instance_id": "",
            "ip": "",
            "file": "",
            "files_uploaded": 0,
            "training_logs": [],  # Recent log lines from training startup
        }

        def make_progress_panel():
            """Create progress panel for Live display."""
            table = Table(show_header=False, box=None, padding=(0, 1))
            table.add_column("Label", style="cyan", width=14)
            table.add_column("Value")

            table.add_row("ジョブ名:", self.state.job_name or "")

            # Show phase progress bar
            phase_idx = current["phase_index"]
            phase_bar = ""
            for i, (_, name) in enumerate(PHASES):
                if i < phase_idx:
                    phase_bar += "✓ "
                elif i == phase_idx:
                    phase_bar += "● "
                else:
                    phase_bar += "○ "
            table.add_row("進捗:", phase_bar.strip())

            # Current phase and message
            if current["phase_name"]:
                table.add_row("フェーズ:", current["phase_name"])
            table.add_row("状態:", current["message"] or "...")

            # Instance info
            if current.get("instance_type"):
                table.add_row("インスタンス:", current["instance_type"])
            if current.get("location"):
                table.add_row("ロケーション:", current["location"])
            if current.get("instance_id"):
                table.add_row("インスタンスID:", current["instance_id"][:16] + "...")

            # Waiting indicator with progress bar
            if current.get("elapsed") and current.get("timeout"):
                elapsed = current["elapsed"]
                timeout = current["timeout"]
                pct = min((elapsed / timeout) * 100, 100)
                bar_len = 20
                filled = int(bar_len * pct / 100)
                bar = "█" * filled + "░" * (bar_len - filled)
                table.add_row("待機:", f"[{bar}] {elapsed}s/{timeout}s")

            # SSH attempts
            if current.get("attempt") and current.get("max_attempts"):
                attempt = current["attempt"]
                max_attempts = current["max_attempts"]
                table.add_row("SSH試行:", f"{attempt}/{max_attempts}")

            # IP
            if current.get("ip"):
                table.add_row("IP:", current["ip"])

            # File upload progress
            if current.get("file"):
                table.add_row("転送中:", current["file"])
            if current.get("files_uploaded"):
                table.add_row("転送済み:", f"{current['files_uploaded']}ファイル")

            # Training startup logs (real-time)
            if current.get("training_logs"):
                table.add_row("", "")  # Spacer
                table.add_row("セットアップログ:", "[dim]リアルタイム[/dim]")
                for log_line in current["training_logs"][-3:]:  # Show last 3 lines
                    # Truncate long lines
                    display_line = log_line[:60] + "..." if len(log_line) > 60 else log_line
                    table.add_row("", f"[dim]{display_line}[/dim]")

            return Panel(table, title="🚀 ジョブ作成中", border_style="cyan")

        def progress_callback(data: Dict[str, Any]) -> None:
            """Handle progress updates from WebSocket."""
            msg_type = data.get("type", "")
            current["message"] = data.get("message", "")

            # Update phase based on message type
            if msg_type in ("start", "validating", "validated"):
                current["phase_index"] = 0
                current["phase_name"] = "設定検証"
            elif msg_type in ("selecting_instance", "instance_selected", "getting_ssh_key", "finding_location", "location_found"):
                current["phase_index"] = 1
                current["phase_name"] = "インスタンス選択"
            elif msg_type in ("creating_instance", "instance_created"):
                current["phase_index"] = 2
                current["phase_name"] = "インスタンス作成"
            elif msg_type in ("waiting_ip", "ip_assigned"):
                current["phase_index"] = 3
                current["phase_name"] = "IP割り当て待機"
            elif msg_type in ("connecting_ssh", "ssh_ready"):
                current["phase_index"] = 4
                current["phase_name"] = "SSH接続"
            elif msg_type == "deploying":
                current["phase_index"] = 5
                current["phase_name"] = "ファイル転送"
            elif msg_type == "starting_training":
                current["phase_index"] = 6
                current["phase_name"] = "学習開始"

            # Handle specific data
            if msg_type == "instance_selected":
                current["instance_type"] = data.get("instance_type", "")
            elif msg_type == "location_found":
                current["location"] = data.get("location", "")
            elif msg_type == "instance_created":
                current["instance_id"] = data.get("instance_id", "")
            elif msg_type == "waiting_ip":
                current["elapsed"] = data.get("elapsed", 0)
                current["timeout"] = data.get("timeout", 900)
            elif msg_type == "ip_assigned":
                current["ip"] = data.get("ip", "")
                current["elapsed"] = 0
                current["timeout"] = 0
            elif msg_type == "connecting_ssh":
                current["attempt"] = data.get("attempt", 0)
                current["max_attempts"] = data.get("max_attempts", 30)
                if "elapsed" in data:
                    current["elapsed"] = data["elapsed"]
                    current["timeout"] = 300
            elif msg_type == "ssh_ready":
                current["attempt"] = 0
                current["max_attempts"] = 0
                current["elapsed"] = 0
                current["timeout"] = 0
            elif msg_type == "deploying":
                current["file"] = data.get("file", "")
                current["files_uploaded"] += 1
            elif msg_type == "starting_training":
                current["file"] = ""  # Clear file info
            elif msg_type == "training_log":
                # Append log line (keep last 10 for memory efficiency)
                current["training_logs"].append(data.get("message", ""))
                if len(current["training_logs"]) > 10:
                    current["training_logs"] = current["training_logs"][-10:]

        try:
            with Live(make_progress_panel(), console=console, refresh_per_second=4) as live:
                def update_display(data: Dict[str, Any]) -> None:
                    progress_callback(data)
                    live.update(make_progress_panel())

                result = self.api.create_training_job_ws(payload, update_display)

            # Check result
            if result.get("type") == "complete":
                job_id = result.get("job_id", "")
                print(f"\n{Colors.success('✓ 学習ジョブを開始しました!')}")
                print(f"  ジョブID: {job_id}")
                print(f"  インスタンスID: {result.get('instance_id', 'N/A')}")
                print(f"  IP: {result.get('ip', 'N/A')}")
                print(f"  ステータス: {result.get('status', 'running')}")

                # Ask if user wants to stream logs
                if job_id:
                    stream = inquirer.confirm(
                        message="学習ログをストリーミングしますか? (Ctrl+Cで終了)",
                        default=True,
                        style=hacker_style,
                    ).execute()

                    if stream:
                        self._stream_logs_after_create(job_id)
                        return "done"

            elif result.get("type") == "error":
                error_msg = result.get("error", "Unknown error")
                print(f"\n{Colors.error('エラー:')} {error_msg}")

                # Check if it's a GPU availability error
                if "No Spot instance available" in error_msg or "No instance available" in error_msg.lower():
                    # Offer to go back to GPU selection
                    action = inquirer.select(
                        message="",
                        choices=[
                            Choice(value="goto_verda", name="🔧 GPU設定へ戻る"),
                            Choice(value="cancel", name="✕ 中止"),
                        ],
                        style=hacker_style,
                    ).execute()
                    return action
            else:
                print(f"\n{Colors.warning('予期しない結果:')} {result}")

        except Exception as e:
            error_str = str(e)
            print(f"\n{Colors.error('エラー:')} {error_str}")

            # Check if it's a GPU availability error
            if "No Spot instance available" in error_str or "No instance available" in error_str.lower():
                # Offer to go back to GPU selection
                action = inquirer.select(
                    message="",
                    choices=[
                        Choice(value="goto_verda", name="🔧 GPU設定へ戻る"),
                        Choice(value="cancel", name="✕ 中止"),
                    ],
                    style=hacker_style,
                ).execute()
                return action

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return "done"

    def _stream_logs_after_create(self, job_id: str) -> None:
        """Stream logs after job creation via WebSocket."""
        print(f"\n{Colors.CYAN}ログストリーミング中... (Ctrl+Cで終了){Colors.RESET}\n")

        def on_log(line: str) -> None:
            print(f"  {line}")

        def on_status(status: str, message: str) -> None:
            if status == "connected":
                print(f"{Colors.success('SSH接続完了')}\n")
            else:
                print(f"\n{Colors.info(message)}")

        def on_error(error: str) -> None:
            print(f"\n{Colors.error('エラー:')} {error}")

        try:
            self.api.stream_training_job_logs_ws(
                job_id,
                on_log=on_log,
                on_status=on_status,
                on_error=on_error,
            )
        except KeyboardInterrupt:
            print(f"\n{Colors.muted('ストリーミング終了')}")


# =============================================================================
# Continue Training Wizard (6 Steps)
# =============================================================================


class ContinueTrainingWizard(BaseMenu):
    """Continue training wizard - 6 step process."""

    title = "継続学習"

    def __init__(self, app: "PhiApplication"):
        super().__init__(app)
        self.state = ContinueTrainingState()

    def get_choices(self) -> List[Choice]:
        return []

    def show(self) -> MenuResult:
        """Override show to run wizard flow instead of choice menu."""
        return self.run()

    def run(self) -> MenuResult:
        """Run the wizard steps."""
        steps = [
            ("Step 1/6: ポリシータイプフィルター", self._step1_policy_filter),
            ("Step 2/6: チェックポイント選択", self._step2_checkpoint_selection),
            ("Step 3/6: データセット選択", self._step3_dataset_selection),
            ("Step 4/6: 追加学習パラメータ", self._step4_training_params),
            ("Step 5/6: Verda設定", self._step5_verda_settings),
            ("Step 6/6: 確認", self._step6_confirmation),
        ]

        current_step = 0
        while current_step < len(steps):
            step_name, step_func = steps[current_step]
            show_section_header(step_name)

            result = step_func()

            if result == "back":
                if current_step == 0:
                    return MenuResult.BACK
                current_step -= 1
            elif result == "next":
                current_step += 1
            elif result == "goto_verda":
                # Go back to Step 5 (Verda settings) - index 4
                current_step = 4
            elif result == "cancel":
                return MenuResult.BACK
            elif result == "done":
                return MenuResult.BACK

        return MenuResult.BACK

    def handle_choice(self, choice: Any) -> MenuResult:
        return MenuResult.CONTINUE

    def _step1_policy_filter(self) -> str:
        """Step 1: Policy type filter."""
        choices = [Choice(value=None, name="  すべて表示")]
        for key, info in POLICY_TYPES.items():
            choices.append(Choice(value=key, name=f"  {info.display_name}"))
        choices.append(Choice(value="__back__", name="← 戻る"))

        policy_filter = inquirer.select(
            message="ポリシータイプでフィルター:",
            choices=choices,
            style=hacker_style,
        ).execute()

        if policy_filter == "__back__":
            return "back"

        self.state.policy_filter = policy_filter
        return "next"

    def _step2_checkpoint_selection(self) -> str:
        """Step 2: Checkpoint selection."""
        try:
            result = self.api.list_training_checkpoints(
                policy_type=self.state.policy_filter
            )
            checkpoints = result.get("checkpoints", [])
        except Exception as e:
            print(f"{Colors.error('チェックポイント取得エラー:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return "back"

        if not checkpoints:
            print(f"{Colors.warning('利用可能なチェックポイントがありません。')}")
            if self.state.policy_filter:
                print(f"{Colors.muted('フィルターを変更するか、新規学習を行ってください。')}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return "back"

        # Display checkpoint table
        print(f"\n{Colors.muted('ポリシー    モデル名                      ステップ      作成日時')}")
        print(f"{Colors.muted('─' * 70)}")

        choices = []
        for cp in checkpoints[:20]:
            job_name = cp.get("job_name", "unknown")
            policy_type = cp.get("policy_type", "?")
            step = cp.get("step", 0)
            created_at = cp.get("created_at", "")[:10]
            dataset_id = cp.get("dataset_id", "")

            # Format display
            policy_display = policy_type[:10].ljust(10)
            job_display = job_name[:30].ljust(30)
            step_display = f"{step:,}".rjust(12)

            choices.append(Choice(
                value=job_name,
                name=f"  {policy_display} {job_display} {step_display}  {created_at}"
            ))

        choices.append(Choice(value="__back__", name="← 戻る"))

        selection = inquirer.select(
            message="チェックポイントを選択:",
            choices=choices,
            style=hacker_style,
        ).execute()

        if selection == "__back__":
            return "back"

        # Get checkpoint details
        selected_cp = next((cp for cp in checkpoints if cp.get("job_name") == selection), None)
        if selected_cp:
            self.state.checkpoint_job_name = selection
            self.state.checkpoint_step = selected_cp.get("step", 0)
            self.state.checkpoint_policy_type = selected_cp.get("policy_type")
            self.state.original_dataset_id = selected_cp.get("dataset_id")

            # Set defaults based on checkpoint
            if self.state.checkpoint_policy_type:
                policy_info = POLICY_TYPES.get(self.state.checkpoint_policy_type, PolicyTypeInfo(display_name=""))
                self.state.batch_size = policy_info.default_batch_size
                self.state.save_freq = policy_info.default_save_freq
                self.state.storage_size = policy_info.recommended_storage

        return "next"

    def _step3_dataset_selection(self) -> str:
        """Step 3: Dataset selection with compatibility check."""
        choices = [
            Choice(
                value="original",
                name=f"  元のデータセットを使用 ({self.state.original_dataset_id})"
            ),
            Choice(value="new", name="  新しいデータセットを指定"),
            Choice(value="__back__", name="← 戻る"),
        ]

        selection = inquirer.select(
            message="データセット:",
            choices=choices,
            style=hacker_style,
        ).execute()

        if selection == "__back__":
            return "back"

        if selection == "original":
            self.state.use_original_dataset = True
            self.state.dataset_id = self.state.original_dataset_id
            # Get short_id for original dataset from API
            try:
                datasets = self.api.list_datasets()
                ds_list = datasets.get("datasets", [])
                for d in ds_list:
                    if isinstance(d, dict) and d.get("id") == self.state.original_dataset_id:
                        self.state.dataset_short_id = d.get("short_id")
                        break
            except Exception:
                pass  # Will use None if not found
            return "next"

        # New dataset selection
        self.state.use_original_dataset = False

        try:
            datasets = self.api.list_datasets()
            ds_list = datasets.get("datasets", [])
        except Exception as e:
            print(f"{Colors.error('データセット取得エラー:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return "back"

        if not ds_list:
            print(f"{Colors.warning('利用可能なデータセットがありません。')}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return "back"

        ds_lookup = {}
        ds_choices = []
        for d in ds_list:
            if isinstance(d, dict):
                ds_id = d.get("id", "unknown")
                size = format_size(d.get("size_bytes", 0))
                ds_choices.append(Choice(value=ds_id, name=f"  {ds_id} ({size})"))
                ds_lookup[ds_id] = d

        ds_choices.append(Choice(value="__back__", name="← 戻る"))

        dataset = inquirer.select(
            message="データセットを選択:",
            choices=ds_choices,
            style=hacker_style,
        ).execute()

        if dataset == "__back__":
            return "back"

        # Compatibility check
        print(f"\n{Colors.CYAN}互換性チェック実行中...{Colors.RESET}")
        try:
            compat_result = self.api.check_dataset_compatibility(
                checkpoint_job_name=self.state.checkpoint_job_name,
                dataset_id=dataset
            )

            is_compatible = compat_result.get("is_compatible", False)
            errors = compat_result.get("errors", [])
            warnings = compat_result.get("warnings", [])

            if errors:
                print(f"\n{Colors.error('❌ 互換性エラー')}")
                for err in errors:
                    print(f"  • {err}")
                print(f"\n{Colors.muted('このデータセットは継続学習に使用できません。')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return "back"

            if warnings:
                print(f"\n{Colors.warning('⚠ 警告')}")
                for warn in warnings:
                    print(f"  • {warn}")

                proceed = inquirer.confirm(
                    message="続行しますか?",
                    default=True,
                    style=hacker_style,
                ).execute()

                if not proceed:
                    return "back"
            else:
                print(f"{Colors.success('✓ 互換性チェック: OK')}")

        except Exception as e:
            print(f"{Colors.warning('⚠ 互換性チェックをスキップします:')} {e}")

        self.state.dataset_id = dataset
        # Get short_id from dataset info for job naming
        ds_info = ds_lookup.get(dataset, {})
        self.state.dataset_short_id = ds_info.get("short_id")
        return "next"

    def _step4_training_params(self) -> str:
        """Step 4: Training parameters."""
        print(f"{Colors.muted(f'現在のステップ: {self.state.checkpoint_step:,}')}")
        print()

        try:
            additional = inquirer.number(
                message="追加ステップ数:",
                default=self.state.additional_steps,
                min_allowed=100,
                max_allowed=1000000,
                style=hacker_style,
            ).execute()
            self.state.additional_steps = int(additional)

            total_steps = self.state.checkpoint_step + self.state.additional_steps
            print(f"{Colors.muted(f'  → 合計: {total_steps:,} ステップ')}")

            batch_size = inquirer.number(
                message="Batch size:",
                default=self.state.batch_size,
                min_allowed=1,
                max_allowed=256,
                style=hacker_style,
            ).execute()
            self.state.batch_size = int(batch_size)

            save_freq_max = self.state.additional_steps
            save_freq_default = max(min(self.state.save_freq, save_freq_max), 50)
            save_freq = inquirer.number(
                message="Save frequency (steps):",
                default=save_freq_default,
                min_allowed=50,
                max_allowed=save_freq_max,
                style=hacker_style,
            ).execute()
            self.state.save_freq = int(save_freq)

        except KeyboardInterrupt:
            return "back"

        action = inquirer.select(
            message="",
            choices=[
                Choice(value="next", name="次へ →"),
                Choice(value="back", name="← 戻る"),
            ],
            style=hacker_style,
        ).execute()

        return action

    def _step5_verda_settings(self) -> str:
        """Step 5: Verda settings."""
        # Fetch GPU availability via WebSocket with real-time display
        gpu_availability = {}  # key: (gpu_model, gpu_count) -> {"spot": bool, "ondemand": bool}
        gpu_status = {name: "?" for name, _, _ in GPU_MODELS}  # Track status for each GPU

        def get_status_icon(gpu_name: str) -> str:
            """Get status icon for a GPU."""
            key = (gpu_name, 1)
            if key in gpu_availability:
                spot_ok = gpu_availability[key]["spot"]
                ondemand_ok = gpu_availability[key]["ondemand"]
                if spot_ok:
                    return "✓"
                elif ondemand_ok:
                    return "△"
                else:
                    return "✗"
            return gpu_status.get(gpu_name, "?")

        def print_gpu_status():
            """Print current GPU availability status."""
            status_parts = []
            for gpu_name, _, _ in GPU_MODELS:
                icon = get_status_icon(gpu_name)
                status_parts.append(f"{icon} {gpu_name}")
            return " | ".join(status_parts)

        try:
            # Use Rich Live for real-time updates
            console = Console()
            with Live(console=console, refresh_per_second=4, transient=True) as live:
                live.update(f"[dim]GPU空き状況を確認中... {print_gpu_status()}[/dim]")

                def on_checking(gpu_model: str) -> None:
                    gpu_status[gpu_model] = "…"
                    live.update(f"[dim]GPU空き状況を確認中... {print_gpu_status()}[/dim]")

                def on_result(gpu_model: str, gpu_count: int, spot_available: bool, ondemand_available: bool) -> None:
                    key = (gpu_model, gpu_count)
                    gpu_availability[key] = {
                        "spot": spot_available,
                        "ondemand": ondemand_available,
                    }
                    live.update(f"[dim]GPU空き状況を確認中... {print_gpu_status()}[/dim]")

                def on_error(error: str) -> None:
                    live.update(f"[yellow]⚠ GPU空き状況の取得に失敗: {error}[/yellow]")

                self.api.get_gpu_availability_ws(
                    on_checking=on_checking,
                    on_result=on_result,
                    on_error=on_error,
                )

            # Print final status
            print(f"{Colors.muted('GPU空き状況:')} {print_gpu_status()}")

        except Exception as e:
            print(f"{Colors.warning('⚠ GPU空き状況の取得に失敗:')} {e}")

        # GPU Model selection with availability indicators
        # Priority: spot > ondemand > none > unknown
        gpu_choices = []
        for gpu_name, gpu_desc, needs_nightly in GPU_MODELS:
            nightly_note = " ⚠" if needs_nightly else ""
            is_default = " (推奨)" if gpu_name == "H100" else ""

            # Check availability for this GPU (check count=1 as default indicator)
            avail_key = (gpu_name, 1)
            if avail_key in gpu_availability:
                spot_ok = gpu_availability[avail_key]["spot"]
                ondemand_ok = gpu_availability[avail_key]["ondemand"]
                if spot_ok:
                    avail_icon = "✓"  # Spot available (best - cheapest)
                elif ondemand_ok:
                    avail_icon = "△"  # On-demand only
                else:
                    avail_icon = "✗"  # Not available
            else:
                avail_icon = "?"  # Unknown

            gpu_choices.append(Choice(
                value=gpu_name,
                name=f"{avail_icon} {gpu_name}: {gpu_desc}{nightly_note}{is_default}"
            ))
        gpu_choices.append(Choice(value="__back__", name="← 戻る"))

        print(f"{Colors.muted('✓=スポット空き △=オンデマンドのみ ✗=空きなし ?=不明')}")
        gpu_model = inquirer.select(
            message="GPUモデル:",
            choices=gpu_choices,
            default="H100",
            style=hacker_style,
        ).execute()

        if gpu_model == "__back__":
            return "back"

        self.state.gpu_model = gpu_model

        # Auto-set torch_nightly for Blackwell GPUs
        for name, _, needs_nightly in GPU_MODELS:
            if name == gpu_model and needs_nightly:
                self.state.torch_nightly = True
                print(f"{Colors.warning('⚠ Blackwell GPUのため、torch nightlyを自動有効化します')}")
                break

        # GPU Count with availability indicators
        # Priority: spot > ondemand > none > unknown
        gpu_count_choices = []
        for n in GPU_COUNTS:
            avail_key = (gpu_model, n)
            if avail_key in gpu_availability:
                spot_ok = gpu_availability[avail_key]["spot"]
                ondemand_ok = gpu_availability[avail_key]["ondemand"]
                if spot_ok:
                    avail_icon = "✓"  # Spot available
                elif ondemand_ok:
                    avail_icon = "△"  # On-demand only
                else:
                    avail_icon = "✗"  # Not available
            else:
                avail_icon = "?"  # Unknown
            gpu_count_choices.append(Choice(
                value=n,
                name=f"{avail_icon} {n} GPU{'s' if n > 1 else ''}"
            ))

        gpu_count = inquirer.select(
            message="GPU数:",
            choices=gpu_count_choices,
            default=1,
            style=hacker_style,
        ).execute()
        self.state.gpu_count = gpu_count

        # Storage size
        try:
            storage = inquirer.number(
                message="ストレージサイズ (GB):",
                default=self.state.storage_size,
                min_allowed=50,
                max_allowed=1000,
                style=hacker_style,
            ).execute()
            self.state.storage_size = int(storage)
        except KeyboardInterrupt:
            return "back"

        # Instance type with availability check
        avail_key = (gpu_model, gpu_count)
        spot_available = gpu_availability.get(avail_key, {}).get("spot", True)
        ondemand_available = gpu_availability.get(avail_key, {}).get("ondemand", True)

        instance_choices = []
        spot_label = "  スポット (低コスト、中断リスクあり)"
        ondemand_label = "  オンデマンド (高コスト、安定)"

        if not spot_available:
            spot_label = "✗ スポット (現在空きなし)"
        if not ondemand_available:
            ondemand_label = "✗ オンデマンド (現在空きなし)"

        instance_choices.append(Choice(value=True, name=spot_label))
        instance_choices.append(Choice(value=False, name=ondemand_label))

        # Default to on-demand if spot not available
        default_is_spot = True if spot_available else False

        instance_type = inquirer.select(
            message="インスタンスタイプ:",
            choices=instance_choices,
            default=default_is_spot,
            style=hacker_style,
        ).execute()
        self.state.is_spot = instance_type

        # Warn if selected type is not available
        if instance_type and not spot_available:
            print(f"{Colors.warning('⚠ 選択したスポットインスタンスは現在空きがありません。')}")
            print(f"{Colors.warning('  ジョブ作成時にエラーになる可能性があります。')}")
        elif not instance_type and not ondemand_available:
            print(f"{Colors.warning('⚠ 選択したオンデマンドインスタンスは現在空きがありません。')}")
            print(f"{Colors.warning('  ジョブ作成時にエラーになる可能性があります。')}")

        action = inquirer.select(
            message="",
            choices=[
                Choice(value="next", name="次へ →"),
                Choice(value="back", name="← 戻る"),
            ],
            style=hacker_style,
        ).execute()

        return action

    def _step6_confirmation(self) -> str:
        """Step 6: Confirmation and start."""
        total_steps = self.state.checkpoint_step + self.state.additional_steps

        print(f"\n{Colors.CYAN}=== 継続学習設定 ==={Colors.RESET}")
        print(f"  ベースモデル: {self.state.checkpoint_job_name}")
        print(f"  現在ステップ: {self.state.checkpoint_step:,}")
        print(f"  データセット: {self.state.dataset_id}")
        print(f"  追加ステップ: {self.state.additional_steps:,}")
        print(f"  最終ステップ: {total_steps:,}")
        print(f"  バッチサイズ: {self.state.batch_size}")

        print(f"\n{Colors.CYAN}=== Verda設定 ==={Colors.RESET}")
        print(f"  GPU: {self.state.gpu_model} x {self.state.gpu_count}")
        print(f"  ストレージ: {self.state.storage_size}GB")
        print(f"  インスタンス: {'スポット' if self.state.is_spot else 'オンデマンド'}")

        action = inquirer.select(
            message="",
            choices=[
                Choice(value="start", name="🚀 学習を開始"),
                Choice(value="back", name="← 編集"),
                Choice(value="cancel", name="✕ キャンセル"),
            ],
            style=hacker_style,
        ).execute()

        if action == "back":
            return "back"
        if action == "cancel":
            return "cancel"

        return self._start_continue_training()

    def _start_continue_training(self) -> str:
        """Start the continue training job."""
        try:
            payload = {
                "type": "continue",
                "checkpoint": {
                    "job_name": self.state.checkpoint_job_name,
                    "step": self.state.checkpoint_step,
                },
                "dataset": {
                    "id": self.state.dataset_id,
                    "use_original": self.state.use_original_dataset,
                },
                "training": {
                    "additional_steps": self.state.additional_steps,
                    "batch_size": self.state.batch_size,
                    "save_freq": self.state.save_freq,
                },
                "cloud": {
                    "gpu_model": self.state.gpu_model,
                    "gpus_per_instance": self.state.gpu_count,
                    "storage_size": self.state.storage_size,
                    "is_spot": self.state.is_spot,
                },
            }

            result = self.api.create_continue_training_job(payload)

            print(f"\n{Colors.success('✓ 継続学習ジョブを開始しました!')}")
            print(f"  ジョブID: {result.get('job_id', 'N/A')}")
            print(f"  ステータス: {result.get('status', 'starting')}")

        except Exception as e:
            error_str = str(e)
            print(f"\n{Colors.error('エラー:')} {error_str}")

            # Check if it's a GPU availability error
            if "No Spot instance available" in error_str or "No instance available" in error_str.lower():
                # Offer to go back to GPU selection
                action = inquirer.select(
                    message="",
                    choices=[
                        Choice(value="goto_verda", name="🔧 GPU設定へ戻る"),
                        Choice(value="cancel", name="✕ 中止"),
                    ],
                    style=hacker_style,
                ).execute()
                return action

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return "done"


# =============================================================================
# Training Jobs Menu (Existing functionality preserved)
# =============================================================================


class TrainingJobsMenu(BaseMenu):
    """View and manage training jobs."""

    title = "学習ジョブ"

    def get_choices(self) -> List[Choice]:
        choices = []
        try:
            result = self.api.list_training_jobs()
            jobs = result.get("jobs", [])
            for job in jobs[:15]:
                job_id = job.get("job_id", "unknown")
                job_name = job.get("job_name") or job_id
                status = job.get("status", "unknown")
                gpu_model = job.get("gpu_model", "")
                gpu_count = job.get("gpus_per_instance") or job.get("gpu_count") or 1
                status_icon = self._status_icon(status)

                # Build display string
                running_time = self._running_time(job)
                gpu_info = f"{gpu_model}x{gpu_count}" if gpu_model else ""
                name_display = job_name[:28] + "..." if len(job_name) > 31 else job_name
                display_parts = [status_icon, name_display]
                if gpu_info:
                    display_parts.append(f"[{gpu_info}]")
                display_parts.append(running_time)
                display_parts.append(f"({status})")
                display = " ".join(display_parts)

                choices.append(Choice(value=job_id, name=display))
        except Exception:
            pass

        if not choices:
            choices.append(Choice(value="__none__", name="(学習ジョブなし)"))

        choices.append(Choice(value="__refresh__", name="🔄 更新"))
        choices.append(Choice(value="__check_all__", name="📊 全ステータス確認"))

        return choices

    def _status_icon(self, status: str) -> str:
        """Get status icon (no ANSI colors - InquirerPy doesn't support them in Choice.name)."""
        icons = {
            "starting": "◐",
            "deploying": "◑",
            "running": "🔄",
            "completed": "✓",
            "failed": "✗",
            "stopped": "◌",
            "terminated": "◌",
        }
        return icons.get(status, "?")

    def _parse_timestamp(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
        if parsed.tzinfo:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    def _format_duration(self, seconds: float) -> str:
        total = int(max(0, seconds))
        if total < 60:
            return f"{total}s"
        minutes = total // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        minutes = minutes % 60
        if hours < 24:
            return f"{hours}h{minutes:02d}m"
        days = hours // 24
        hours = hours % 24
        return f"{days}d{hours:02d}h"

    def _running_time(self, job: dict) -> str:
        status = job.get("status")
        started_at = self._parse_timestamp(job.get("started_at"))
        created_at = self._parse_timestamp(job.get("created_at"))
        completed_at = self._parse_timestamp(job.get("completed_at"))
        start = started_at or created_at
        if not start:
            return "N/A"
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if status in ("completed", "failed", "stopped", "terminated") and completed_at:
            end = completed_at
        else:
            end = now
        if end < start:
            end = start
        return self._format_duration((end - start).total_seconds())

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "__none__":
            return MenuResult.BACK
        if choice == "__refresh__":
            return MenuResult.CONTINUE
        if choice == "__check_all__":
            return self._check_all_status()

        return self._show_job_detail(choice)

    def _check_all_status(self) -> MenuResult:
        """Check status of all jobs."""
        show_section_header("全ジョブステータス確認")

        try:
            result = self.api.check_training_jobs_status()
            updates = result.get("updates", [])
            checked = result.get("checked_count", 0)

            print(f"{Colors.success('ステータス確認完了')}")
            print(f"  確認: {checked} ジョブ")
            print(f"  更新: {len(updates)} ジョブ")

            if updates:
                print(f"\n{Colors.CYAN}更新されたジョブ:{Colors.RESET}")
                for update in updates[:10]:
                    print(f"  {update.get('job_id', '')}: {update.get('old_status')} → {update.get('new_status')}")

        except Exception as e:
            print(f"{Colors.error('エラー:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_job_detail(self, job_id: str) -> MenuResult:
        """Show job details and actions."""
        show_section_header("学習ジョブ詳細")

        try:
            result = self.api.get_training_job(job_id)
            job_info = result.get("job", {})
            training_config = result.get("training_config") or {}
            summary = result.get("summary") or {}
            early_stopping = result.get("early_stopping") or {}
            latest_train = result.get("latest_train_metrics")
            latest_val = result.get("latest_val_metrics")

            print(f"  ID: {job_info.get('job_id', 'N/A')}")
            print(f"  ジョブ名: {job_info.get('job_name', 'N/A')}")
            print(f"  ステータス: {job_info.get('status', 'N/A')}")
            print(f"  モード: {job_info.get('mode', 'train')}")
            if job_info.get("gpu_model"):
                gpu_count = job_info.get("gpus_per_instance") or job_info.get("gpu_count", 1)
                print(f"  GPU: {job_info.get('gpu_model')} x {gpu_count}")
            if job_info.get("ip"):
                print(f"  IP: {job_info.get('ip')}")
            if job_info.get("dataset_id"):
                print(f"  データセット: {job_info.get('dataset_id')}")
            if job_info.get("policy_type"):
                print(f"  ポリシー: {job_info.get('policy_type')}")
            print(f"  作成: {job_info.get('created_at', 'N/A')}")
            if job_info.get("started_at"):
                print(f"  開始: {job_info.get('started_at')}")
            running_time = self._running_time(job_info)
            if running_time != "N/A":
                print(f"  経過: {running_time}")
            if job_info.get("failure_reason"):
                print(f"  失敗理由: {job_info.get('failure_reason')}")
            if job_info.get("termination_reason"):
                print(f"  終了理由: {job_info.get('termination_reason')}")
            if job_info.get("cleanup_status"):
                print(f"  後処理: {job_info.get('cleanup_status')}")
            if job_info.get("deleted_at"):
                print(f"  削除日時: {job_info.get('deleted_at')}")

            dataset_cfg = training_config.get("dataset") or {}
            policy_cfg = training_config.get("policy") or {}
            training_cfg = training_config.get("training") or {}
            validation_cfg = training_config.get("validation") or {}
            early_cfg = training_config.get("early_stopping") or {}

            if training_config:
                print(f"\n{Colors.CYAN}設定:{Colors.RESET}")
                if dataset_cfg.get("id"):
                    print(f"  dataset.id: {dataset_cfg.get('id')}")
                if policy_cfg.get("type"):
                    print(f"  policy.type: {policy_cfg.get('type')}")
                if policy_cfg.get("pretrained_path"):
                    print(f"  policy.pretrained_path: {policy_cfg.get('pretrained_path')}")
                if training_cfg.get("steps") is not None:
                    print(f"  training.steps: {training_cfg.get('steps')}")
                if training_cfg.get("batch_size") is not None:
                    print(f"  training.batch_size: {training_cfg.get('batch_size')}")
                if training_cfg.get("save_freq") is not None:
                    print(f"  training.save_freq: {training_cfg.get('save_freq')}")
                if validation_cfg.get("enable") is not None:
                    print(f"  validation.enable: {validation_cfg.get('enable')}")
                if validation_cfg.get("eval_freq") is not None:
                    print(f"  validation.eval_freq: {validation_cfg.get('eval_freq')}")
                if early_cfg.get("enable") is not None:
                    print(f"  early_stopping.enable: {early_cfg.get('enable')}")
                if early_cfg.get("patience") is not None:
                    print(f"  early_stopping.patience: {early_cfg.get('patience')}")
                if early_cfg.get("min_delta") is not None:
                    print(f"  early_stopping.min_delta: {early_cfg.get('min_delta')}")
                if early_cfg.get("mode"):
                    print(f"  early_stopping.mode: {early_cfg.get('mode')}")

            if summary:
                print(f"\n{Colors.CYAN}Summary:{Colors.RESET}")
                for key in (
                    "total_steps",
                    "total_time_s",
                    "early_stopping_point_step",
                    "early_stopping_point_val_loss",
                    "val_loss",
                    "stopped_step",
                ):
                    if key in summary:
                        print(f"  {key}: {summary.get(key)}")

            if early_stopping:
                print(f"\n{Colors.CYAN}Early Stopping:{Colors.RESET}")
                for key, value in early_stopping.items():
                    print(f"  {key}: {value}")

            print(f"\n{Colors.CYAN}最新loss:{Colors.RESET}")
            if latest_train:
                print(
                    f"  train: step={latest_train.get('step')} loss={latest_train.get('loss')} ts={latest_train.get('ts')}"
                )
            else:
                print("  train: N/A")
            if latest_val:
                print(
                    f"  val: step={latest_val.get('step')} loss={latest_val.get('loss')} ts={latest_val.get('ts')}"
                )
            else:
                print("  val: N/A")

            status = job_info.get("status", "")
            action_choices = []

            if status == "running":
                action_choices.append(Choice(value="stream_logs", name="📜 ログをストリーミング (Ctrl+Cで終了)"))
                action_choices.append(Choice(value="stop", name="⏹ ジョブを停止"))
                action_choices.append(Choice(value="refresh", name="🔄 更新"))
            else:
                action_choices.append(Choice(value="logs", name="📜 ログを表示 (最新30行)"))

            if status in ("completed", "failed", "stopped", "terminated"):
                action_choices.append(Choice(value="delete", name="🗑 ジョブを削除"))

            action_choices.append(Choice(value="back", name="← 戻る"))

            action = inquirer.select(
                message="アクション:",
                choices=action_choices,
                style=hacker_style,
            ).execute()

            if action == "logs":
                self._show_job_logs(job_id)
            elif action == "stream_logs":
                self._stream_job_logs(job_id)
            elif action == "stop":
                self._stop_job(job_id)
            elif action == "delete":
                self._delete_job(job_id)
            elif action == "refresh":
                return self._show_job_detail(job_id)

        except KeyboardInterrupt:
            print(f"\n{Colors.muted('中断されました')}")
        except Exception as e:
            print(f"{Colors.error('エラー:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")

        return MenuResult.CONTINUE

    def _show_job_logs(self, job_id: str) -> None:
        """Show job logs (for non-running jobs)."""
        print(f"\n{Colors.CYAN}ログ:{Colors.RESET}")
        try:
            result = self.api.get_training_job_logs(job_id)
            logs = result.get("logs", "")
            if logs:
                lines = logs.strip().split("\n") if isinstance(logs, str) else logs
                for line in lines[-30:]:
                    print(f"  {line}")
            else:
                print(f"  {Colors.muted('ログなし')}")
        except Exception as e:
            print(f"{Colors.error('エラー:')} {e}")
        input(f"\n{Colors.muted('Press Enter to continue...')}")

    def _stream_job_logs_with_session(self, session) -> None:
        """Stream job logs using existing WebSocket session (no new SSH connection)."""
        print(f"\n{Colors.CYAN}ログストリーミング中... (Ctrl+Cで終了){Colors.RESET}\n")

        # Start log streaming via existing session
        if not session.start_logs():
            print(f"{Colors.error('ログストリーミングの開始に失敗しました')}")
            return

        try:
            while True:
                msg = session.receive(timeout=1.0)
                if msg is None:
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "log":
                    print(f"  {msg.get('line', '')}")
                elif msg_type == "log_stream_started":
                    pass  # Already started
                elif msg_type == "log_stream_stopped":
                    print(f"\n{Colors.info('ログストリーム終了')}")
                    break
                elif msg_type == "job_status_changed":
                    status = msg.get("status", "")
                    print(f"\n{Colors.info(f'ジョブ状態が変更されました: {status}')}")
                    break
                elif msg_type == "heartbeat":
                    continue
                elif msg_type == "progress":
                    # Show progress updates while streaming
                    step = msg.get("step", "N/A")
                    loss = msg.get("loss", "N/A")
                    print(f"  {Colors.muted(f'[進捗: Step {step}, Loss: {loss}]')}")
                elif msg_type == "error" or msg_type == "ssh_error":
                    print(f"\n{Colors.error('エラー:')} {msg.get('error', 'Unknown error')}")
                    break

        except KeyboardInterrupt:
            session.stop_logs()
            print(f"\n{Colors.muted('ストリーミング終了')}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")

    def _stream_job_logs(self, job_id: str) -> None:
        """Stream job logs in real-time via WebSocket (legacy, creates new session)."""
        # Create new session and use it for streaming
        session = self.api.create_job_session_ws(job_id)

        if not session.connect():
            print(f"{Colors.error('エラー:')} WebSocket接続に失敗しました")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return

        print(f"\n{Colors.CYAN}ログストリーミング中... (Ctrl+Cで終了){Colors.RESET}\n")

        try:
            # Wait for SSH connection
            while True:
                msg = session.receive(timeout=1.0)
                if msg is None:
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "job_info":
                    pass  # Skip job info
                elif msg_type == "ssh_connecting":
                    print(f"  {Colors.muted('SSH接続中...')}")
                elif msg_type == "ssh_connected":
                    print(f"{Colors.success('SSH接続完了')}\n")
                    break
                elif msg_type == "ssh_error":
                    print(f"{Colors.error('SSH接続エラー:')} {msg.get('error', '')}")
                    session.close()
                    input(f"\n{Colors.muted('Press Enter to continue...')}")
                    return
                elif msg_type == "error":
                    print(f"{Colors.error('エラー:')} {msg.get('error', '')}")
                    session.close()
                    input(f"\n{Colors.muted('Press Enter to continue...')}")
                    return

            # Skip remote_status and progress
            msg = session.receive(timeout=1.0)  # remote_status
            msg = session.receive(timeout=1.0)  # progress

            # Now stream logs
            self._stream_job_logs_with_session(session)

        except KeyboardInterrupt:
            print(f"\n{Colors.muted('ストリーミング終了')}")
        finally:
            session.close()

    def _stop_job(self, job_id: str) -> None:
        """Stop a running job."""
        confirm = inquirer.confirm(
            message="このジョブを停止しますか?",
            default=False,
            style=hacker_style,
        ).execute()

        if confirm:
            try:
                self.api.stop_training_job(job_id)
                print(f"{Colors.success('ジョブを停止しました')}")
            except Exception as e:
                print(f"{Colors.error('エラー:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")

    def _delete_job(self, job_id: str) -> None:
        """Delete a job and terminate the remote instance."""
        confirm = inquirer.confirm(
            message="このジョブを削除しますか？（リモートインスタンスも終了します）",
            default=False,
            style=hacker_style,
        ).execute()

        if confirm:
            try:
                result = self.api.delete_training_job(job_id)
                message = result.get("message", "ジョブを削除しました")
                print(f"{Colors.success(message)}")
            except Exception as e:
                print(f"{Colors.error('エラー:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")

    def _show_instance_status(self, job_id: str) -> None:
        """Show instance status."""
        print(f"\n{Colors.CYAN}インスタンス状態:{Colors.RESET}")
        try:
            result = self.api.get_training_instance_status(job_id)
            print(f"  インスタンス: {result.get('instance_status', 'N/A')}")
            print(f"  ジョブ状態: {result.get('job_status', 'N/A')}")
            print(f"  GPU: {result.get('gpu_model', 'N/A')}")
            if result.get('ip'):
                print(f"  IP: {result.get('ip')}")
            if result.get('remote_process_status'):
                print(f"  プロセス: {result.get('remote_process_status')}")
        except Exception as e:
            print(f"{Colors.error('エラー:')} {e}")
        input(f"\n{Colors.muted('Press Enter to continue...')}")


# =============================================================================
# Training Configs Menu (Existing functionality preserved)
# =============================================================================


class TrainingConfigsMenu(BaseMenu):
    """Manage training configurations."""

    title = "学習設定"

    def get_choices(self) -> List[Choice]:
        choices = []
        try:
            result = self.api.list_training_configs()
            configs = result.get("configs", [])
            for c in configs[:15]:
                config_id = c.get("config_id", "unknown")
                config_data = c.get("config", {})

                if isinstance(config_data, dict):
                    policy = config_data.get("policy", {}).get("type", "?")
                    dataset = config_data.get("dataset", {}).get("id", "?")
                else:
                    policy = "?"
                    dataset = "?"

                choices.append(Choice(
                    value=config_id,
                    name=f"  {config_id} [{policy}] - {dataset}"
                ))
        except Exception:
            pass

        if not choices:
            choices.append(Choice(value="__none__", name="(設定なし)"))

        choices.append(Choice(value="__create__", name="+ 新規設定を作成"))

        return choices

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "__none__":
            return MenuResult.BACK
        if choice == "__create__":
            # Redirect to training wizard
            return self.submenu(TrainingWizard)

        return self._show_config_detail(choice)

    def _show_config_detail(self, config_id: str) -> MenuResult:
        """Show config details and actions."""
        show_section_header(f"設定: {config_id}")

        try:
            config_result = self.api.get_training_config(config_id)
            config_data = config_result.get("config", {})

            policy_type = config_data.get("policy", {}).get("type", "N/A")
            dataset_id = config_data.get("dataset", {}).get("id", "N/A")
            steps = config_data.get("training", {}).get("steps", 0) or 0
            batch_size = config_data.get("training", {}).get("batch_size", 0) or 0

            print(f"  ID: {config_result.get('config_id', 'N/A')}")
            print(f"  ポリシー: {policy_type}")
            print(f"  データセット: {dataset_id}")
            print(f"  ステップ数: {steps:,}")
            print(f"  バッチサイズ: {batch_size}")
            print(f"  作成: {config_result.get('created_at', 'N/A')}")

        except Exception as e:
            print(f"{Colors.error('エラー:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        action = inquirer.select(
            message="アクション:",
            choices=[
                Choice(value="validate", name="✓ 検証"),
                Choice(value="dryrun", name="🔍 ドライラン"),
                Choice(value="start", name="🚀 学習開始"),
                Choice(value="delete", name="🗑 削除"),
                Choice(value="back", name="← 戻る"),
            ],
            style=hacker_style,
        ).execute()

        if action == "validate":
            try:
                result = self.api.validate_training_config(config_id)
                if result.get("is_valid"):
                    print(f"{Colors.success('設定は有効です')}")
                else:
                    print(f"{Colors.warning('問題が見つかりました:')}")
                    for issue in result.get("issues", []):
                        print(f"  - {issue}")
            except Exception as e:
                print(f"{Colors.error('エラー:')} {e}")

        elif action == "dryrun":
            try:
                result = self.api.dry_run_training(config_id)
                print(f"{Colors.success('ドライラン完了')}")
                print(f"  推定時間: {result.get('estimated_time', 'N/A')}")
                print(f"  推定コスト: ${result.get('estimated_cost', 0):.2f}")
            except Exception as e:
                print(f"{Colors.error('エラー:')} {e}")

        elif action == "start":
            try:
                result = self.api.create_training_job({"config_id": config_id})
                print(f"{Colors.success('学習ジョブを開始しました!')}")
                print(f"  ジョブID: {result.get('job_id', 'N/A')}")
            except Exception as e:
                print(f"{Colors.error('エラー:')} {e}")

        elif action == "delete":
            confirm = inquirer.confirm(
                message=f"設定 {config_id} を削除しますか?",
                default=False,
                style=hacker_style,
            ).execute()
            if confirm:
                try:
                    self.api.delete_training_config(config_id)
                    print(f"{Colors.success('設定を削除しました')}")
                except Exception as e:
                    print(f"{Colors.error('エラー:')} {e}")

        if action != "back":
            input(f"\n{Colors.muted('Press Enter to continue...')}")

        return MenuResult.CONTINUE

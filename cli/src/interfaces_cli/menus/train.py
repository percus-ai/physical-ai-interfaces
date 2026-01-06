"""Train menu - Model training operations."""

from typing import TYPE_CHECKING, Any, Dict, List

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from interfaces_cli.banner import format_size, show_section_header
from interfaces_cli.menu_system import BaseMenu, MenuResult
from interfaces_cli.styles import Colors, hacker_style

if TYPE_CHECKING:
    from interfaces_cli.app import PhiApplication


def download_dataset_with_progress(
    api,
    dataset_id: str,
) -> Dict[str, Any]:
    """Download a dataset from R2 with Rich progress display.

    Args:
        api: API client instance
        dataset_id: ID of dataset to download

    Returns:
        Result dict with 'success', 'error' keys
    """
    console = Console()
    current = {"file": "", "done": 0, "total": 0, "size": 0, "transferred": 0, "total_size": 0}

    def make_progress_panel():
        """Create progress display panel."""
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Label", style="cyan")
        table.add_column("Value")

        table.add_row("データセット:", dataset_id)

        if current["file"]:
            # File progress
            if current["size"] > 0:
                pct = (current["transferred"] / current["size"]) * 100
                transferred_str = format_size(current["transferred"])
                size_str = format_size(current["size"])
                progress_str = f"{transferred_str} / {size_str} ({pct:.1f}%)"
            else:
                progress_str = format_size(current["size"]) if current["size"] else "..."
            table.add_row("ファイル:", current["file"])
            table.add_row("転送:", progress_str)

        if current["total"] > 0:
            table.add_row("ファイル数:", f"{current['done']}/{current['total']}")

        if current["total_size"] > 0:
            table.add_row("合計サイズ:", format_size(current["total_size"]))

        return Panel(table, title="📥 データセットダウンロード", border_style="cyan")

    def progress_callback(data):
        """Handle progress updates from WebSocket."""
        msg_type = data.get("type", "")

        if msg_type == "start":
            current["total"] = data.get("total_files", 0)
            current["total_size"] = data.get("total_size", 0)
            current["done"] = 0
            current["file"] = ""
            current["transferred"] = 0
        elif msg_type == "downloading":
            current["file"] = data.get("current_file", "")
            current["size"] = data.get("file_size", 0)
            current["done"] = data.get("files_done", 0)
            current["transferred"] = 0
        elif msg_type == "progress":
            current["file"] = data.get("current_file", "")
            current["size"] = data.get("file_size", 0)
            current["transferred"] = data.get("bytes_transferred", 0)
        elif msg_type == "downloaded":
            current["done"] = data.get("files_done", 0)
            current["transferred"] = current["size"]

    try:
        with Live(make_progress_panel(), console=console, refresh_per_second=4) as live:
            def update_display(data):
                progress_callback(data)
                live.update(make_progress_panel())

            result = api.sync_with_progress(
                action="download",
                entry_type="datasets",
                item_ids=[dataset_id],
                progress_callback=update_display,
            )

        success_count = result.get("success_count", 0)
        if success_count > 0:
            return {"success": True}
        else:
            results = result.get("results", {})
            error = results.get(dataset_id, {}).get("error", "Unknown error")
            return {"success": False, "error": error}

    except Exception as e:
        return {"success": False, "error": str(e)}


class TrainMenu(BaseMenu):
    """Train menu - Model training operations."""

    title = "モデル学習"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="jobs", name="📋 [JOBS] 学習ジョブ一覧"),
            Choice(value="new", name="🚀 [NEW] 新規学習ジョブ"),
            Choice(value="configs", name="⚙️  [CONFIGS] 学習設定管理"),
            Choice(value="stats", name="📊 [STATS] 学習統計"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "jobs":
            return self.submenu(TrainingJobsMenu)
        if choice == "new":
            return self.submenu(NewTrainingMenu)
        if choice == "configs":
            return self.submenu(TrainingConfigsMenu)
        if choice == "stats":
            return self._show_stats()
        return MenuResult.CONTINUE

    def _show_stats(self) -> MenuResult:
        """Show training statistics."""
        show_section_header("Training Statistics")

        try:
            stats = self.api.get_analytics_training()

            print(f"{Colors.CYAN}Jobs Summary:{Colors.RESET}")
            print(f"  Total: {stats.get('total_jobs', 0)}")
            print(f"  Running: {stats.get('running_jobs', 0)}")
            print(f"  Completed: {stats.get('completed_jobs', 0)}")
            print(f"  Failed: {stats.get('failed_jobs', 0)}")

            print(f"\n{Colors.CYAN}Resources:{Colors.RESET}")
            print(f"  Total GPU Hours: {stats.get('total_gpu_hours', 0):.1f}")
            print(f"  Avg Job Duration: {stats.get('avg_duration_hours', 0):.1f}h")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class TrainingJobsMenu(BaseMenu):
    """View training jobs."""

    title = "学習ジョブ"

    def get_choices(self) -> List[Choice]:
        choices = []
        try:
            result = self.api.list_training_jobs()
            jobs = result.get("jobs", [])
            for job in jobs[:15]:
                job_id = job.get("job_id", "unknown")
                status = job.get("status", "unknown")
                config = job.get("config", {})
                policy = config.get("policy_type", "?") if isinstance(config, dict) else "?"
                progress = job.get("progress", 0)
                status_icon = self._status_icon(status)
                progress_str = f"{progress:.0%}" if status == "running" else status
                choices.append(Choice(
                    value=job_id,
                    name=f"{status_icon} {job_id[:12]}... [{policy}] {progress_str}"
                ))
        except Exception:
            pass

        if not choices:
            choices.append(Choice(value="__none__", name="(No training jobs)"))

        choices.append(Choice(value="__refresh__", name="Refresh"))
        choices.append(Choice(value="__check_all__", name="Check All Status"))

        return choices

    def _status_icon(self, status: str) -> str:
        """Get status icon."""
        icons = {
            "running": Colors.warning("●"),
            "completed": Colors.success("●"),
            "failed": Colors.error("●"),
            "queued": Colors.muted("○"),
            "stopped": Colors.muted("◌"),
        }
        return icons.get(status, Colors.muted("?"))

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "__none__":
            return MenuResult.BACK
        if choice == "__refresh__":
            return MenuResult.CONTINUE  # Will refresh the menu
        if choice == "__check_all__":
            return self._check_all_status()

        return self._show_job_detail(choice)

    def _check_all_status(self) -> MenuResult:
        """Check status of all jobs."""
        show_section_header("Checking All Jobs")

        try:
            result = self.api.check_training_jobs_status()
            updates = result.get("updates", [])
            print(f"{Colors.success('Status check complete')}")
            print(f"  Jobs updated: {len(updates)}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_job_detail(self, job_id: str) -> MenuResult:
        """Show job details and actions."""
        show_section_header(f"Training Job")

        try:
            result = self.api.get_training_job(job_id)
            job = result.get("job", result)
            progress_info = result.get("progress", {})
            print(f"  ID: {job.get('job_id', 'N/A')}")
            print(f"  Status: {job.get('status', 'N/A')}")
            config = job.get("config", {})
            if isinstance(config, dict):
                print(f"  Policy: {config.get('policy_type', 'N/A')}")
                print(f"  Dataset: {config.get('dataset_repo_id', 'N/A')}")
            print(f"  Steps: {progress_info.get('current_step', 0):,} / {progress_info.get('total_steps', 0):,}")
            progress_val = progress_info.get('progress', 0) or 0
            print(f"  Progress: {progress_val:.1%}")
            if progress_info.get('loss') is not None:
                print(f"  Loss: {progress_info.get('loss', 0):.6f}")
            print(f"  Created: {job.get('created_at', 'N/A')}")

            status = job.get('status', '')

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        # Build action choices based on status
        action_choices = [
            Choice(value="logs", name="View Logs"),
            Choice(value="progress", name="View Progress"),
        ]
        if status == "running":
            action_choices.append(Choice(value="stop", name="Stop Job"))
        if status in ("completed", "failed", "stopped"):
            action_choices.append(Choice(value="delete", name="Delete Job"))
        if status == "running":
            action_choices.append(Choice(value="instance", name="Instance Status"))
        action_choices.append(Choice(value="back", name="« Back"))

        action = inquirer.select(
            message="Action:",
            choices=action_choices,
            style=hacker_style,
        ).execute()

        if action == "logs":
            self._show_job_logs(job_id)
        elif action == "progress":
            self._show_job_progress(job_id)
        elif action == "stop":
            self._stop_job(job_id)
        elif action == "delete":
            self._delete_job(job_id)
        elif action == "instance":
            self._show_instance_status(job_id)

        return MenuResult.CONTINUE

    def _show_job_logs(self, job_id: str) -> None:
        """Show job logs."""
        print(f"\n{Colors.CYAN}Logs:{Colors.RESET}")
        try:
            result = self.api.get_training_job_logs(job_id)
            logs = result.get("logs", "")
            if logs:
                # logs is a string, split by newlines and show last 20 lines
                lines = logs.strip().split("\n") if isinstance(logs, str) else logs
                for line in lines[-20:]:
                    print(f"  {line}")
            else:
                print(f"  {Colors.muted('No logs available')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
        input(f"\n{Colors.muted('Press Enter to continue...')}")

    def _show_job_progress(self, job_id: str) -> None:
        """Show job progress."""
        print(f"\n{Colors.CYAN}Progress:{Colors.RESET}")
        try:
            result = self.api.get_training_job_progress(job_id)
            print(f"  Step: {result.get('current_step', 0):,} / {result.get('total_steps', 0):,}")
            print(f"  Progress: {result.get('progress', 0):.1%}")
            print(f"  Loss: {result.get('loss', 'N/A')}")
            print(f"  ETA: {result.get('eta', 'N/A')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
        input(f"\n{Colors.muted('Press Enter to continue...')}")

    def _stop_job(self, job_id: str) -> None:
        """Stop a running job."""
        confirm = inquirer.confirm(
            message="Stop this training job?",
            default=False,
            style=hacker_style,
        ).execute()
        if confirm:
            try:
                self.api.stop_training_job(job_id)
                print(f"{Colors.success('Job stopped')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")

    def _delete_job(self, job_id: str) -> None:
        """Delete a job."""
        confirm = inquirer.confirm(
            message="Delete this training job?",
            default=False,
            style=hacker_style,
        ).execute()
        if confirm:
            try:
                self.api.delete_training_job(job_id)
                print(f"{Colors.success('Job deleted')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")

    def _show_instance_status(self, job_id: str) -> None:
        """Show instance status."""
        print(f"\n{Colors.CYAN}Instance Status:{Colors.RESET}")
        try:
            result = self.api.get_training_instance_status(job_id)
            print(f"  Instance: {result.get('instance_status', 'N/A')}")
            print(f"  Job Status: {result.get('job_status', 'N/A')}")
            print(f"  GPU: {result.get('gpu_model', 'N/A')}")
            if result.get('ip'):
                print(f"  IP: {result.get('ip')}")
            if result.get('remote_process_status'):
                print(f"  Process: {result.get('remote_process_status')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
        input(f"\n{Colors.muted('Press Enter to continue...')}")


class NewTrainingMenu(BaseMenu):
    """New training job configuration."""

    title = "新規学習ジョブ"

    def get_choices(self) -> List[Choice]:
        # List available configs
        choices = []
        try:
            result = self.api.list_training_configs()
            configs = result.get("configs", [])
            for c in configs[:10]:
                config_id = c.get("config_id", "unknown")
                config_data = c.get("config", {})
                policy = config_data.get("policy_type", "?") if isinstance(config_data, dict) else "?"
                dataset = config_data.get("dataset_repo_id", "?") if isinstance(config_data, dict) else "?"
                choices.append(Choice(
                    value=config_id,
                    name=f"{config_id} [{policy}] - {dataset}"
                ))
        except Exception:
            pass

        if not choices:
            choices.append(Choice(value="__none__", name="(No saved configs)"))

        choices.append(Choice(value="__create__", name="+ Create New Config"))

        return choices

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "__none__":
            # Go to create
            return self._create_config()
        if choice == "__create__":
            return self._create_config()

        # Start training from config
        return self._start_from_config(choice)

    def _create_config(self) -> MenuResult:
        """Create a new training config."""
        show_section_header("Create Training Config")

        try:
            # Select policy type
            policy = inquirer.select(
                message="Policy type:",
                choices=[
                    Choice(value="act", name="ACT - Action Chunking Transformer"),
                    Choice(value="pi0", name="Pi0 - Physical Intelligence"),
                    Choice(value="smolvla", name="SmolVLA - Small VLA"),
                    Choice(value="diffusion", name="Diffusion Policy"),
                    Choice(value="__back__", name="« Cancel"),
                ],
                style=hacker_style,
            ).execute()

            if policy == "__back__":
                return MenuResult.CONTINUE

            # Select dataset (local + R2 remote)
            datasets = self.api.list_datasets()
            ds_list = datasets.get("datasets", [])
            if not ds_list:
                print(f"{Colors.warning('No datasets available.')}")
                print(f"{Colors.muted('Upload datasets from R2 Storage menu or record new ones.')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Build dataset lookup
            ds_lookup = {}

            ds_choices = []
            for d in ds_list:
                if isinstance(d, dict):
                    ds_id = d.get("id", "unknown")
                    is_local = d.get("is_local", True)
                    size = format_size(d.get("size_bytes", 0))
                    # Status indicator: ✓ for local, ☁ for remote
                    status = "✓" if is_local else "☁"
                    ds_choices.append(Choice(value=ds_id, name=f"{status} {ds_id} ({size})"))
                    ds_lookup[ds_id] = d
                else:
                    ds_choices.append(Choice(value=d, name=d))
                    ds_lookup[d] = {"id": d, "is_local": True}
            ds_choices.append(Choice(value="__back__", name="« Cancel"))

            dataset = inquirer.select(
                message="Dataset (✓=local, ☁=R2 remote):",
                choices=ds_choices,
                style=hacker_style,
            ).execute()

            if dataset == "__back__":
                return MenuResult.CONTINUE

            # Check if dataset needs to be downloaded
            ds_info = ds_lookup.get(dataset, {})
            if not ds_info.get("is_local", True):
                print(f"\n{Colors.warning('このデータセットはローカルにダウンロードされていません。')}")
                should_download = inquirer.confirm(
                    message="R2からダウンロードしますか?",
                    default=True,
                    style=hacker_style,
                ).execute()

                if not should_download:
                    return MenuResult.CONTINUE

                # Download dataset with WebSocket progress
                print()
                download_result = download_dataset_with_progress(self.api, dataset)
                if download_result.get("success"):
                    print(f"\n{Colors.success('データセットのダウンロードが完了しました。')}")
                else:
                    error = download_result.get("error", "Unknown error")
                    print(f"\n{Colors.error(f'ダウンロードエラー: {error}')}")
                    input(f"\n{Colors.muted('Press Enter to continue...')}")
                    return MenuResult.CONTINUE

            # Get training parameters
            steps = inquirer.number(
                message="Training steps:",
                default=100000,
                min_allowed=1000,
                max_allowed=1000000,
                style=hacker_style,
            ).execute()

            batch_size = inquirer.number(
                message="Batch size:",
                default=32,
                min_allowed=1,
                max_allowed=256,
                style=hacker_style,
            ).execute()

            # Create config with nested structure
            result = self.api.create_training_config({
                "config": {
                    "policy_type": policy,
                    "dataset_repo_id": dataset,
                    "num_train_steps": steps,
                    "batch_size": batch_size,
                }
            })

            config_id = result.get("config_id", "unknown")
            print(f"\n{Colors.success('Config created!')}")
            print(f"  Config ID: {config_id}")

            # Ask to start training
            start = inquirer.confirm(
                message="Start training now?",
                default=True,
                style=hacker_style,
            ).execute()

            if start:
                job_result = self.api.create_training_job({"config_id": config_id})
                print(f"\n{Colors.success('Training job started!')}")
                print(f"  Job ID: {job_result.get('job_id', 'N/A')}")

        except KeyboardInterrupt:
            return MenuResult.CONTINUE
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _start_from_config(self, config_id: str) -> MenuResult:
        """Start training from a saved config."""
        show_section_header(f"Start Training: {config_id}")

        try:
            # Validate config first
            validation = self.api.validate_training_config(config_id)
            if not validation.get("is_valid", False):
                print(f"{Colors.warning('Config has issues:')}")
                for issue in validation.get("issues", []):
                    print(f"  - {issue}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Get config details
            config_result = self.api.get_training_config(config_id)
            config_data = config_result.get("config", {})
            print(f"  Policy: {config_data.get('policy_type', 'N/A')}")
            print(f"  Dataset: {config_data.get('dataset_repo_id', 'N/A')}")
            print(f"  Steps: {config_data.get('num_train_steps', 0):,}")
            print(f"  Batch Size: {config_data.get('batch_size', 0)}")

            confirm = inquirer.confirm(
                message="Start training job?",
                default=True,
                style=hacker_style,
            ).execute()

            if confirm:
                result = self.api.create_training_job({"config_id": config_id})
                print(f"\n{Colors.success('Training job started!')}")
                print(f"  Job ID: {result.get('job_id', 'N/A')}")
                print(f"  Status: {result.get('status', 'queued')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


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
                policy = config_data.get("policy_type", "?") if isinstance(config_data, dict) else "?"
                dataset = config_data.get("dataset_repo_id", "?") if isinstance(config_data, dict) else "?"
                choices.append(Choice(
                    value=config_id,
                    name=f"{config_id} [{policy}] - {dataset}"
                ))
        except Exception:
            pass

        if not choices:
            choices.append(Choice(value="__none__", name="(No configs)"))

        return choices

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "__none__":
            return MenuResult.BACK

        return self._show_config_detail(choice)

    def _show_config_detail(self, config_id: str) -> MenuResult:
        """Show config details and actions."""
        show_section_header(f"Config: {config_id}")

        try:
            config_result = self.api.get_training_config(config_id)
            config_data = config_result.get("config", {})
            print(f"  ID: {config_result.get('config_id', 'N/A')}")
            print(f"  Policy: {config_data.get('policy_type', 'N/A')}")
            print(f"  Dataset: {config_data.get('dataset_repo_id', 'N/A')}")
            print(f"  Steps: {config_data.get('num_train_steps', 0):,}")
            print(f"  Batch Size: {config_data.get('batch_size', 0)}")
            print(f"  Created: {config_result.get('created_at', 'N/A')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        action = inquirer.select(
            message="Action:",
            choices=[
                Choice(value="validate", name="Validate Config"),
                Choice(value="dryrun", name="Dry Run"),
                Choice(value="start", name="Start Training"),
                Choice(value="delete", name="Delete Config"),
                Choice(value="back", name="« Back"),
            ],
            style=hacker_style,
        ).execute()

        if action == "validate":
            try:
                result = self.api.validate_training_config(config_id)
                if result.get("is_valid"):
                    print(f"{Colors.success('Config is valid')}")
                else:
                    print(f"{Colors.warning('Issues found:')}")
                    for issue in result.get("issues", []):
                        print(f"  - {issue}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "dryrun":
            try:
                result = self.api.dry_run_training(config_id)
                print(f"{Colors.success('Dry run complete')}")
                print(f"  Estimated time: {result.get('estimated_time', 'N/A')}")
                print(f"  Estimated cost: ${result.get('estimated_cost', 0):.2f}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "start":
            try:
                result = self.api.create_training_job({"config_id": config_id})
                print(f"{Colors.success('Training job started!')}")
                print(f"  Job ID: {result.get('job_id', 'N/A')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "delete":
            confirm = inquirer.confirm(
                message=f"Delete config {config_id}?",
                default=False,
                style=hacker_style,
            ).execute()
            if confirm:
                try:
                    self.api.delete_training_config(config_id)
                    print(f"{Colors.success('Config deleted')}")
                except Exception as e:
                    print(f"{Colors.error('Error:')} {e}")

        if action != "back":
            input(f"\n{Colors.muted('Press Enter to continue...')}")

        return MenuResult.CONTINUE

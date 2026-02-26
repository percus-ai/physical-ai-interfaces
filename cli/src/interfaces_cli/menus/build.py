"""Build menu - PyTorch building for Jetson."""

from typing import Any, List

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from interfaces_cli.banner import show_section_header
from interfaces_cli.menu_system import BaseMenu, MenuResult
from interfaces_cli.styles import Colors, hacker_style

class BuildMenu(BaseMenu):
    """Build menu - PyTorch building for Jetson."""

    title = "ビルド"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="status", name="📊 [STATUS] bundled-torch状態確認"),
            Choice(value="build", name="🔨 [BUILD] PyTorch/torchvisionビルド (数時間)"),
            Choice(value="clean", name="🗑️  [CLEAN] bundled-torch削除"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "status":
            return self._show_status()
        if choice == "build":
            return self._build_bundled_torch()
        if choice == "clean":
            return self._clean_bundled_torch()
        return MenuResult.CONTINUE

    def _show_status(self) -> MenuResult:
        """Show bundled-torch status."""
        show_section_header("Bundled-Torch Status")

        try:
            status = self.api.get_bundled_torch_status()

            table = Table(show_header=False, box=None)
            table.add_column("Key", style="cyan")
            table.add_column("Value")

            table.add_row("Jetson:", "Yes" if status.get("is_jetson") else "No")
            table.add_row("Exists:", "Yes" if status.get("exists") else "No")

            if status.get("exists"):
                table.add_row("Valid:", "Yes" if status.get("is_valid") else "No (not built)")
                if status.get("pytorch_version"):
                    table.add_row("PyTorch:", status["pytorch_version"])
                if status.get("torchvision_version"):
                    table.add_row("torchvision:", status["torchvision_version"])
                if status.get("numpy_version"):
                    numpy_ver = status["numpy_version"]
                    # Highlight if numpy 2.x (compatible with lerobot)
                    if numpy_ver.startswith("2."):
                        table.add_row("numpy:", f"{numpy_ver} (lerobot compatible)")
                    else:
                        table.add_row("numpy:", f"{numpy_ver} [bold red](needs rebuild for lerobot)[/bold red]")
                if status.get("pytorch_path"):
                    table.add_row("Path:", status["pytorch_path"])

            console = Console()
            console.print(table)

            if status.get("is_valid"):
                print(f"\n{Colors.success('Note:')} bundled-torch is automatically loaded via sys.path.")
                print(f"{Colors.muted('No manual installation needed - just restart CLI/backend.')}")
            elif not status.get("is_jetson"):
                print(f"\n{Colors.warning('Note:')} bundled-torch build is only needed on Jetson.")
                print(f"{Colors.muted('On other platforms, use: pip install torch torchvision')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _build_bundled_torch(self) -> MenuResult:
        """Build bundled-torch."""
        show_section_header("Build Bundled-Torch")

        try:
            # Check if Jetson
            status = self.api.get_bundled_torch_status()

            if not status.get("is_jetson"):
                print(f"{Colors.error('Error:')} This feature is only available on Jetson.")
                print(f"{Colors.muted('On other platforms, use: pip install torch torchvision')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            if status.get("is_valid"):
                print(f"{Colors.warning('Warning:')} bundled-torch already exists and is valid.")
                confirm = inquirer.confirm(
                    message="Do you want to rebuild anyway?",
                    default=False,
                    style=hacker_style,
                ).execute()
                if not confirm:
                    return MenuResult.CONTINUE

            # Version selection
            print(f"\n{Colors.muted('Leave empty to use latest version.')}")

            pytorch_version = inquirer.text(
                message="PyTorch version (e.g., v2.1.0):",
                default="",
                style=hacker_style,
            ).execute() or None

            torchvision_version = inquirer.text(
                message="torchvision version (e.g., v0.16.0):",
                default="",
                style=hacker_style,
            ).execute() or None

            # Confirmation
            print(f"\n{Colors.CYAN}Build Configuration:{Colors.RESET}")
            print(f"  PyTorch: {pytorch_version or 'latest'}")
            print(f"  torchvision: {torchvision_version or 'latest'}")
            print(f"\n{Colors.warning('Warning:')} Building PyTorch from source may take several hours.")

            confirm = inquirer.confirm(
                message="Start build?",
                default=False,
                style=hacker_style,
            ).execute()

            if not confirm:
                print(f"{Colors.muted('Build cancelled.')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Start build with progress
            print(f"\n{Colors.CYAN}Building...{Colors.RESET}\n")

            console = Console()
            current_step = {"step": "", "percent": 0, "message": ""}
            log_lines: List[str] = []

            def make_progress_panel():
                """Create progress panel."""
                table = Table(show_header=False, box=None, expand=True)
                table.add_column("Key", style="cyan", width=12, no_wrap=True)
                table.add_column("Value", overflow="ellipsis", no_wrap=True)

                step_name = current_step["step"].replace("_", " ").title()
                table.add_row("Step:", step_name or "Starting...")
                table.add_row("Progress:", f"{current_step['percent']}%")
                table.add_row("Status:", current_step["message"] or "...")

                if log_lines:
                    # Show last 3 log lines
                    table.add_row("", "")
                    table.add_row("Log:", "")
                    for line in log_lines[-3:]:
                        table.add_row("", Colors.muted(line))

                return Panel(table, title="Build Progress", border_style="cyan")

            def progress_callback(data):
                """Handle progress updates."""
                msg_type = data.get("type", "")

                if msg_type == "start":
                    current_step["step"] = data.get("step", "")
                    current_step["percent"] = 0
                    current_step["message"] = data.get("message", "")
                elif msg_type == "progress":
                    current_step["step"] = data.get("step", current_step["step"])
                    current_step["percent"] = data.get("percent", current_step["percent"])
                    current_step["message"] = data.get("message", current_step["message"])
                elif msg_type == "step_complete":
                    current_step["percent"] = 100
                    current_step["message"] = data.get("message", "Completed")
                elif msg_type == "log":
                    line = data.get("line", "")
                    if line:
                        log_lines.append(line)
                        # Keep only last 100 lines
                        if len(log_lines) > 100:
                            log_lines.pop(0)
                elif msg_type == "complete":
                    current_step["percent"] = 100
                    current_step["message"] = "Build completed!"
                elif msg_type == "error":
                    current_step["message"] = f"Error: {data.get('error', 'Unknown')}"

            # Run build with live progress display
            from rich.live import Live

            result = {"type": "error", "error": "Unknown"}

            with Live(make_progress_panel(), refresh_per_second=2, console=console) as live:
                def live_progress_callback(data):
                    progress_callback(data)
                    live.update(make_progress_panel())

                result = self.api.build_bundled_torch_ws(
                    pytorch_version=pytorch_version,
                    torchvision_version=torchvision_version,
                    progress_callback=live_progress_callback,
                )

            # Show result
            if result.get("type") == "complete":
                print(f"\n{Colors.success('Build completed!')}")
                if result.get("output_path"):
                    print(f"  Output: {result['output_path']}")
            else:
                print(f"\n{Colors.error('Build failed!')}")
                if result.get("error"):
                    print(f"  Error: {result['error']}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _clean_bundled_torch(self) -> MenuResult:
        """Clean bundled-torch."""
        show_section_header("Clean Bundled-Torch")

        try:
            status = self.api.get_bundled_torch_status()

            if not status.get("exists"):
                print(f"{Colors.muted('bundled-torch does not exist. Nothing to clean.')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"{Colors.warning('Warning:')} This will delete all bundled-torch files.")
            if status.get("pytorch_path"):
                print(f"  Path: {status['pytorch_path']}")

            confirm = inquirer.confirm(
                message="Are you sure?",
                default=False,
                style=hacker_style,
            ).execute()

            if not confirm:
                print(f"{Colors.muted('Cancelled.')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            print(f"\n{Colors.CYAN}Cleaning...{Colors.RESET}")

            def progress_callback(data):
                msg_type = data.get("type", "")
                if msg_type == "progress":
                    print(f"  {data.get('message', '...')}")
                elif msg_type == "complete":
                    print(f"  {Colors.success('Done!')}")
                elif msg_type == "error":
                    print(f"  {Colors.error('Error:')} {data.get('error', 'Unknown')}")

            result = self.api.clean_bundled_torch_ws(progress_callback=progress_callback)

            if result.get("type") == "complete":
                print(f"\n{Colors.success('Cleaned successfully!')}")
            else:
                print(f"\n{Colors.error('Clean failed!')}")
                if result.get("error"):
                    print(f"  Error: {result['error']}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

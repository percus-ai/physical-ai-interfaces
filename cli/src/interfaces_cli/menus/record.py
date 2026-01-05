"""Record menu - Simplified data recording operations."""

from typing import TYPE_CHECKING, Any, List, Optional

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from interfaces_cli.banner import show_section_header
from interfaces_cli.menu_system import BaseMenu, MenuResult
from interfaces_cli.styles import Colors, hacker_style

if TYPE_CHECKING:
    from interfaces_cli.app import PhiApplication


class RecordMenu(BaseMenu):
    """Record menu - Data recording operations."""

    title = "データ録画"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="record", name="🎬 [RECORD] 録画開始"),
            Choice(value="list", name="📁 [LIST] 録画一覧"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "record":
            return self._start_recording()
        if choice == "list":
            return self.submenu(RecordingsListMenu)
        return MenuResult.CONTINUE

    def _select_project(self) -> Optional[str]:
        """Select a project for recording."""
        try:
            result = self.api.list_projects()
            projects = result.get("projects", [])
            if not projects:
                print(f"{Colors.warning('No projects found.')}")
                print(f"{Colors.muted('Project YAML files should be in data/projects/')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return None

            # Get project details for display
            choices = []
            for p in projects:
                try:
                    project_info = self.api.get_project(p)
                    display_name = project_info.get("display_name", p)
                    description = project_info.get("description", "")
                    label = f"📦 {display_name}"
                    if description:
                        label += f" - {description[:40]}"
                    choices.append(Choice(value=p, name=label))
                except Exception:
                    choices.append(Choice(value=p, name=f"📦 {p}"))

            choices.append(Choice(value="__back__", name="« Cancel"))

            selected = inquirer.select(
                message="Select project:",
                choices=choices,
                style=hacker_style,
            ).execute()

            if selected == "__back__":
                return None

            return selected
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            return None

    def _start_recording(self) -> MenuResult:
        """Start a new recording session."""
        project_name = self._select_project()
        if not project_name:
            return MenuResult.CONTINUE

        show_section_header(f"Recording: {project_name}")

        try:
            # Get project info for display
            try:
                project_info = self.api.get_project(project_name)
                print(f"  Project: {project_info.get('display_name', project_name)}")
                print(f"  Description: {project_info.get('description', 'N/A')}")
                print(f"  Episode time: {project_info.get('episode_time_s', 60)}s")
                print(f"  Reset time: {project_info.get('reset_time_s', 10)}s")
                print()
            except Exception:
                pass

            # Get episode count
            num_episodes = inquirer.text(
                message="Number of episodes:",
                default="1",
                validate=lambda x: x.isdigit() and int(x) > 0,
                style=hacker_style,
            ).execute()

            if num_episodes is None:
                return MenuResult.CONTINUE

            # Confirm
            print(f"\n{Colors.CYAN}Recording Configuration:{Colors.RESET}")
            print(f"  Project: {project_name}")
            print(f"  Episodes: {num_episodes}")
            print()

            confirm = inquirer.confirm(
                message="Start recording?",
                default=True,
                style=hacker_style,
            ).execute()

            if not confirm:
                return MenuResult.CONTINUE

            # Start recording with WebSocket for real-time output
            print(f"\n{Colors.muted('Starting lerobot-record...')}")
            print(f"{Colors.muted('Press Ctrl+C to stop recording.')}\n")

            console = Console()
            output_lines: List[str] = []
            max_display_lines = 20
            status_info = {
                "project": project_name,
                "output_path": "",
                "started": False,
                "num_episodes": num_episodes,
            }

            def make_output_panel():
                """Create output display panel."""
                text = Text()

                if status_info["started"]:
                    text.append(f"Project: {status_info['project']}  ", style="cyan")
                    text.append(f"Episodes: {status_info['num_episodes']}\n", style="cyan")
                    text.append(f"Output: {status_info['output_path']}\n\n", style="dim")

                # Show last N lines
                display_lines = output_lines[-max_display_lines:]
                for line in display_lines:
                    if line.startswith("[stderr]"):
                        text.append(line + "\n", style="yellow")
                    elif "error" in line.lower() or "Error" in line:
                        text.append(line + "\n", style="red")
                    elif "INFO" in line:
                        text.append(line + "\n", style="dim")
                    else:
                        text.append(line + "\n")

                return Panel(text, title="🎬 録画中", border_style="cyan")

            def on_progress(msg):
                """Handle progress messages from WebSocket."""
                msg_type = msg.get("type")
                if msg_type == "start":
                    status_info["started"] = True
                    status_info["output_path"] = msg.get("output_path", "N/A")
                    output_lines.append(f"[開始] Recording started")
                elif msg_type == "output":
                    line = msg.get("line", "")
                    if line:
                        output_lines.append(line)
                elif msg_type == "error_output":
                    line = msg.get("line", "")
                    if line:
                        output_lines.append(f"[stderr] {line}")
                elif msg_type == "error":
                    output_lines.append(f"[ERROR] {msg.get('error', 'Unknown')}")

            try:
                with Live(make_output_panel(), console=console, refresh_per_second=4) as live:
                    def update_display(msg):
                        on_progress(msg)
                        live.update(make_output_panel())

                    result = self.api.record_ws(
                        project_name,
                        int(num_episodes),
                        progress_callback=update_display
                    )
            except Exception as e:
                result = {"type": "error", "error": str(e)}

            if result.get("type") == "complete" and result.get("success"):
                print(f"\n{Colors.success('Recording completed!')}")
            elif result.get("type") == "stopped":
                print(f"\n{Colors.warning('Recording stopped')}")
            else:
                print(f"\n{Colors.warning('Recording ended')}")

            print(f"  Message: {result.get('message', 'N/A')}")
            print(f"  Output: {result.get('output_path', 'N/A')}")

        except KeyboardInterrupt:
            print(f"\n{Colors.warning('Recording interrupted.')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class RecordingsListMenu(BaseMenu):
    """List all recordings."""

    title = "録画一覧"

    def get_choices(self) -> List[Choice]:
        choices = []
        try:
            result = self.api.list_recordings()
            recordings = result.get("recordings", [])
            for r in recordings[:30]:
                rec_id = r.get("recording_id", "unknown")
                project_id = r.get("project_id", "?")
                episode = r.get("episode_name", "?")
                frames = r.get("frames", 0)
                size_mb = r.get("size_mb", 0)
                choices.append(Choice(
                    value=rec_id,
                    name=f"{project_id}/{episode} - {frames} frames ({size_mb:.1f} MB)"
                ))
        except Exception:
            pass

        if not choices:
            choices.append(Choice(value="__none__", name="(No recordings)"))

        return choices

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "__none__":
            return MenuResult.BACK

        return self._show_recording_detail(choice)

    def _show_recording_detail(self, recording_id: str) -> MenuResult:
        """Show recording details and actions."""
        show_section_header(f"Recording: {recording_id}")

        try:
            recording = self.api.get_recording(recording_id)
            print(f"  ID: {recording.get('recording_id', 'N/A')}")
            print(f"  Project: {recording.get('project_id', 'N/A')}")
            print(f"  Episode: {recording.get('episode_name', 'N/A')}")
            print(f"  Frames: {recording.get('frames', 0)}")
            print(f"  Size: {recording.get('size_mb', 0):.1f} MB")
            print(f"  Cameras: {', '.join(recording.get('cameras', []))}")
            print(f"  Path: {recording.get('path', 'N/A')}")
            print(f"  Created: {recording.get('created_at', 'N/A')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        # Actions
        action = inquirer.select(
            message="Action:",
            choices=[
                Choice(value="validate", name="Validate recording"),
                Choice(value="delete", name="Delete recording"),
                Choice(value="back", name="« Back"),
            ],
            style=hacker_style,
        ).execute()

        if action == "validate":
            try:
                result = self.api.validate_recording(recording_id)
                is_valid = result.get("is_valid", False)

                if is_valid:
                    print(f"\n{Colors.success('Recording is valid')}")
                else:
                    print(f"\n{Colors.warning('Recording has issues:')}")

                errors = result.get("errors", [])
                if errors:
                    print(f"\n{Colors.CYAN}Errors:{Colors.RESET}")
                    for err in errors:
                        print(f"  {Colors.error('!')} {err}")

                warnings = result.get("warnings", [])
                if warnings:
                    print(f"\n{Colors.CYAN}Warnings:{Colors.RESET}")
                    for warn in warnings:
                        print(f"  {Colors.warning('!')} {warn}")

            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "delete":
            confirm = inquirer.confirm(
                message=f"Delete recording {recording_id}?",
                default=False,
                style=hacker_style,
            ).execute()
            if confirm:
                try:
                    self.api.delete_recording(recording_id)
                    print(f"\n{Colors.success('Recording deleted')}")
                except Exception as e:
                    print(f"{Colors.error('Error:')} {e}")

        if action != "back":
            input(f"\n{Colors.muted('Press Enter to continue...')}")

        return MenuResult.CONTINUE

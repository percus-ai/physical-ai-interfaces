"""Record menu - Data recording operations."""

from typing import TYPE_CHECKING, Any, List, Optional

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

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
            Choice(value="new", name="🎬 [NEW] 新規録画セッション"),
            Choice(value="recordings", name="📁 [LIST] 録画一覧"),
            Choice(value="sessions", name="📋 [SESSIONS] アクティブセッション"),
            Choice(value="export", name="📤 [EXPORT] データセットへ出力"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "new":
            return self._start_recording()
        if choice == "recordings":
            return self.submenu(RecordingsListMenu)
        if choice == "sessions":
            return self._show_sessions()
        if choice == "export":
            return self._export_recording()
        return MenuResult.CONTINUE

    def _select_project(self) -> Optional[str]:
        """Select a project for recording."""
        try:
            result = self.api.list_projects()
            projects = result.get("projects", [])
            if not projects:
                print(f"{Colors.warning('No projects found.')}")
                print(f"{Colors.muted('Create a project first in SETUP menu.')}")
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
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            return None

    def _start_recording(self) -> MenuResult:
        """Start a new recording session."""
        project_id = self._select_project()
        if not project_id:
            return MenuResult.CONTINUE

        show_section_header(f"New Recording: {project_id}")

        try:
            # Get username
            username = inquirer.text(
                message="Username:",
                default="user",
                style=hacker_style,
            ).execute()

            # Robot type
            robot_type = inquirer.select(
                message="Robot type:",
                choices=[
                    Choice(value="so101", name="SO-101"),
                    Choice(value="so100", name="SO-100"),
                ],
                style=hacker_style,
            ).execute()

            # Get ports
            leader_port = inquirer.text(
                message="Leader arm port:",
                default="/dev/ttyUSB0",
                style=hacker_style,
            ).execute()

            follower_port = inquirer.text(
                message="Follower arm port:",
                default="/dev/ttyUSB1",
                style=hacker_style,
            ).execute()

            # Arm IDs
            leader_id = inquirer.text(
                message="Leader ID:",
                default="leader",
                style=hacker_style,
            ).execute()

            follower_id = inquirer.text(
                message="Follower ID:",
                default="follower",
                style=hacker_style,
            ).execute()

            # Recording parameters
            fps = inquirer.text(
                message="FPS:",
                default="30",
                style=hacker_style,
            ).execute()

            num_episodes = inquirer.text(
                message="Number of episodes:",
                default="1",
                style=hacker_style,
            ).execute()

            episode_time_s = inquirer.text(
                message="Episode time (seconds):",
                default="60",
                style=hacker_style,
            ).execute()

            reset_time_s = inquirer.text(
                message="Reset time between episodes (seconds):",
                default="5",
                style=hacker_style,
            ).execute()

            # Task description
            task_description = inquirer.text(
                message="Task description (optional):",
                default="",
                style=hacker_style,
            ).execute()

            # Camera configuration
            print(f"\n{Colors.CYAN}Camera Configuration:{Colors.RESET}")
            use_camera = inquirer.confirm(
                message="Add camera?",
                default=True,
                style=hacker_style,
            ).execute()

            cameras = []
            while use_camera:
                camera_id = inquirer.text(
                    message="Camera ID (e.g., 'top', 'wrist'):",
                    default="top",
                    style=hacker_style,
                ).execute()

                camera_type = inquirer.select(
                    message="Camera type:",
                    choices=[
                        Choice(value="opencv", name="OpenCV (webcam)"),
                        Choice(value="intelrealsense", name="Intel RealSense"),
                    ],
                    style=hacker_style,
                ).execute()

                index_or_path = inquirer.text(
                    message="Camera index or path:",
                    default="0",
                    style=hacker_style,
                ).execute()

                cam_width = inquirer.text(
                    message="Width:",
                    default="640",
                    style=hacker_style,
                ).execute()

                cam_height = inquirer.text(
                    message="Height:",
                    default="480",
                    style=hacker_style,
                ).execute()

                cam_fps = inquirer.text(
                    message="Camera FPS:",
                    default="30",
                    style=hacker_style,
                ).execute()

                cameras.append({
                    "camera_id": camera_id,
                    "camera_type": camera_type,
                    "index_or_path": int(index_or_path) if index_or_path.isdigit() else index_or_path,
                    "width": int(cam_width),
                    "height": int(cam_height),
                    "fps": int(cam_fps),
                    "warmup_s": 2.0,
                })

                use_camera = inquirer.confirm(
                    message="Add another camera?",
                    default=False,
                    style=hacker_style,
                ).execute()

            # Build request
            request_data = {
                "username": username,
                "project_id": project_id,
                "robot_type": robot_type,
                "leader_port": leader_port,
                "follower_port": follower_port,
                "leader_id": leader_id,
                "follower_id": follower_id,
                "fps": int(fps),
                "num_episodes": int(num_episodes),
                "episode_time_s": float(episode_time_s),
                "reset_time_s": float(reset_time_s),
                "cameras": cameras,
            }
            if task_description:
                request_data["task_description"] = task_description

            # Start recording session
            print(f"\n{Colors.muted('Creating recording session...')}")
            result = self.api.start_recording(request_data)

            session = result.get("session", {})
            session_id = session.get("session_id", "unknown")
            output_path = session.get("output_path", "")

            print(f"\n{Colors.success('Recording session created')}")
            print(f"  Session: {session_id}")
            print(f"  Project: {project_id}")
            print(f"  Episodes: {num_episodes}")
            print(f"  Output: {output_path}")
            print(f"  Message: {result.get('message', '')}")

            # Ask to run
            run = inquirer.confirm(
                message="Start recording now?",
                default=True,
                style=hacker_style,
            ).execute()

            if run:
                self.api.run_recording(session_id)
                print(f"\n{Colors.success('Recording running!')}")
                print(f"{Colors.muted('Press Enter to stop recording...')}")

                try:
                    input()
                except KeyboardInterrupt:
                    pass

                stop_result = self.api.stop_recording(session_id)
                print(f"\n{Colors.success('Recording stopped.')}")
                print(f"  Total frames: {stop_result.get('total_frames', 0)}")
                print(f"  Duration: {stop_result.get('duration_seconds', 0):.1f}s")
                print(f"  Size: {stop_result.get('size_mb', 0):.1f} MB")
                print(f"  Output: {stop_result.get('output_path', '')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_sessions(self) -> MenuResult:
        """Show recording sessions."""
        show_section_header("Recording Sessions")

        try:
            result = self.api.list_recording_sessions()
            sessions = result.get("sessions", [])
            total = result.get("total", len(sessions))

            if sessions:
                print(f"{Colors.CYAN}Active Sessions ({total}):{Colors.RESET}\n")
                for s in sessions:
                    session_id = s.get("session_id", "unknown")
                    project_id = s.get("project_id", "?")
                    episode_name = s.get("episode_name", "")
                    status = s.get("status", "unknown")
                    is_recording = s.get("is_recording", False)
                    frames = s.get("frames_recorded", 0)
                    duration = s.get("duration_seconds", 0)
                    current_ep = s.get("current_episode", 0)
                    num_eps = s.get("num_episodes", 1)

                    icon = Colors.success("*") if is_recording else Colors.muted("*")
                    status_str = Colors.success("recording") if is_recording else status

                    print(f"  {icon} {session_id}")
                    print(f"      Project: {project_id}/{episode_name}")
                    print(f"      Status: {status_str}")
                    print(f"      Progress: Episode {current_ep}/{num_eps}")
                    print(f"      Frames: {frames}, Duration: {duration:.1f}s")
                    if s.get("error_message"):
                        print(f"      Error: {Colors.error(s.get('error_message'))}")
                    print()
            else:
                print(f"{Colors.muted('No recording sessions.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _export_recording(self) -> MenuResult:
        """Export a recording to dataset format."""
        show_section_header("Export Recording")

        try:
            result = self.api.list_recordings()
            recordings = result.get("recordings", [])

            if not recordings:
                print(f"{Colors.muted('No recordings to export.')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            choices = []
            for r in recordings[:20]:
                rec_id = r.get("recording_id", "unknown")
                project_id = r.get("project_id", "?")
                episode = r.get("episode_name", "?")
                frames = r.get("frames", 0)
                size_mb = r.get("size_mb", 0)
                choices.append(Choice(
                    value=rec_id,
                    name=f"{project_id}/{episode} ({frames} frames, {size_mb:.1f} MB)"
                ))
            choices.append(Choice(value="__back__", name="« Cancel"))

            selected = inquirer.select(
                message="Select recording:",
                choices=choices,
                style=hacker_style,
            ).execute()

            if selected == "__back__":
                return MenuResult.CONTINUE

            # Export
            result = self.api.export_recording(selected)
            print(f"{Colors.success('Recording exported')}")
            print(f"  Path: {result.get('export_path', 'N/A')}")
            print(f"  Size: {result.get('size_mb', 0):.1f} MB")
            print(f"  Message: {result.get('message', '')}")

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
            for r in recordings[:20]:
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
            print(f"  Duration: {recording.get('duration_seconds', 0):.1f}s")
            print(f"  Size: {recording.get('size_mb', 0):.1f} MB")
            print(f"  Cameras: {', '.join(recording.get('cameras', []))}")
            print(f"  Path: {recording.get('path', 'N/A')}")
            print(f"  Created: {recording.get('created_at', 'N/A')}")
            print(f"  Valid: {'Yes' if recording.get('is_valid') else 'No'}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        # Actions
        action = inquirer.select(
            message="Action:",
            choices=[
                Choice(value="validate", name="Validate recording"),
                Choice(value="export", name="Export to dataset"),
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

                stats = result.get("stats", {})
                if stats:
                    print(f"\n{Colors.CYAN}Statistics:{Colors.RESET}")
                    for key, val in stats.items():
                        print(f"  {key}: {val}")

            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")

        elif action == "export":
            try:
                result = self.api.export_recording(recording_id)
                print(f"\n{Colors.success('Recording exported')}")
                print(f"  Path: {result.get('export_path', 'N/A')}")
                print(f"  Size: {result.get('size_mb', 0):.1f} MB")
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

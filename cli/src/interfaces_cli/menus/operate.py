"""Operate menu - Teleop and Inference."""

import asyncio
import json
import sys
import select
import termios
import tty
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from interfaces_cli.banner import format_size, show_section_header
from interfaces_cli.menu_system import BaseMenu, MenuResult
from interfaces_cli.styles import Colors, hacker_style

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

if TYPE_CHECKING:
    from interfaces_cli.app import PhiApplication


def download_with_progress(
    api,
    entry_type: str,
    item_id: str,
    item_label: str = "アイテム",
) -> Dict[str, Any]:
    """Download an item from R2 with Rich progress display.

    Args:
        api: API client instance
        entry_type: 'models' or 'datasets'
        item_id: ID of item to download
        item_label: Display label (e.g., "モデル", "データセット")

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

        table.add_row(f"{item_label}:", item_id)

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

        return Panel(table, title=f"📥 {item_label}ダウンロード", border_style="cyan")

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
                entry_type=entry_type,
                item_ids=[item_id],
                progress_callback=update_display,
            )

        success_count = result.get("success_count", 0)
        if success_count > 0:
            return {"success": True}
        else:
            results = result.get("results", {})
            error = results.get(item_id, {}).get("error", "Unknown error")
            return {"success": False, "error": error}

    except Exception as e:
        return {"success": False, "error": str(e)}


class OperateMenu(BaseMenu):
    """Operate menu - Teleop and Inference operations."""

    title = "テレオペ / 推論"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="teleop", name="🎮 [TELEOP] テレオペレーション"),
            Choice(value="inference", name="🤖 [INFERENCE] AI推論実行"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "teleop":
            return self.submenu(TeleopMenu)
        if choice == "inference":
            return self.submenu(InferenceMenu)
        return MenuResult.CONTINUE


class TeleopMenu(BaseMenu):
    """Teleoperation mode selection."""

    title = "テレオペレーション"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="local", name="🎮 [LOCAL] ローカルテレオペ"),
            Choice(value="remote_leader", name="📡 [LEADER] リモートリーダー"),
            Choice(value="remote_follower", name="📥 [FOLLOWER] リモートフォロワー"),
            Choice(value="sessions", name="📋 [SESSIONS] セッション一覧"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "local":
            return self._start_local_teleop()
        if choice == "remote_leader":
            return self._start_remote_leader()
        if choice == "remote_follower":
            return self._start_remote_follower()
        if choice == "sessions":
            return self._show_sessions()
        return MenuResult.CONTINUE

    def _get_device_config(self) -> dict:
        """Get user device configuration."""
        try:
            return self.api.get_user_devices()
        except Exception:
            return {}

    def _start_local_teleop(self) -> MenuResult:
        """Start local teleoperation."""
        show_section_header("Local Teleoperation")

        try:
            # Get device config for defaults
            devices = self._get_device_config()
            leader_config = devices.get("leader_right") or {}
            follower_config = devices.get("follower_right") or {}

            # Select teleop mode
            mode = inquirer.select(
                message="Teleop mode:",
                choices=[
                    Choice(value="simple", name="Simple (leader-follower)"),
                    Choice(value="visual", name="Visual (with camera)"),
                    Choice(value="bimanual", name="Bimanual (two arms)"),
                    Choice(value="__back__", name="« Cancel"),
                ],
                style=hacker_style,
            ).execute()

            if mode == "__back__":
                return MenuResult.CONTINUE

            # Get robot preset
            robot_preset = inquirer.select(
                message="Robot type:",
                choices=[
                    Choice(value="so101", name="SO-101"),
                    Choice(value="so100", name="SO-100"),
                ],
                style=hacker_style,
            ).execute()

            # Get ports (with defaults from config)
            default_leader = leader_config.get("port") or "/dev/ttyUSB0"
            default_follower = follower_config.get("port") or "/dev/ttyUSB1"

            leader_port = inquirer.text(
                message="Leader arm port:",
                default=default_leader,
                style=hacker_style,
            ).execute()

            follower_port = inquirer.text(
                message="Follower arm port:",
                default=default_follower,
                style=hacker_style,
            ).execute()

            fps = inquirer.text(
                message="FPS:",
                default="60",
                style=hacker_style,
            ).execute()

            # Visual mode uses WebSocket for real-time display on CLI
            if mode == "visual":
                return self._run_visual_teleop(
                    leader_port=leader_port,
                    follower_port=follower_port,
                    robot_preset=robot_preset,
                    fps=int(fps),
                )

            # Other modes use the existing API
            result = self.api.start_teleop({
                "mode": mode,
                "robot_preset": robot_preset,
                "leader_port": leader_port,
                "follower_port": follower_port,
                "fps": int(fps),
            })

            session = result.get("session", {})
            session_id = session.get("session_id", "unknown")

            print(f"\n{Colors.success('Teleop session created')}")
            print(f"  Session: {session_id}")
            print(f"  Mode: {mode}")
            print(f"  Robot: {robot_preset}")
            print(f"  Leader: {leader_port}")
            print(f"  Follower: {follower_port}")

            # Ask to run
            run = inquirer.confirm(
                message="Start teleop now?",
                default=True,
                style=hacker_style,
            ).execute()

            if run:
                self.api.run_teleop(session_id)
                print(f"\n{Colors.success('Teleop running!')}")
                print(f"{Colors.muted('Press Enter to stop teleoperation...')}")

                try:
                    input()
                except KeyboardInterrupt:
                    pass

                self.api.stop_teleop(session_id)
                print(f"\n{Colors.success('Teleoperation stopped.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _run_visual_teleop(
        self,
        leader_port: str,
        follower_port: str,
        robot_preset: str,
        fps: int,
    ) -> MenuResult:
        """Run visual teleoperation with Rich Live display via WebSocket."""
        if not WEBSOCKETS_AVAILABLE:
            print(f"{Colors.error('Error:')} websockets library not installed.")
            print(f"{Colors.muted('Install with: pip install websockets')}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        console = Console()

        # Get backend URL and convert to WebSocket URL
        backend_url = self.api.base_url  # e.g., http://localhost:8000
        ws_url = backend_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/teleop/ws/visual"

        console.print(f"\n[bold cyan]Connecting to:[/bold cyan] {ws_url}")
        console.print(f"[bold cyan]Leader:[/bold cyan] {leader_port}")
        console.print(f"[bold cyan]Follower:[/bold cyan] {follower_port}")
        console.print(f"[bold cyan]Robot:[/bold cyan] {robot_preset}")
        console.print(f"[bold cyan]FPS:[/bold cyan] {fps}")

        try:
            asyncio.run(self._visual_teleop_loop(
                ws_url=ws_url,
                leader_port=leader_port,
                follower_port=follower_port,
                robot_preset=robot_preset,
                fps=fps,
                console=console,
            ))
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    async def _visual_teleop_loop(
        self,
        ws_url: str,
        leader_port: str,
        follower_port: str,
        robot_preset: str,
        fps: int,
        console: Console,
    ) -> None:
        """Async WebSocket loop for visual teleop."""
        async with websockets.connect(ws_url) as ws:
            # Send start command
            await ws.send(json.dumps({
                "action": "start",
                "leader_port": leader_port,
                "follower_port": follower_port,
                "robot_preset": robot_preset,
                "fps": fps,
            }))

            # Wait for connected response
            response = json.loads(await ws.recv())
            if response.get("type") == "error":
                console.print(f"[bold red]Error:[/bold red] {response.get('error')}")
                return

            if response.get("type") == "connected":
                console.print(f"\n[bold green]{response.get('message')}[/bold green]")
                motor_names = response.get("motor_names", [])
            else:
                console.print(f"[bold yellow]Unexpected response:[/bold yellow] {response}")
                return

            console.print("\n[yellow]Move the leader arm - follower will follow...[/yellow]")
            console.print("[dim]Press 'q' to stop[/dim]\n")

            # Set up terminal for key input
            if sys.stdin.isatty():
                fd = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                tty.setcbreak(fd)
            else:
                fd = None
                old_settings = None

            stop_requested = False

            try:
                with Live(self._create_teleop_layout({}, {}, 0, 0.0, 0.0, fps, 0),
                          refresh_per_second=15, console=console) as live:
                    while not stop_requested:
                        # Check for key press (non-blocking)
                        if fd is not None:
                            ready, _, _ = select.select([sys.stdin], [], [], 0)
                            if ready:
                                key = sys.stdin.read(1)
                                if key.lower() in ('q', '\x03'):
                                    stop_requested = True
                                    break

                        # Receive state update with timeout
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=0.1)
                            data = json.loads(msg)

                            if data.get("type") == "state":
                                live.update(self._create_teleop_layout(
                                    leader_states=data.get("leader_states", {}),
                                    follower_states=data.get("follower_states", {}),
                                    iteration=data.get("iteration", 0),
                                    elapsed=data.get("elapsed", 0.0),
                                    actual_fps=data.get("actual_fps", 0.0),
                                    target_fps=data.get("target_fps", fps),
                                    errors=data.get("errors", 0),
                                ))
                            elif data.get("type") == "error":
                                console.print(f"\n[bold red]Error:[/bold red] {data.get('error')}")
                                break
                            elif data.get("type") == "stopped":
                                break
                        except asyncio.TimeoutError:
                            continue

            finally:
                if old_settings is not None:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

            # Send stop command
            console.print("\n[yellow]Stopping...[/yellow]")
            await ws.send(json.dumps({"action": "stop"}))

            # Wait for stopped response
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=2.0)
                data = json.loads(response)
                if data.get("type") == "stopped":
                    console.print(f"\n[bold green]Teleoperation Ended[/bold green]")
                    console.print(f"Duration: [cyan]{data.get('duration', 0):.1f}s[/cyan]")
                    console.print(f"Total iterations: [cyan]{data.get('total_iterations', 0)}[/cyan]")
                    console.print(f"Average frequency: [cyan]{data.get('average_fps', 0):.1f} Hz[/cyan]")
            except asyncio.TimeoutError:
                console.print("[yellow]Stop response timeout[/yellow]")

    def _create_motor_table(self, title: str, states: Dict[str, dict]) -> Table:
        """Create motor state table for display."""
        table = Table(title=title, show_header=True, header_style="bold magenta")
        table.add_column("Motor", style="cyan", width=12)
        table.add_column("Position", justify="right", style="green", width=9)
        table.add_column("Speed", justify="right", style="yellow", width=9)
        table.add_column("Load", justify="right", style="blue", width=9)
        table.add_column("Current", justify="right", style="cyan", width=9)
        table.add_column("Temp", justify="right", style="red", width=8)
        table.add_column("Voltage", justify="right", style="magenta", width=8)

        for motor_name, state in states.items():
            if state.get("error"):
                table.add_row(motor_name, "[red]ERROR[/red]", "-", "-", "-", "-", "-")
            else:
                pos = f"{state.get('position', 0):.0f}" if state.get("position") is not None else "-"
                speed = f"{state.get('speed', 0):.0f}" if state.get("speed") is not None else "-"
                load = f"{state.get('load', 0):.0f}" if state.get("load") is not None else "-"
                current = f"{state.get('current', 0):.0f}" if state.get("current") is not None else "-"
                temp = f"{state.get('temperature')}C" if state.get("temperature") is not None else "-"
                volt = f"{state.get('voltage', 0):.1f}V" if state.get("voltage") is not None else "-"
                table.add_row(motor_name, pos, speed, load, current, temp, volt)

        return table

    def _create_status_panel(
        self, iteration: int, elapsed: float, actual_fps: float, target_fps: int, errors: int
    ) -> Panel:
        """Create status panel for display."""
        text = Text()
        text.append("Time: ", style="bold")
        text.append(f"{elapsed:.1f}s\n", style="cyan")

        text.append("Iterations: ", style="bold")
        text.append(f"{iteration}\n", style="cyan")

        text.append("FPS: ", style="bold")
        fps_style = "green" if actual_fps >= target_fps * 0.9 else "yellow" if actual_fps >= target_fps * 0.7 else "red"
        text.append(f"{actual_fps:.1f} Hz", style=fps_style)
        text.append(f" (target: {target_fps} Hz)\n", style="dim")

        text.append("Errors: ", style="bold")
        error_style = "green" if errors == 0 else "yellow" if errors < 10 else "red"
        text.append(f"{errors}", style=error_style)

        return Panel(text, title="[bold]Status[/bold]", border_style="blue")

    def _create_teleop_layout(
        self,
        leader_states: Dict[str, dict],
        follower_states: Dict[str, dict],
        iteration: int,
        elapsed: float,
        actual_fps: float,
        target_fps: int,
        errors: int,
    ) -> Layout:
        """Create display layout for visual teleop."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=7),
        )

        layout["main"].split_row(
            Layout(name="leader"),
            Layout(name="follower"),
        )

        header_text = Text("Visual Teleoperation", justify="center", style="bold white on blue")
        layout["header"].update(Panel(header_text))

        layout["leader"].update(self._create_motor_table("Leader Arm", leader_states))
        layout["follower"].update(self._create_motor_table("Follower Arm", follower_states))

        layout["footer"].update(self._create_status_panel(iteration, elapsed, actual_fps, target_fps, errors))

        return layout

    def _start_remote_leader(self) -> MenuResult:
        """Start as remote leader."""
        show_section_header("Remote Leader")

        try:
            # Get device config for defaults
            devices = self._get_device_config()
            leader_config = devices.get("leader_right") or {}
            cameras_config = devices.get("cameras") or {}

            # Get host/port
            host = inquirer.text(
                message="Host (0.0.0.0 for all interfaces):",
                default="0.0.0.0",
                style=hacker_style,
            ).execute()

            port = inquirer.text(
                message="Port:",
                default="8765",
                style=hacker_style,
            ).execute()

            default_leader = leader_config.get("port") or "/dev/ttyUSB0"
            leader_port = inquirer.text(
                message="Leader arm port:",
                default=default_leader,
                style=hacker_style,
            ).execute()

            # Optional camera
            use_camera = inquirer.confirm(
                message="Enable camera streaming?",
                default=False,
                style=hacker_style,
            ).execute()

            camera_id = None
            if use_camera:
                # Build camera choices from config
                if cameras_config:
                    camera_choices = [
                        Choice(value=cam.get("id", "0"), name=f"{name} ({cam.get('id')})")
                        for name, cam in cameras_config.items()
                    ]
                    camera_choices.append(Choice(value="__custom__", name="Custom..."))
                    selected = inquirer.select(
                        message="Select camera:",
                        choices=camera_choices,
                        style=hacker_style,
                    ).execute()
                    if selected == "__custom__":
                        camera_id = inquirer.text(
                            message="Camera ID:",
                            default="0",
                            style=hacker_style,
                        ).execute()
                    else:
                        camera_id = selected
                else:
                    camera_id = inquirer.text(
                        message="Camera ID:",
                        default="0",
                        style=hacker_style,
                    ).execute()

            result = self.api.start_teleop_leader({
                "host": host,
                "port": int(port),
                "leader_port": leader_port,
                "camera_id": int(camera_id) if camera_id else None,
            })

            session = result.get("session", {})
            session_id = session.get("session_id", "unknown")
            url = session.get("url", f"http://{host}:{port}")

            print(f"\n{Colors.success('Leader session created')}")
            print(f"  Session: {session_id}")
            print(f"  URL: {url}")
            print(f"  Leader Port: {leader_port}")
            print(f"\n{Colors.muted('Share this URL with followers.')}")
            print(f"{Colors.muted('Press Enter to stop...')}")

            try:
                input()
            except KeyboardInterrupt:
                pass

            self.api.stop_teleop_leader(session_id)
            print(f"\n{Colors.success('Leader session stopped.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _start_remote_follower(self) -> MenuResult:
        """Start as remote follower."""
        show_section_header("Remote Follower")

        try:
            # Get device config for defaults
            devices = self._get_device_config()
            follower_config = devices.get("follower_right") or {}

            leader_url = inquirer.text(
                message="Leader URL (e.g., http://192.168.1.100:8765):",
                style=hacker_style,
            ).execute()

            if not leader_url:
                return MenuResult.CONTINUE

            default_follower = follower_config.get("port") or "/dev/ttyUSB0"
            follower_port = inquirer.text(
                message="Follower arm port:",
                default=default_follower,
                style=hacker_style,
            ).execute()

            result = self.api.start_teleop_follower({
                "leader_url": leader_url,
                "follower_port": follower_port,
            })

            session = result.get("session", {})
            session_id = session.get("session_id", "unknown")

            print(f"\n{Colors.success('Follower session created')}")
            print(f"  Session: {session_id}")
            print(f"  Leader: {leader_url}")
            print(f"  Follower Port: {follower_port}")
            print(f"\n{Colors.muted('Waiting for leader connection...')}")
            print(f"{Colors.muted('Press Enter to stop...')}")

            try:
                input()
            except KeyboardInterrupt:
                pass

            self.api.stop_teleop_follower(session_id)
            print(f"\n{Colors.success('Follower session stopped.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_sessions(self) -> MenuResult:
        """Show teleop sessions."""
        show_section_header("Teleop Sessions")

        try:
            # Local sessions
            local = self.api.list_teleop_sessions()
            local_sessions = local.get("sessions", [])
            print(f"{Colors.CYAN}Local Sessions:{Colors.RESET}")
            if local_sessions:
                for s in local_sessions:
                    session_id = s.get("session_id", "unknown")
                    mode = s.get("mode", "?")
                    running = s.get("is_running", False)
                    status = Colors.success("running") if running else Colors.muted("stopped")
                    print(f"  - {session_id}: {mode} ({status})")
            else:
                print(f"  {Colors.muted('No local sessions')}")

            # Remote sessions
            remote = self.api.list_remote_teleop_sessions()
            leaders = remote.get("leaders", [])
            followers = remote.get("followers", [])

            print(f"\n{Colors.CYAN}Remote Leaders:{Colors.RESET}")
            if leaders:
                for s in leaders:
                    session_id = s.get("session_id", "unknown")
                    url = s.get("url", "?")
                    running = s.get("is_running", False)
                    clients = s.get("clients_connected", 0)
                    status = Colors.success("running") if running else Colors.muted("stopped")
                    print(f"  - {session_id}: {url} ({status}, {clients} clients)")
            else:
                print(f"  {Colors.muted('No leader sessions')}")

            print(f"\n{Colors.CYAN}Remote Followers:{Colors.RESET}")
            if followers:
                for s in followers:
                    session_id = s.get("session_id", "unknown")
                    leader_url = s.get("leader_url", "?")
                    connected = s.get("is_connected", False)
                    running = s.get("is_running", False)
                    latency = s.get("latency_ms", 0)
                    status = Colors.success("connected") if connected else Colors.muted("disconnected")
                    print(f"  - {session_id}: -> {leader_url} ({status}, {latency:.1f}ms)")
            else:
                print(f"  {Colors.muted('No follower sessions')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class InferenceMenu(BaseMenu):
    """Inference - Run models on robot."""

    title = "AI推論"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="run", name="🚀 [RUN] モデル実行"),
            Choice(value="models", name="📦 [MODELS] 利用可能モデル一覧"),
            Choice(value="compat", name="🔍 [COMPAT] デバイス互換性チェック"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "run":
            return self._run_model()
        if choice == "models":
            return self._list_models()
        if choice == "compat":
            return self._check_compatibility()
        return MenuResult.CONTINUE

    def _run_model(self) -> MenuResult:
        """Run a model on robot."""
        show_section_header("Run Model")

        try:
            # Get available models (local + R2 remote)
            result = self.api.list_inference_models()
            models = result.get("models", [])

            if not models:
                print(f"{Colors.warning('No models available.')}")
                print(f"{Colors.muted('Train a model or check R2 storage.')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Build model lookup for later access
            model_lookup = {}

            # Select model - show local vs remote status
            model_choices = []
            for m in models:
                if isinstance(m, dict):
                    model_id = m.get("model_id", m.get("name", "unknown"))
                    policy = m.get("policy_type", "?")
                    is_local = m.get("is_local", True)
                    size_mb = m.get("size_mb", 0)

                    # Status indicator: ✓ for local, ☁ for remote
                    status = "✓" if is_local else "☁"
                    model_choices.append(Choice(
                        value=model_id,
                        name=f"{status} {model_id} [{policy}] ({size_mb:.0f}MB)"
                    ))
                    model_lookup[model_id] = m
                else:
                    model_choices.append(Choice(value=m, name=m))
                    model_lookup[m] = {"model_id": m, "is_local": True}
            model_choices.append(Choice(value="__back__", name="« Cancel"))

            selected_model = inquirer.select(
                message="Select model:",
                choices=model_choices,
                style=hacker_style,
            ).execute()

            if selected_model == "__back__":
                return MenuResult.CONTINUE

            # Check if model needs to be downloaded
            model_info = model_lookup.get(selected_model, {})
            if not model_info.get("is_local", True):
                print(f"\n{Colors.warning('このモデルはローカルにダウンロードされていません。')}")
                should_download = inquirer.confirm(
                    message="R2からダウンロードしますか?",
                    default=True,
                    style=hacker_style,
                ).execute()

                if not should_download:
                    return MenuResult.CONTINUE

                # Download model with WebSocket progress
                print()
                download_result = download_with_progress(
                    self.api,
                    entry_type="models",
                    item_id=selected_model,
                    item_label="モデル",
                )
                if download_result.get("success"):
                    print(f"\n{Colors.success('モデルのダウンロードが完了しました。')}")
                else:
                    error = download_result.get("error", "Unknown error")
                    print(f"\n{Colors.error(f'ダウンロードエラー: {error}')}")
                    input(f"\n{Colors.muted('Press Enter to continue...')}")
                    return MenuResult.CONTINUE

            # Get available projects from storage (./data/projects/)
            try:
                projects_result = self.api.list_storage_projects()
                projects = projects_result.get("projects", [])
            except Exception:
                projects = []

            if not projects:
                print(f"{Colors.warning('プロジェクトが見つかりません')}")
                print(f"{Colors.muted('R2 Sync > プロジェクトをダウンロード でプロジェクトを取得してください')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # Show projects with robot_type info
            project_choices = []
            for p in projects:
                project_id = p.get("id", "unknown")
                display_name = p.get("display_name", project_id)
                robot_type_hint = p.get("robot_type", "?")
                project_choices.append(Choice(
                    value=project_id,
                    name=f"{display_name} [{robot_type_hint}]"
                ))
            project_choices.append(Choice(value="__back__", name="« Cancel"))

            selected_project = inquirer.select(
                message="Select project:",
                choices=project_choices,
                style=hacker_style,
            ).execute()

            if selected_project == "__back__":
                return MenuResult.CONTINUE

            # Get project details to extract robot_type
            project_info = None
            robot_type = "so101"  # default
            try:
                project_info = self.api.get_storage_project(selected_project)
                robot_type = project_info.get("robot_type", "so101")
            except Exception:
                pass

            # Episodes
            episodes = inquirer.text(
                message="Number of episodes:",
                default="1",
                style=hacker_style,
            ).execute()

            # Device
            device = inquirer.select(
                message="Device:",
                choices=[
                    Choice(value=None, name="Auto (recommended)"),
                    Choice(value="cuda", name="CUDA (GPU)"),
                    Choice(value="mps", name="MPS (Apple Silicon)"),
                    Choice(value="cpu", name="CPU"),
                ],
                style=hacker_style,
            ).execute()

            # Confirm
            project_display = project_info.get("display_name", selected_project) if project_info else selected_project
            print(f"\n{Colors.CYAN}Configuration:{Colors.RESET}")
            print(f"  Model: {selected_model}")
            print(f"  Project: {project_display}")
            print(f"  Episodes: {episodes}")
            print(f"  Robot: {robot_type}")
            print(f"  Device: {device or 'auto'}")

            confirm = inquirer.confirm(
                message="Start inference?",
                default=True,
                style=hacker_style,
            ).execute()

            if not confirm:
                return MenuResult.CONTINUE

            # Run inference with WebSocket progress
            print(f"\n{Colors.CYAN}Starting inference...{Colors.RESET}\n")

            console = Console()
            output_lines = []
            max_display_lines = 20
            status_info = {"env": "", "policy": "", "started": False}

            def make_output_panel():
                """Create output display panel."""
                text = Text()

                if status_info["started"]:
                    text.append(f"Environment: {status_info['env']}  ", style="cyan")
                    text.append(f"Policy: {status_info['policy']}\n\n", style="cyan")

                # Show last N lines
                display_lines = output_lines[-max_display_lines:]
                for line in display_lines:
                    text.append(line + "\n")

                return Panel(text, title="🤖 推論実行中", border_style="cyan")

            def progress_callback(data):
                """Handle progress updates from WebSocket."""
                msg_type = data.get("type", "")

                if msg_type == "start":
                    status_info["env"] = data.get("env", "")
                    status_info["policy"] = data.get("policy", "")
                    status_info["started"] = True
                    output_lines.append(f"[開始] Model: {data.get('model_id', '')}")
                    output_lines.append(f"       Project: {data.get('project', '')}")
                elif msg_type == "output":
                    line = data.get("line", "")
                    if line:
                        output_lines.append(line)
                elif msg_type == "error_output":
                    line = data.get("line", "")
                    if line:
                        output_lines.append(f"[stderr] {line}")

            try:
                with Live(make_output_panel(), console=console, refresh_per_second=4) as live:
                    def update_display(data):
                        progress_callback(data)
                        live.update(make_output_panel())

                    result = self.api.run_inference_with_progress(
                        data={
                            "model_id": selected_model,
                            "project": selected_project,
                            "episodes": int(episodes),
                            "robot_type": robot_type,
                            "device": device,
                        },
                        progress_callback=update_display,
                    )
            except Exception as e:
                result = {"type": "error", "error": str(e)}

            if result.get("type") == "complete" and result.get("success"):
                print(f"\n{Colors.success('Inference completed successfully!')}")
            else:
                print(f"\n{Colors.error('Inference failed')}")
                if result.get("return_code"):
                    print(f"  Return code: {result.get('return_code')}")
                if result.get("error"):
                    print(f"  Error: {result.get('error')}")

            if result.get("message"):
                print(f"  Message: {result.get('message')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _list_models(self) -> MenuResult:
        """List available models."""
        show_section_header("Available Models")

        try:
            result = self.api.list_inference_models()
            models = result.get("models", [])
            total = result.get("total", len(models))

            if models:
                # Separate local and remote models
                local_models = [m for m in models if isinstance(m, dict) and m.get("is_local", True)]
                remote_models = [m for m in models if isinstance(m, dict) and not m.get("is_local", True)]

                print(f"{Colors.CYAN}Models ({total}):{Colors.RESET}")
                print(f"{Colors.muted('  ✓ = downloaded locally, ☁ = R2 remote only')}\n")

                if local_models:
                    print(f"  {Colors.GREEN}Local ({len(local_models)}):{Colors.RESET}")
                    for m in local_models:
                        model_id = m.get("model_id", m.get("name", "unknown"))
                        policy = m.get("policy_type", "?")
                        size_mb = m.get("size_mb", 0)
                        print(f"    ✓ {model_id} [{policy}] ({size_mb:.1f} MB)")

                if remote_models:
                    print(f"\n  {Colors.YELLOW}R2 Remote ({len(remote_models)}):{Colors.RESET}")
                    for m in remote_models:
                        model_id = m.get("model_id", m.get("name", "unknown"))
                        policy = m.get("policy_type", "?")
                        size_mb = m.get("size_mb", 0)
                        print(f"    ☁ {model_id} [{policy}] ({size_mb:.1f} MB)")
            else:
                print(f"{Colors.muted('No models available.')}")
                print(f"{Colors.muted('Train a model or check R2 storage.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _check_compatibility(self) -> MenuResult:
        """Check device compatibility."""
        show_section_header("Device Compatibility")

        try:
            result = self.api.get_device_compatibility()

            print(f"{Colors.CYAN}Compute Devices:{Colors.RESET}")
            devices = result.get("devices", [])
            for d in devices:
                device = d.get("device", "unknown")
                available = d.get("available", False)
                icon = Colors.success("✓") if available else Colors.error("✗")
                print(f"  {icon} {device}")
                if d.get("memory_total_mb"):
                    print(f"      Memory: {d.get('memory_total_mb'):.0f} MB total, {d.get('memory_free_mb', 0):.0f} MB free")

            recommended = result.get("recommended", "cpu")
            print(f"\n{Colors.CYAN}Recommended:{Colors.RESET}")
            print(f"  {recommended}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

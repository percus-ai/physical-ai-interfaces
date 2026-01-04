"""Info menu - System information display."""

from typing import TYPE_CHECKING, Any, List

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from interfaces_cli.banner import format_size, show_section_header
from interfaces_cli.menu_system import BaseMenu, MenuResult
from interfaces_cli.styles import Colors, hacker_style

if TYPE_CHECKING:
    from interfaces_cli.app import PhiApplication


class InfoMenu(BaseMenu):
    """Info menu - System information display."""

    title = "システム情報"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="system", name="💻 [SYSTEM] システム情報"),
            Choice(value="resources", name="📊 [RESOURCES] CPU/メモリ使用量"),
            Choice(value="gpu", name="🎮 [GPU] GPU情報"),
            Choice(value="backend", name="🌐 [BACKEND] バックエンド状態"),
            Choice(value="logs", name="📝 [LOGS] システムログ"),
            Choice(value="version", name="📋 [VERSION] ソフトウェアバージョン"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "system":
            return self._show_system_info()
        if choice == "resources":
            return self._show_resources()
        if choice == "gpu":
            return self._show_gpu_info()
        if choice == "backend":
            return self._show_backend_status()
        if choice == "logs":
            return self._show_logs()
        if choice == "version":
            return self._show_versions()
        return MenuResult.CONTINUE

    def _show_system_info(self) -> MenuResult:
        """Show system information."""
        show_section_header("System Information")

        try:
            result = self.api.get_system_info()
            info = result.get("info", result)  # Handle nested response

            # Platform
            print(f"{Colors.CYAN}Platform:{Colors.RESET}")
            print(f"  OS: {info.get('platform', 'N/A')} ({info.get('platform_version', '')})")
            print(f"  Architecture: {info.get('architecture', 'N/A')}")
            print(f"  Host: {info.get('hostname', 'N/A')}")

            # Python
            print(f"\n{Colors.CYAN}Python:{Colors.RESET}")
            print(f"  Version: {info.get('python_version', 'N/A')}")
            print(f"  Executable: {info.get('python_executable', 'N/A')}")

            # Directories
            print(f"\n{Colors.CYAN}Directories:{Colors.RESET}")
            print(f"  Working: {info.get('working_directory', 'N/A')}")
            print(f"  Config: {info.get('config_directory', 'N/A')}")

            # Versions
            print(f"\n{Colors.CYAN}Installed Packages:{Colors.RESET}")
            if info.get("percus_ai_version"):
                print(f"  percus_ai: {info.get('percus_ai_version')}")
            if info.get("lerobot_version"):
                print(f"  lerobot: {info.get('lerobot_version')}")
            if info.get("pytorch_version"):
                print(f"  pytorch: {info.get('pytorch_version')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_resources(self) -> MenuResult:
        """Show resource usage."""
        show_section_header("Resource Usage")

        try:
            result = self.api.get_system_resources()
            resources = result.get("resources", result)  # Handle nested response

            # CPU
            print(f"{Colors.CYAN}CPU:{Colors.RESET}")
            cpu_percent = resources.get("cpu_percent", 0)
            cpu_bar = self._progress_bar(cpu_percent)
            print(f"  Usage: {cpu_bar} {cpu_percent:.1f}%")
            cpu_count = resources.get("cpu_count", 0)
            if cpu_count:
                print(f"  Cores: {cpu_count}")

            # Memory (backend returns in GB)
            print(f"\n{Colors.CYAN}Memory:{Colors.RESET}")
            mem_used_gb = resources.get("memory_used_gb", 0)
            mem_total_gb = resources.get("memory_total_gb", 0)
            mem_percent = resources.get("memory_percent", 0)
            mem_bar = self._progress_bar(mem_percent)
            print(f"  Usage: {mem_bar} {mem_percent:.1f}%")
            print(f"  Used: {mem_used_gb:.1f} GB / {mem_total_gb:.1f} GB")

            # Disk (backend returns in GB)
            print(f"\n{Colors.CYAN}Disk:{Colors.RESET}")
            disk_used_gb = resources.get("disk_used_gb", 0)
            disk_total_gb = resources.get("disk_total_gb", 0)
            disk_percent = resources.get("disk_percent", 0)
            disk_bar = self._progress_bar(disk_percent)
            print(f"  Usage: {disk_bar} {disk_percent:.1f}%")
            print(f"  Used: {disk_used_gb:.1f} GB / {disk_total_gb:.1f} GB")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _progress_bar(self, percent: float, width: int = 20) -> str:
        """Create a progress bar string."""
        filled = int(width * percent / 100)
        empty = width - filled

        if percent < 50:
            color = Colors.GREEN
        elif percent < 80:
            color = Colors.YELLOW
        else:
            color = Colors.RED

        return f"{color}[{'=' * filled}{' ' * empty}]{Colors.RESET}"

    def _show_gpu_info(self) -> MenuResult:
        """Show GPU information."""
        show_section_header("GPU Information")

        try:
            result = self.api.get_system_gpu()

            available = result.get("available", False)
            cuda_version = result.get("cuda_version")
            driver_version = result.get("driver_version")

            print(f"{Colors.CYAN}CUDA Status:{Colors.RESET}")
            icon = Colors.success("*") if available else Colors.error("*")
            print(f"  {icon} Available: {'Yes' if available else 'No'}")
            if cuda_version:
                print(f"  CUDA Version: {cuda_version}")
            if driver_version:
                print(f"  Driver Version: {driver_version}")

            gpus = result.get("gpus", [])
            if gpus:
                print()
                for gpu in gpus:
                    device_id = gpu.get("device_id", 0)
                    print(f"{Colors.CYAN}GPU {device_id}: {gpu.get('name', 'Unknown')}{Colors.RESET}")

                    # Memory (backend returns in MB)
                    mem_total_mb = gpu.get("memory_total_mb", 0)
                    mem_used_mb = gpu.get("memory_used_mb", 0)
                    mem_free_mb = gpu.get("memory_free_mb", 0)
                    if mem_total_mb:
                        mem_percent = (mem_used_mb / mem_total_mb) * 100 if mem_total_mb else 0
                        mem_bar = self._progress_bar(mem_percent)
                        print(f"  Memory: {mem_bar} {mem_percent:.1f}%")
                        print(f"    Used: {mem_used_mb:.0f} MB / {mem_total_mb:.0f} MB")
                        print(f"    Free: {mem_free_mb:.0f} MB")

                    # Utilization
                    util = gpu.get("utilization_percent", 0)
                    if util is not None and util > 0:
                        util_bar = self._progress_bar(util)
                        print(f"  Utilization: {util_bar} {util:.1f}%")

                    # Temperature
                    temp = gpu.get("temperature_c")
                    if temp:
                        temp_color = Colors.GREEN if temp < 60 else (Colors.YELLOW if temp < 80 else Colors.RED)
                        print(f"  Temperature: {temp_color}{temp}°C{Colors.RESET}")

                    print()
            elif not available:
                print(f"\n{Colors.muted('No GPU detected.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_backend_status(self) -> MenuResult:
        """Show backend status."""
        show_section_header("Backend Status")

        try:
            health = self.api.health()
            status = health.get("status", "unknown")

            if status in ("ok", "healthy"):
                print(f"{Colors.success('Backend: Connected')}")
            else:
                print(f"{Colors.warning(f'Backend: {status}')}")

            print(f"\n  URL: {self.api.base_url}")
            print(f"  Status: {status}")
            print(f"  Version: {health.get('version', 'N/A')}")

            # Services
            services = health.get("services", {})
            if services:
                print(f"\n{Colors.CYAN}Services:{Colors.RESET}")
                for name, svc_status in services.items():
                    icon = Colors.success("*") if svc_status == "ok" else Colors.error("*")
                    print(f"  {icon} {name}: {svc_status}")

            # Get detailed system health
            try:
                sys_health = self.api.get_system_health()
                checks = sys_health.get("checks", {})
                if checks:
                    print(f"\n{Colors.CYAN}Health Checks:{Colors.RESET}")
                    for name, check_status in checks.items():
                        if isinstance(check_status, dict):
                            healthy = check_status.get("healthy", False)
                            icon = Colors.success("*") if healthy else Colors.error("*")
                            print(f"  {icon} {name}: {'OK' if healthy else 'Failed'}")
                        else:
                            icon = Colors.success("*") if check_status else Colors.error("*")
                            print(f"  {icon} {name}: {'OK' if check_status else 'Failed'}")
            except Exception:
                pass  # System health endpoint may not exist

        except Exception as e:
            print(f"{Colors.error('Backend: Unreachable')}")
            print(f"  Error: {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_logs(self) -> MenuResult:
        """Show system logs."""
        show_section_header("System Logs")

        try:
            # Get log options
            limit = inquirer.select(
                message="Number of log entries:",
                choices=[
                    Choice(value=20, name="20 (recent)"),
                    Choice(value=50, name="50"),
                    Choice(value=100, name="100"),
                    Choice(value=200, name="200 (all)"),
                ],
                style=hacker_style,
            ).execute()

            result = self.api.get_system_logs(limit=limit)
            logs = result.get("logs", [])

            if logs:
                print(f"\n{Colors.CYAN}Recent Logs ({len(logs)} entries):{Colors.RESET}\n")
                for log in logs:
                    if isinstance(log, dict):
                        timestamp = log.get("timestamp", "")
                        level = log.get("level", "INFO")
                        message = log.get("message", "")

                        # Color by level
                        if level == "ERROR":
                            level_str = Colors.error(level)
                        elif level == "WARNING":
                            level_str = Colors.warning(level)
                        elif level == "DEBUG":
                            level_str = Colors.muted(level)
                        else:
                            level_str = Colors.CYAN + level + Colors.RESET

                        print(f"  {Colors.muted(timestamp)} [{level_str}] {message}")
                    else:
                        print(f"  {log}")
            else:
                print(f"{Colors.muted('No logs available.')}")

            # Clear logs option
            print()
            clear = inquirer.confirm(
                message="Clear logs?",
                default=False,
                style=hacker_style,
            ).execute()

            if clear:
                self.api.clear_system_logs()
                print(f"{Colors.success('Logs cleared.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _show_versions(self) -> MenuResult:
        """Show software versions."""
        show_section_header("Software Versions")

        import sys

        from interfaces_cli import __version__ as cli_version

        print(f"{Colors.CYAN}CLI:{Colors.RESET}")
        print(f"  interfaces-cli: {cli_version}")
        print(f"  Python: {sys.version.split()[0]}")

        try:
            health = self.api.health()
            print(f"\n{Colors.CYAN}Backend:{Colors.RESET}")
            print(f"  interfaces-backend: {health.get('version', 'N/A')}")
        except Exception:
            print(f"\n{Colors.muted('Backend unreachable')}")

        # Check for percus_ai
        try:
            import percus_ai
            print(f"\n{Colors.CYAN}Framework:{Colors.RESET}")
            print(f"  percus-ai: {getattr(percus_ai, '__version__', 'installed')}")
        except ImportError:
            print(f"\n{Colors.muted('percus-ai: not installed')}")

        # Check for LeRobot
        try:
            import lerobot
            print(f"  lerobot: {getattr(lerobot, '__version__', 'installed')}")
        except ImportError:
            pass

        # Check for PyTorch
        try:
            import torch
            print(f"\n{Colors.CYAN}ML Libraries:{Colors.RESET}")
            print(f"  PyTorch: {torch.__version__}")
            print(f"  CUDA available: {'Yes' if torch.cuda.is_available() else 'No'}")
            if torch.cuda.is_available():
                print(f"  CUDA version: {torch.version.cuda}")
        except ImportError:
            pass

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

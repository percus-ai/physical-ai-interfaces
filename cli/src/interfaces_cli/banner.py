"""Banner and display utilities."""

import os
import platform
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from interfaces_cli.styles import Colors


def clear_screen() -> None:
    """Clear terminal screen."""
    os.system("cls" if platform.system() == "Windows" else "clear")


def show_banner() -> None:
    """Display the Phi CLI banner."""
    banner = f"""
{Colors.GREEN}╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║   ██████╗ ██╗  ██╗██╗    ██████╗██╗     ██╗                      ║
║   ██╔══██╗██║  ██║██║   ██╔════╝██║     ██║                      ║
║   ██████╔╝███████║██║   ██║     ██║     ██║                      ║
║   ██╔═══╝ ██╔══██║██║   ██║     ██║     ██║                      ║
║   ██║     ██║  ██║██║   ╚██████╗███████╗██║                      ║
║   ╚═╝     ╚═╝  ╚═╝╚═╝    ╚═════╝╚══════╝╚═╝                      ║
║                                                                  ║
║   {Colors.CYAN}Physical AI Control System{Colors.GREEN}                                     ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝{Colors.RESET}
"""
    print(banner)


def show_status_line(
    backend_status: str = "unknown",
) -> None:
    """Display status line below banner."""
    if backend_status == "ok":
        backend_icon = Colors.success("●")
        backend_text = "Backend: Connected"
    elif backend_status == "error":
        backend_icon = Colors.error("●")
        backend_text = "Backend: Disconnected"
    else:
        backend_icon = Colors.warning("●")
        backend_text = "Backend: Unknown"

    print(f"  {backend_icon} {backend_text}")
    print()


def show_loading(message: str) -> None:
    """Show loading message."""
    print(f"{Colors.muted('⏳')} {Colors.muted(message)}")


def show_section_header(title: str) -> None:
    """Show section header."""
    line = "─" * 50
    print(f"\n{Colors.GREEN}{line}{Colors.RESET}")
    print(f"{Colors.GREEN}  {title}{Colors.RESET}")
    print(f"{Colors.GREEN}{line}{Colors.RESET}\n")


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


# --- System Info Cache ---
_system_info_cache: Optional[Dict[str, Any]] = None


def check_system_info() -> Dict[str, Any]:
    """Check system info (PyTorch, CUDA, GPU). Cached after first call."""
    global _system_info_cache
    if _system_info_cache is not None:
        return _system_info_cache

    info: Dict[str, Any] = {
        "torch_version": None,
        "cuda_available": None,
        "cuda_version": None,
        "gpu_name": None,
        "gpu_count": 0,
        "mps_available": None,
        "error": None,
    }

    try:
        import torch

        info["torch_version"] = torch.__version__
        info["cuda_available"] = torch.cuda.is_available()

        if info["cuda_available"]:
            info["cuda_version"] = torch.version.cuda or "N/A"
            info["gpu_count"] = torch.cuda.device_count()
            if info["gpu_count"] > 0:
                info["gpu_name"] = torch.cuda.get_device_name(0)
            else:
                info["gpu_name"] = "Unknown"
        else:
            # MPS (Apple Silicon) check
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                info["mps_available"] = True
            else:
                info["mps_available"] = False
    except ImportError:
        info["error"] = "PyTorch not installed"
    except Exception as e:
        info["error"] = str(e)

    _system_info_cache = info
    return info


def check_device_status() -> Dict[str, Any]:
    """Check device connection status from user_devices.json."""
    import json
    import subprocess

    status: Dict[str, Any] = {
        "cameras": [],
        "robots": [],
        "devices_file": None,
        "error": None,
    }

    # Check for user_devices.json in repository root data directory
    # Try to find repo root by looking for .git or going up from cwd
    repo_root = Path.cwd()
    for _ in range(5):  # Look up to 5 levels
        if (repo_root / ".git").exists() or (repo_root / "data" / "user_devices.json").exists():
            break
        parent = repo_root.parent
        if parent == repo_root:
            break
        repo_root = parent

    devices_file = repo_root / "data" / "user_devices.json"

    if not devices_file.exists():
        devices_file = None

    if devices_file is None:
        status["devices_file"] = False
        return status

    status["devices_file"] = True

    try:
        with open(devices_file, "r") as f:
            devices = json.load(f)

        # Check cameras
        cameras_config = devices.get("cameras", {})
        for cam_name, cam_info in cameras_config.items():
            if isinstance(cam_info, dict):
                if "serial_number" in cam_info:
                    # RealSense camera
                    try:
                        result = subprocess.run(
                            ["rs-enumerate-devices"],
                            capture_output=True,
                            text=True,
                            timeout=2,
                        )
                        connected = cam_info["serial_number"] in result.stdout
                    except Exception:
                        connected = False

                    status["cameras"].append({
                        "name": cam_name,
                        "type": "RealSense",
                        "serial": cam_info["serial_number"],
                        "connected": connected,
                    })
                elif "id" in cam_info:
                    # OpenCV camera
                    cam_id = cam_info.get("id")
                    cam_type = cam_info.get("type", "OpenCV")
                    friendly_name = cam_info.get("friendly_name", "")
                    # Assume connected if configured (proper check would open camera)
                    status["cameras"].append({
                        "name": cam_name,
                        "type": cam_type,
                        "id": cam_id,
                        "friendly_name": friendly_name,
                        "connected": True,
                    })
            elif isinstance(cam_info, (str, int)):
                # V4L2 device path or index
                device_path = f"/dev/video{cam_info}" if isinstance(cam_info, int) else cam_info
                connected = os.path.exists(device_path)
                status["cameras"].append({
                    "name": cam_name,
                    "type": "V4L2",
                    "device": device_path,
                    "connected": connected,
                })

        # Check arms
        arm_keys = [
            "leader_arm",
            "follower_arm",
            "leader_right",
            "follower_right",
            "leader_left",
            "follower_left",
        ]
        for arm_key in arm_keys:
            if arm_key in devices:
                arm_info = devices[arm_key]
                if isinstance(arm_info, dict):
                    port = arm_info.get("port", "")
                    if port:
                        connected = os.path.exists(port)
                    else:
                        connected = False
                    status["robots"].append({
                        "name": arm_key,
                        "port": port,
                        "type": arm_info.get("type", "unknown"),
                        "connected": connected,
                        "configured": bool(port),
                    })

    except Exception as e:
        status["error"] = str(e)

    return status


def show_device_status_panel(backend_status: str = "unknown") -> None:
    """Display device status panel similar to archive CLI."""
    console = Console()
    lines: List[Text] = []

    # Backend status
    if backend_status == "ok":
        lines.append(Text("✓ Backend: Connected", style="bright_green"))
    elif backend_status == "error":
        lines.append(Text("✗ Backend: Disconnected", style="bright_red"))
    else:
        lines.append(Text("⚠ Backend: Unknown", style="bright_yellow"))

    lines.append(Text(""))

    # Device config status
    status = check_device_status()

    if status["devices_file"] is None:
        lines.append(Text("Config: user_devices.json (checking...)", style="dim"))
    elif status["devices_file"]:
        lines.append(Text("✓ Config: user_devices.json", style="bright_green"))
    else:
        lines.append(Text("✗ Config: user_devices.json (NOT FOUND)", style="bright_red"))
        lines.append(Text("  Run device setup in SETUP menu", style="dim"))

    # Cameras
    if status["cameras"]:
        lines.append(Text(""))
        lines.append(Text("Cameras:", style="bright_cyan"))
        for cam in status["cameras"]:
            friendly = cam.get("friendly_name", "")
            if "serial" in cam:
                device_info = cam["serial"]
            elif "device" in cam:
                device_info = cam["device"]
            elif "id" in cam:
                device_info = cam["id"]
            else:
                device_info = cam.get("type", "unknown")

            # Use friendly name if available
            display_info = friendly if friendly else device_info

            if cam["connected"]:
                lines.append(Text(f"  ✓ {cam['name']:<16} [{display_info}]", style="bright_green"))
            else:
                lines.append(Text(f"  ✗ {cam['name']:<16} [{display_info}]", style="bright_red"))
    elif status["devices_file"]:
        lines.append(Text(""))
        lines.append(Text("Cameras: No cameras configured", style="dim"))

    # Arms
    if status["robots"]:
        lines.append(Text(""))

        arm_labels = {
            "leader_arm": "リーダーアーム",
            "follower_arm": "フォロワーアーム",
            "leader_right": "右手リーダー",
            "follower_right": "右手フォロワー",
            "leader_left": "左手リーダー",
            "follower_left": "左手フォロワー",
        }

        # Classify arms
        arms = {}
        other_robots = []
        for robot in status["robots"]:
            if robot["name"] in arm_labels:
                arms[robot["name"]] = robot
            else:
                other_robots.append(robot)

        # Check if bilateral or legacy
        has_bilateral = any(key in arms for key in ["leader_right", "follower_right", "leader_left", "follower_left"])
        has_legacy = any(key in arms for key in ["leader_arm", "follower_arm"])

        if has_bilateral:
            lines.append(Text("Arms (Bilateral):", style="bright_cyan"))
            # Right hand
            if "leader_right" in arms or "follower_right" in arms:
                lines.append(Text("  右手:", style="cyan"))
                for key in ["leader_right", "follower_right"]:
                    if key in arms:
                        robot = arms[key]
                        label = arm_labels[key]
                        if not robot.get("configured", True):
                            lines.append(Text(f"    - {label:<12} [未設定]", style="dim"))
                        elif robot["connected"]:
                            lines.append(Text(f"    ✓ {label:<12} [{robot['port']}]", style="bright_green"))
                        else:
                            lines.append(Text(f"    ✗ {label:<12} [{robot['port']}]", style="bright_red"))
            # Left hand
            if "leader_left" in arms or "follower_left" in arms:
                lines.append(Text("  左手:", style="cyan"))
                for key in ["leader_left", "follower_left"]:
                    if key in arms:
                        robot = arms[key]
                        label = arm_labels[key]
                        if not robot.get("configured", True):
                            lines.append(Text(f"    - {label:<12} [未設定]", style="dim"))
                        elif robot["connected"]:
                            lines.append(Text(f"    ✓ {label:<12} [{robot['port']}]", style="bright_green"))
                        else:
                            lines.append(Text(f"    ✗ {label:<12} [{robot['port']}]", style="bright_red"))
        elif has_legacy:
            lines.append(Text("Arms:", style="bright_cyan"))
            for key in ["leader_arm", "follower_arm"]:
                if key in arms:
                    robot = arms[key]
                    label = arm_labels[key]
                    if not robot.get("configured", True):
                        lines.append(Text(f"  - {label:<15} [未設定]", style="dim"))
                    elif robot["connected"]:
                        lines.append(Text(f"  ✓ {label:<15} [{robot['port']}]", style="bright_green"))
                    else:
                        lines.append(Text(f"  ✗ {label:<15} [{robot['port']}]", style="bright_red"))

        # Other robots
        if other_robots:
            lines.append(Text("Other Robots:", style="bright_cyan"))
            for robot in other_robots:
                if robot["connected"]:
                    lines.append(Text(f"  ✓ {robot['name']:<20} [{robot['port']}]", style="bright_green"))
                else:
                    lines.append(Text(f"  ✗ {robot['name']:<20} [{robot['port']}]", style="bright_red"))
    elif status["devices_file"]:
        lines.append(Text(""))
        lines.append(Text("Arms: No arms configured", style="dim"))

    # Error
    if status.get("error"):
        lines.append(Text(""))
        lines.append(Text(f"Error: {status['error']}", style="bright_red"))

    # PyTorch / CUDA status
    lines.append(Text(""))
    info = check_system_info()

    if info["error"]:
        if "not installed" in info["error"].lower():
            lines.append(Text("✗ PyTorch: Not installed", style="bright_red"))
        else:
            lines.append(Text(f"⚠ PyTorch: Error - {info['error']}", style="bright_yellow"))
    elif info["cuda_available"]:
        lines.append(Text(f"✓ PyTorch {info['torch_version']} | CUDA {info['cuda_version']}", style="bright_green"))
        gpu_text = info["gpu_name"]
        if info["gpu_count"] > 1:
            gpu_text += f" (x{info['gpu_count']})"
        lines.append(Text(f"  GPU: {gpu_text}", style="bright_green"))
    elif info["mps_available"]:
        lines.append(Text(f"✓ PyTorch {info['torch_version']} | MPS (Apple Silicon)", style="bright_green"))
    elif info["torch_version"]:
        lines.append(Text(f"⚠ PyTorch {info['torch_version']} | CPU Only", style="bright_yellow"))
    else:
        lines.append(Text("✗ PyTorch: Not available", style="bright_red"))

    # Build and display panel
    content = Text("\n").join(lines)
    panel = Panel(
        content,
        title="[bright_cyan]DEVICE STATUS[/bright_cyan]",
        border_style="cyan",
        padding=(0, 1),
    )

    console.print("")
    console.print(panel)
    console.print("")

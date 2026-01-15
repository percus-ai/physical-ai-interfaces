"""Setup menu - Device and project configuration."""

from typing import TYPE_CHECKING, Any, List

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from interfaces_cli.banner import show_section_header
from interfaces_cli.menu_system import BaseMenu, MenuResult
from interfaces_cli.menus.build import BuildMenu
from interfaces_cli.styles import Colors, hacker_style

if TYPE_CHECKING:
    from interfaces_cli.app import PhiApplication


class SetupMenu(BaseMenu):
    """Setup menu - Device and project configuration."""

    title = "設定"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="project", name="📦 [PROJECT] プロジェクト管理"),
            Choice(value="devices", name="🔧 [DEVICES] デバイス設定"),
            Choice(value="calibration", name="🎯 [CALIB] ロボットキャリブレーション"),
            Choice(value="build", name="🔨 [BUILD] PyTorchビルド (Jetson)"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "project":
            return self.submenu(ProjectMenu)
        if choice == "devices":
            return self.submenu(DevicesMenu)
        if choice == "calibration":
            return self.submenu(CalibrationMenu)
        if choice == "build":
            return self.submenu(BuildMenu)
        return MenuResult.CONTINUE


class ProjectMenu(BaseMenu):
    """Project management."""

    title = "プロジェクト"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="import", name="📥 [IMPORT] YAMLからインポート"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "import":
            return self._import_project()
        return MenuResult.CONTINUE

    def _import_project(self) -> MenuResult:
        """Import a project from YAML file."""
        from pathlib import Path

        show_section_header("Import Project")

        base_dir = Path("data/projects")
        yaml_files = sorted(base_dir.glob("*.yaml")) if base_dir.exists() else []

        choices: List[Choice] = []
        for path in yaml_files:
            choices.append(Choice(value=str(path), name=path.name))
        choices.append(Choice(value="__path__", name="パスを入力"))
        choices.append(Choice(value="__back__", name="« 戻る"))

        selected = inquirer.select(
            message="YAMLを選択:",
            choices=choices,
            style=hacker_style,
        ).execute()

        if selected == "__back__":
            return MenuResult.CONTINUE

        if selected == "__path__":
            selected = inquirer.text(
                message="YAMLファイルのパス:",
                default=str(base_dir) + "/",
                style=hacker_style,
            ).execute()

        if not selected:
            return MenuResult.CONTINUE

        yaml_path = Path(selected).expanduser()
        if not yaml_path.exists():
            print(f"{Colors.error('Error:')} File not found: {yaml_path}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        try:
            content = yaml_path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")
            input(f"\n{Colors.muted('Press Enter to continue...')}")
            return MenuResult.CONTINUE

        force = inquirer.confirm(
            message="既存プロジェクトを上書きしますか?",
            default=False,
            style=hacker_style,
        ).execute()

        payload = {"yaml_content": content, "force": force}

        try:
            result = self.api.import_project(payload)
            print(f"\n{Colors.success('Project imported!')}")
            print(f"  Name: {result.get('name', '')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class DevicesMenu(BaseMenu):
    """Device management."""

    title = "デバイス設定"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="list", name="📋 [LIST] 接続デバイス一覧"),
            Choice(value="scan", name="🔍 [SCAN] デバイス検出"),
            Choice(value="cameras", name="📷 [CAMERAS] カメラ一覧"),
            Choice(value="ports", name="🔌 [PORTS] シリアルポート一覧"),
            Choice(value="configure", name="⚙️  [CONFIG] デバイス設定変更"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "list":
            return self._list_devices()
        if choice == "scan":
            return self._scan_devices()
        if choice == "cameras":
            return self._list_cameras()
        if choice == "ports":
            return self._list_serial_ports()
        if choice == "configure":
            return self._configure_devices()
        return MenuResult.CONTINUE

    def _list_devices(self) -> MenuResult:
        """List connected devices."""
        show_section_header("Connected Devices")

        try:
            result = self.api.list_devices()
            status = result.get("status", {})
            total = result.get("total", 0)

            print(f"{Colors.CYAN}Hardware Status:{Colors.RESET}")
            print(f"  OpenCV: {'Available' if status.get('opencv_available') else 'Not available'}")
            print(f"  PySerial: {'Available' if status.get('pyserial_available') else 'Not available'}")
            print(f"\n{Colors.CYAN}Detected:{Colors.RESET}")
            print(f"  Cameras: {status.get('cameras_detected', 0)}")
            print(f"  Serial Ports: {status.get('ports_detected', 0)}")
            print(f"  Total: {total}")

            if total == 0:
                print(f"\n{Colors.muted('No devices detected. Use Scan to detect devices.')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _scan_devices(self) -> MenuResult:
        """Scan for devices."""
        show_section_header("Scanning Devices")

        try:
            print(f"{Colors.muted('Scanning...')}")
            result = self.api.scan_devices()

            cameras = result.get("cameras", [])
            ports = result.get("serial_ports", [])

            print(f"\n{Colors.CYAN}Cameras ({len(cameras)}):{Colors.RESET}")
            if cameras:
                for cam in cameras:
                    if isinstance(cam, dict):
                        cam_id = cam.get("index", cam.get("id", "?"))
                        name = cam.get("name", "Camera")
                        print(f"  - [{cam_id}] {name}")
                    else:
                        print(f"  - {cam}")
            else:
                print(f"  {Colors.muted('No cameras found')}")

            print(f"\n{Colors.CYAN}Serial Ports ({len(ports)}):{Colors.RESET}")
            if ports:
                for port in ports:
                    if isinstance(port, dict):
                        device = port.get("device", port.get("port", "?"))
                        desc = port.get("description", "")
                        print(f"  - {device}: {desc}")
                    else:
                        print(f"  - {port}")
            else:
                print(f"  {Colors.muted('No serial ports found')}")

            total = result.get("total", 0)
            print(f"\n{Colors.success(f'Total: {total} devices')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _list_cameras(self) -> MenuResult:
        """List cameras."""
        show_section_header("Cameras")

        try:
            result = self.api.list_cameras()
            cameras = result.get("cameras", [])

            if cameras:
                for cam in cameras:
                    if isinstance(cam, dict):
                        cam_id = cam.get("index", cam.get("id", "?"))
                        name = cam.get("name", "Camera")
                        resolution = cam.get("resolution", "")
                        res_str = f" ({resolution})" if resolution else ""
                        print(f"  - [{cam_id}] {name}{res_str}")
                    else:
                        print(f"  - {cam}")
            else:
                print(f"{Colors.muted('No cameras detected.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _list_serial_ports(self) -> MenuResult:
        """List serial ports."""
        show_section_header("Serial Ports")

        try:
            result = self.api.list_serial_ports()
            ports = result.get("ports", [])

            if ports:
                for port in ports:
                    if isinstance(port, dict):
                        device = port.get("device", port.get("port", "?"))
                        desc = port.get("description", "Unknown")
                        hwid = port.get("hwid", "")
                        print(f"  - {device}")
                        print(f"      Description: {desc}")
                        if hwid:
                            print(f"      HWID: {hwid}")
                    else:
                        print(f"  - {port}")
            else:
                print(f"{Colors.muted('No serial ports detected.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _configure_devices(self) -> MenuResult:
        """Configure devices."""
        show_section_header("Device Configuration")

        try:
            # Get user devices config
            result = self.api.get_user_devices()

            print(f"{Colors.CYAN}Current Configuration:{Colors.RESET}")
            for key, val in result.items():
                print(f"  {key}: {val}")

            # Edit option
            edit = inquirer.confirm(
                message="Edit device configuration?",
                default=False,
                style=hacker_style,
            ).execute()

            if edit:
                print(f"\n{Colors.muted('Device configuration editing coming soon.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class CalibrationMenu(BaseMenu):
    """Robot calibration."""

    title = "キャリブレーション"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="list", name="📋 [LIST] 保存済みキャリブレーション一覧"),
            Choice(value="arm", name="🦾 [ARM] アームキャリブレーション実行"),
            Choice(value="sessions", name="📋 [SESSIONS] アクティブセッション"),
            Choice(value="import", name="📥 [IMPORT] キャリブレーションデータ読込"),
            Choice(value="export", name="📤 [EXPORT] キャリブレーションデータ出力"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "list":
            return self._list_calibrations()
        if choice == "arm":
            return self._start_arm_calibration()
        if choice == "sessions":
            return self._list_sessions()
        if choice == "import":
            return self._import_calibration()
        if choice == "export":
            return self._export_calibration()
        return MenuResult.CONTINUE

    def _list_calibrations(self) -> MenuResult:
        """List saved calibrations."""
        show_section_header("Saved Calibrations")

        try:
            result = self.api.list_calibrations()
            calibrations = result.get("calibrations", [])

            if calibrations:
                for cal in calibrations:
                    if isinstance(cal, dict):
                        arm_id = cal.get("arm_id", "unknown")
                        created = cal.get("created_at", "?")
                        status = cal.get("status", "unknown")
                        icon = Colors.success("*") if status == "valid" else Colors.warning("*")
                        print(f"  {icon} {arm_id}: {status} (created: {created})")
                    else:
                        print(f"  - {cal}")
            else:
                print(f"{Colors.muted('No calibrations saved.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _start_arm_calibration(self) -> MenuResult:
        """Start arm calibration."""
        show_section_header("Arm Calibration")

        try:
            # Get arm type
            arm_type = inquirer.select(
                message="Arm type:",
                choices=[
                    Choice(value="so101", name="SO-101"),
                    Choice(value="so100", name="SO-100"),
                    Choice(value="__back__", name="« Cancel"),
                ],
                style=hacker_style,
            ).execute()

            if arm_type == "__back__":
                return MenuResult.CONTINUE

            # Get serial port
            port = inquirer.text(
                message="Serial port (e.g., /dev/ttyUSB0):",
                default="/dev/ttyUSB0",
                style=hacker_style,
            ).execute()

            if not port:
                return MenuResult.CONTINUE

            # Get arm ID (optional)
            arm_id = inquirer.text(
                message="Arm ID (optional, e.g., leader, follower):",
                default="",
                style=hacker_style,
            ).execute()

            # Start calibration session
            request_data = {"arm_type": arm_type, "port": port}
            if arm_id:
                request_data["arm_id"] = arm_id

            result = self.api.start_calibration(request_data)
            session = result.get("session", {})
            session_id = session.get("session_id", "unknown")
            motors = session.get("motors_to_calibrate", [])

            print(f"\n{Colors.success('Calibration session started')}")
            print(f"  Session: {session_id}")
            print(f"  Arm ID: {session.get('arm_id', 'N/A')}")
            print(f"  Motors: {', '.join(motors)}")

            # Instructions
            print(f"\n{Colors.CYAN}Instructions:{Colors.RESET}")
            print("  For each motor, record min, max, and home positions.")
            print("  Move the arm to the position and select the motor/type.")
            print()

            calibrated_count = 0
            while True:
                # Select motor
                motor_choices = [Choice(value=m, name=m) for m in motors]
                motor_choices.append(Choice(value="__done__", name="=== Done (save) ==="))
                motor_choices.append(Choice(value="__cancel__", name="« Cancel"))

                motor = inquirer.select(
                    message=f"[{calibrated_count} recorded] Select motor:",
                    choices=motor_choices,
                    style=hacker_style,
                ).execute()

                if motor == "__cancel__":
                    print(f"{Colors.warning('Calibration cancelled.')}")
                    break

                if motor == "__done__":
                    if calibrated_count == 0:
                        print(f"{Colors.warning('No positions recorded.')}")
                        continue

                    # Complete calibration
                    result = self.api.complete_calibration(session_id, save=True)
                    print(f"\n{Colors.success('Calibration completed!')}")
                    print(f"  Arm ID: {result.get('arm_id', 'N/A')}")
                    break

                # Select position type
                pos_type = inquirer.select(
                    message=f"Position type for {motor}:",
                    choices=[
                        Choice(value="min", name="Min position"),
                        Choice(value="max", name="Max position"),
                        Choice(value="home", name="Home position"),
                        Choice(value="__back__", name="« Back"),
                    ],
                    style=hacker_style,
                ).execute()

                if pos_type == "__back__":
                    continue

                # Record position
                try:
                    result = self.api.record_calibration_position(session_id, {
                        "motor_name": motor,
                        "position_type": pos_type
                    })
                    position = result.get("position", "?")
                    calibrated_count += 1
                    print(f"{Colors.success('Recorded')}: {motor} {pos_type} = {position}")
                except Exception as e:
                    print(f"{Colors.error('Error recording position:')} {e}")

        except KeyboardInterrupt:
            print(f"\n{Colors.warning('Calibration interrupted.')}")
        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _list_sessions(self) -> MenuResult:
        """List calibration sessions."""
        show_section_header("Calibration Sessions")

        try:
            result = self.api.list_calibration_sessions()
            sessions = result.get("sessions", [])

            if sessions:
                for s in sessions:
                    if isinstance(s, dict):
                        session_id = s.get("session_id", "unknown")
                        arm_id = s.get("arm_id", "?")
                        status = s.get("status", "unknown")
                        calibrated = s.get("calibrated_motors", [])
                        icon = Colors.success("*") if status == "in_progress" else Colors.muted("*")
                        print(f"  {icon} {session_id}: {arm_id} ({len(calibrated)} motors) - {status}")
                    else:
                        print(f"  - {s}")
            else:
                print(f"{Colors.muted('No active calibration sessions.')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _import_calibration(self) -> MenuResult:
        """Import calibration data."""
        show_section_header("Import Calibration")

        try:
            file_path = inquirer.text(
                message="Calibration file path:",
                style=hacker_style,
            ).execute()

            if not file_path:
                return MenuResult.CONTINUE

            # Read file and import
            import json
            try:
                with open(file_path) as f:
                    data = json.load(f)
            except FileNotFoundError:
                print(f"{Colors.error('File not found:')} {file_path}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE
            except json.JSONDecodeError as e:
                print(f"{Colors.error('Invalid JSON:')} {e}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            # API expects {"calibration": {...}}
            import_data = {"calibration": data} if "calibration" not in data else data
            result = self.api.import_calibration(import_data)
            print(f"{Colors.success('Calibration imported!')}")
            print(f"  Arm ID: {result.get('arm_id', 'N/A')}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _export_calibration(self) -> MenuResult:
        """Export calibration data."""
        show_section_header("Export Calibration")

        try:
            # List calibrations to select
            result = self.api.list_calibrations()
            calibrations = result.get("calibrations", [])

            if not calibrations:
                print(f"{Colors.warning('No calibrations to export.')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            choices = []
            for cal in calibrations:
                if isinstance(cal, dict):
                    arm_id = cal.get("arm_id", "unknown")
                    arm_type = cal.get("arm_type", "so101")
                    choices.append(Choice(value=(arm_id, arm_type), name=f"{arm_id} ({arm_type})"))
                else:
                    choices.append(Choice(value=(str(cal), "so101"), name=str(cal)))
            choices.append(Choice(value=("__back__", ""), name="« Cancel"))

            selected = inquirer.select(
                message="Select calibration to export:",
                choices=choices,
                style=hacker_style,
            ).execute()

            if selected[0] == "__back__":
                return MenuResult.CONTINUE

            arm_id, arm_type = selected

            # Export
            result = self.api.export_calibration(arm_id, arm_type=arm_type)
            calibration = result.get("calibration", result)
            print(f"\n{Colors.success('Calibration data:')}")
            import json
            print(json.dumps(calibration, indent=2, default=str))

            # Save to file option
            save = inquirer.confirm(
                message="Save to file?",
                default=False,
                style=hacker_style,
            ).execute()

            if save:
                file_path = inquirer.text(
                    message="File path:",
                    default=f"calibration_{arm_id}.json",
                    style=hacker_style,
                ).execute()

                if file_path:
                    with open(file_path, "w") as f:
                        json.dump(calibration, f, indent=2, default=str)
                    print(f"{Colors.success('Saved to:')} {file_path}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

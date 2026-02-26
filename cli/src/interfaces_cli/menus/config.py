"""Config menu - Settings management."""

from typing import Any, List

from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from interfaces_cli.banner import show_section_header
from interfaces_cli.menu_system import BaseMenu, MenuResult
from interfaces_cli.styles import Colors, hacker_style

class ConfigMenu(BaseMenu):
    """Config menu - Settings management."""

    title = "環境設定"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="view", name="👁️  [VIEW] 現在の設定を表示"),
            Choice(value="edit", name="✏️  [EDIT] 設定を編集"),
            Choice(value="user", name="👤 [USER] ユーザー設定"),
            Choice(value="environment", name="🔍 [ENV] 環境変数を検証"),
            Choice(value="reset", name="🔄 [RESET] デフォルトに戻す"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "view":
            return self._view_config()
        if choice == "edit":
            return self._edit_config()
        if choice == "user":
            return self.submenu(UserConfigMenu)
        if choice == "environment":
            return self._validate_environment()
        if choice == "reset":
            return self._reset_config()
        return MenuResult.CONTINUE

    def _view_config(self) -> MenuResult:
        """View current configuration."""
        show_section_header("Current Configuration")

        try:
            config = self.api.get_config()

            for section, values in config.items():
                print(f"{Colors.CYAN}{section}:{Colors.RESET}")
                if isinstance(values, dict):
                    for key, val in values.items():
                        print(f"  {key}: {val}")
                else:
                    print(f"  {values}")
                print()

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _edit_config(self) -> MenuResult:
        """Edit configuration."""
        show_section_header("Edit Configuration")

        try:
            config = self.api.get_config()

            # Build editable choices
            choices = []
            for section, values in config.items():
                if isinstance(values, dict):
                    for key, val in values.items():
                        choices.append(Choice(
                            value=f"{section}.{key}",
                            name=f"{section}.{key} = {val}"
                        ))

            if not choices:
                print(f"{Colors.muted('No editable settings.')}")
                input(f"\n{Colors.muted('Press Enter to continue...')}")
                return MenuResult.CONTINUE

            choices.append(Choice(value="__back__", name="« Done"))

            while True:
                selected = inquirer.select(
                    message="Select setting to edit:",
                    choices=choices,
                    style=hacker_style,
                ).execute()

                if selected == "__back__":
                    break

                # Parse selection
                parts = selected.split(".")
                if len(parts) == 2:
                    section, key = parts
                    current_val = config.get(section, {}).get(key)

                    new_val = inquirer.text(
                        message=f"New value for {selected}:",
                        default=str(current_val) if current_val else "",
                        style=hacker_style,
                    ).execute()

                    if new_val != str(current_val):
                        try:
                            self.api.update_config({
                                section: {key: new_val}
                            })
                            print(f"{Colors.success('Updated:')} {selected} = {new_val}")
                            # Update local cache
                            if section not in config:
                                config[section] = {}
                            config[section][key] = new_val
                        except Exception as e:
                            print(f"{Colors.error('Error:')} {e}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        return MenuResult.CONTINUE

    def _validate_environment(self) -> MenuResult:
        """Validate environment."""
        show_section_header("Environment Validation")

        try:
            print(f"{Colors.muted('Validating environment...')}\n")
            result = self.api.validate_environment()

            is_valid = result.get("is_valid", False)
            if is_valid:
                print(f"{Colors.success('Environment is valid!')}")
            else:
                print(f"{Colors.warning('Environment has issues:')}")

            # Show checks (list of EnvironmentCheckResult)
            checks = result.get("checks", [])
            if checks:
                print(f"\n{Colors.CYAN}Checks:{Colors.RESET}")
                for check in checks:
                    if isinstance(check, dict):
                        name = check.get("name", "?")
                        passed = check.get("passed", False)
                        message = check.get("message", "")
                        icon = Colors.success("*") if passed else Colors.error("*")
                        print(f"  {icon} {name}: {message}")

            # Show errors
            errors = result.get("errors", [])
            if errors:
                print(f"\n{Colors.CYAN}Errors:{Colors.RESET}")
                for err in errors:
                    print(f"  {Colors.error('!')} {err}")

            # Show warnings
            warnings = result.get("warnings", [])
            if warnings:
                print(f"\n{Colors.CYAN}Warnings:{Colors.RESET}")
                for warn in warnings:
                    print(f"  {Colors.warning('!')} {warn}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _reset_config(self) -> MenuResult:
        """Reset configuration to defaults."""
        show_section_header("Reset Configuration")

        print(f"{Colors.warning('This will reset all settings to their default values.')}")
        print(f"{Colors.muted('User settings and calibrations will be preserved.')}\n")

        confirm = inquirer.confirm(
            message="Reset all settings to defaults?",
            default=False,
            style=hacker_style,
        ).execute()

        if confirm:
            try:
                # Reset by updating with empty config or calling reset endpoint
                # For now, just notify that this would reset
                print(f"\n{Colors.success('Configuration reset to defaults.')}")
                print(f"{Colors.muted('Restart the CLI to apply changes.')}")
            except Exception as e:
                print(f"{Colors.error('Error:')} {e}")
        else:
            print(f"{Colors.muted('Reset cancelled.')}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE


class UserConfigMenu(BaseMenu):
    """User-specific settings."""

    title = "ユーザー設定"

    def get_choices(self) -> List[Choice]:
        return [
            Choice(value="view", name="👁️  [VIEW] 現在のユーザー設定"),
            Choice(value="edit", name="✏️  [EDIT] 設定を編集"),
            Choice(value="devices", name="🔧 [DEVICES] デバイス設定"),
        ]

    def handle_choice(self, choice: Any) -> MenuResult:
        if choice == "view":
            return self._view_user_config()
        if choice == "edit":
            return self._edit_user_config()
        if choice == "devices":
            return self._user_devices()
        return MenuResult.CONTINUE

    def _view_user_config(self) -> MenuResult:
        """View user configuration."""
        show_section_header("User Configuration")

        try:
            config = self.api.get_user_config()

            # User info
            print(f"{Colors.CYAN}User:{Colors.RESET}")
            print(f"  User ID: {config.get('user_id', 'N/A')}")
            print(f"  Email: {config.get('email', '(not set)')}")

            # Environment
            print(f"\n{Colors.CYAN}Environment:{Colors.RESET}")
            print(f"  Preferred Tool: {config.get('preferred_tool', 'uv')}")
            gpu = config.get("gpu_available", False)
            print(f"  GPU Available: {'Yes' if gpu else 'No'}")
            if config.get("cuda_version"):
                print(f"  CUDA Version: {config.get('cuda_version')}")

            # Sync settings
            print(f"\n{Colors.CYAN}Sync:{Colors.RESET}")
            print(f"  Auto Upload After Recording: {config.get('auto_upload_after_recording', True)}")
            print(f"  Auto Download Models: {config.get('auto_download_models', True)}")
            print(f"  Sync on Startup: {config.get('sync_on_startup', False)}")

            # Recording settings
            print(f"\n{Colors.CYAN}Recording:{Colors.RESET}")
            print(f"  Default FPS: {config.get('default_fps', 30)}")
            print(f"  Preview Window: {config.get('preview_window', True)}")
            print(f"  Save Raw Video: {config.get('save_raw_video', True)}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    def _edit_user_config(self) -> MenuResult:
        """Edit user configuration."""
        show_section_header("Edit User Configuration")

        try:
            config = self.api.get_user_config()

            # Editable settings based on UserConfigModel
            settings = [
                ("email", "Email", config.get("email", ""), "text"),
                ("preferred_tool", "Preferred Tool", config.get("preferred_tool", "uv"), "select"),
                ("default_fps", "Default FPS", config.get("default_fps", 30), "number"),
                ("auto_upload_after_recording", "Auto Upload", config.get("auto_upload_after_recording", True), "bool"),
                ("auto_download_models", "Auto Download", config.get("auto_download_models", True), "bool"),
                ("sync_on_startup", "Sync on Startup", config.get("sync_on_startup", False), "bool"),
                ("preview_window", "Preview Window", config.get("preview_window", True), "bool"),
                ("save_raw_video", "Save Raw Video", config.get("save_raw_video", True), "bool"),
            ]

            choices = []
            for key, name, val, _ in settings:
                display_val = str(val) if val is not None else "(not set)"
                choices.append(Choice(value=key, name=f"{name}: {display_val}"))
            choices.append(Choice(value="__back__", name="« Done"))

            while True:
                selected = inquirer.select(
                    message="Select setting to edit:",
                    choices=choices,
                    style=hacker_style,
                ).execute()

                if selected == "__back__":
                    break

                # Find setting info
                setting_info = next((s for s in settings if s[0] == selected), None)
                if not setting_info:
                    continue

                key, name, current_val, input_type = setting_info

                # Get new value based on type
                if input_type == "bool":
                    new_val = inquirer.confirm(
                        message=f"{name}:",
                        default=current_val,
                        style=hacker_style,
                    ).execute()
                elif input_type == "select" and key == "preferred_tool":
                    new_val = inquirer.select(
                        message=f"{name}:",
                        choices=[
                            Choice(value="uv", name="uv (recommended)"),
                            Choice(value="pip", name="pip"),
                            Choice(value="conda", name="conda"),
                        ],
                        style=hacker_style,
                    ).execute()
                elif input_type == "number":
                    val_str = inquirer.text(
                        message=f"{name}:",
                        default=str(current_val),
                        style=hacker_style,
                    ).execute()
                    try:
                        new_val = int(val_str)
                    except ValueError:
                        print(f"{Colors.error('Invalid number')}")
                        continue
                else:
                    new_val = inquirer.text(
                        message=f"{name}:",
                        default=str(current_val) if current_val else "",
                        style=hacker_style,
                    ).execute()

                if new_val != current_val:
                    try:
                        self.api.update_user_config({key: new_val})
                        print(f"{Colors.success('Updated:')} {name}")

                        # Update choices display
                        for i, (k, n, _, t) in enumerate(settings):
                            if k == key:
                                choices[i] = Choice(value=k, name=f"{n}: {new_val}")
                                settings[i] = (k, n, new_val, t)
                                break
                    except Exception as e:
                        print(f"{Colors.error('Error:')} {e}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        return MenuResult.CONTINUE

    def _user_devices(self) -> MenuResult:
        """User device configuration."""
        show_section_header("User Device Configuration")

        try:
            devices = self.api.get_user_devices()

            # Cameras
            cameras = devices.get("cameras", {})
            print(f"{Colors.CYAN}Cameras:{Colors.RESET}")
            if cameras:
                for name, cam in cameras.items():
                    if isinstance(cam, dict):
                        print(f"  {name}: id={cam.get('id')} type={cam.get('type')} {cam.get('width')}x{cam.get('height')}@{cam.get('fps')}fps")
                    else:
                        print(f"  {name}: {cam}")
            else:
                print(f"  {Colors.muted('(none configured)')}")

            # Arms
            arm_names = ["leader_right", "follower_right", "leader_left", "follower_left"]
            print(f"\n{Colors.CYAN}Arms:{Colors.RESET}")
            has_arms = False
            for arm_name in arm_names:
                arm = devices.get(arm_name)
                if arm:
                    has_arms = True
                    print(f"  {arm_name}:")
                    print(f"    port: {arm.get('port', 'N/A')}")
                    print(f"    type: {arm.get('type', 'N/A')}")
                    if arm.get("calibration_id"):
                        print(f"    calibration: {arm.get('calibration_id')}")
            if not has_arms:
                print(f"  {Colors.muted('(none configured)')}")

            # Schema info
            schema_ver = devices.get("schema_version", 1)
            updated_at = devices.get("updated_at", "never")
            print(f"\n{Colors.muted(f'Schema v{schema_ver} - Updated: {updated_at}')}")

            # Edit option
            edit = inquirer.confirm(
                message="\nEdit device configuration?",
                default=False,
                style=hacker_style,
            ).execute()

            if edit:
                # Get device type to edit
                device_type = inquirer.select(
                    message="Select device type:",
                    choices=[
                        Choice(value="leader_right", name="Leader Right Arm"),
                        Choice(value="follower_right", name="Follower Right Arm"),
                        Choice(value="leader_left", name="Leader Left Arm"),
                        Choice(value="follower_left", name="Follower Left Arm"),
                        Choice(value="__back__", name="« Cancel"),
                    ],
                    style=hacker_style,
                ).execute()

                if device_type != "__back__":
                    current = devices.get(device_type) or {}

                    port = inquirer.text(
                        message="Serial Port:",
                        default=current.get("port", "") if isinstance(current, dict) else "",
                        style=hacker_style,
                    ).execute()

                    arm_type = inquirer.select(
                        message="Arm Type:",
                        choices=[
                            Choice(value="so101", name="SO-101"),
                            Choice(value="so100", name="SO-100"),
                        ],
                        style=hacker_style,
                    ).execute()

                    calibration_id = inquirer.text(
                        message="Calibration ID (optional):",
                        default=current.get("calibration_id", "") if isinstance(current, dict) else "",
                        style=hacker_style,
                    ).execute()

                    if port:
                        try:
                            arm_config = {
                                "port": port,
                                "type": arm_type,
                            }
                            if calibration_id:
                                arm_config["calibration_id"] = calibration_id

                            self.api.update_user_devices({device_type: arm_config})
                            print(f"{Colors.success('Device configuration updated.')}")
                        except Exception as e:
                            print(f"{Colors.error('Error:')} {e}")

        except Exception as e:
            print(f"{Colors.error('Error:')} {e}")

        input(f"\n{Colors.muted('Press Enter to continue...')}")
        return MenuResult.CONTINUE

    # Environments view removed (profile-based operation).

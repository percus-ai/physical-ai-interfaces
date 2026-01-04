"""Phi CLI - Hacker-style CLI for Physical AI Framework.

Usage:
    phi           # Launch interactive menu
    phi health    # Check backend health
    phi projects  # List projects
"""

import sys
from pathlib import Path
from typing import Optional

# Inject bundled-torch paths BEFORE any torch imports
# This allows Jetson's pre-built PyTorch to be used without pip install
_bundled_torch = Path.home() / ".cache" / "daihen-physical-ai" / "bundled-torch"
if (_bundled_torch / "pytorch").is_dir():
    _pytorch_path = str(_bundled_torch / "pytorch")
    _torchvision_path = str(_bundled_torch / "torchvision")
    if _pytorch_path not in sys.path:
        sys.path.insert(0, _pytorch_path)
    if _torchvision_path not in sys.path:
        sys.path.insert(0, _torchvision_path)

import typer
from rich import print as rprint

from interfaces_cli.client import PhiClient

# Typer app for direct commands
cli = typer.Typer(
    help="Physical AI CLI - Hacker-style interface for robot control",
    invoke_without_command=True,
    no_args_is_help=False,
)


@cli.callback()
def main_callback(ctx: typer.Context):
    """Launch interactive menu if no command specified."""
    if ctx.invoked_subcommand is None:
        # No subcommand - launch interactive mode
        run_interactive()


def run_interactive(backend_url: Optional[str] = None) -> None:
    """Run the interactive menu-based CLI."""
    try:
        from interfaces_cli.app import PhiApplication

        app = PhiApplication(backend_url=backend_url)
        app.run()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
    except Exception as e:
        rprint(f"[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
def health():
    """Check backend health."""
    client = PhiClient()
    try:
        result = client.health()
        rprint(f"[green]Backend status: {result['status']}[/green]")
    except Exception as e:
        rprint(f"[red]Backend unreachable: {e}[/red]")
        raise typer.Exit(1)


@cli.command()
def projects():
    """List all projects."""
    client = PhiClient()
    try:
        result = client.list_projects()
        project_list = result.get("projects", [])
        if project_list:
            rprint("[green]Projects:[/green]")
            for p in project_list:
                rprint(f"  - {p}")
        else:
            rprint("[yellow]No projects found[/yellow]")
    except Exception as e:
        rprint(f"[red]Error listing projects: {e}[/red]")
        raise typer.Exit(1)


@cli.command()
def devices():
    """List connected devices."""
    client = PhiClient()
    try:
        result = client.list_devices()
        device_list = result.get("devices", [])
        if device_list:
            rprint("[green]Devices:[/green]")
            for d in device_list:
                rprint(f"  - {d.get('id', 'unknown')}: {d.get('type', 'unknown')}")
        else:
            rprint("[yellow]No devices connected[/yellow]")
    except Exception as e:
        rprint(f"[red]Error listing devices: {e}[/red]")
        raise typer.Exit(1)


@cli.command()
def info():
    """Show system information."""
    client = PhiClient()
    try:
        result = client.get_system_info()
        rprint("[green]System Info:[/green]")
        for key, value in result.items():
            rprint(f"  {key}: {value}")
    except Exception as e:
        rprint(f"[red]Error getting system info: {e}[/red]")
        raise typer.Exit(1)


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()

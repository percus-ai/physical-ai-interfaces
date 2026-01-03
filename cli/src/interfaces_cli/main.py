"""CLI entrypoint using Typer."""

import typer
from rich import print as rprint
from interfaces_cli.client import PhiClient

app = typer.Typer(help="Physical AI CLI")


@app.command()
def health():
    """Check backend health."""
    client = PhiClient()
    result = client.health()
    rprint(f"[green]Backend status: {result['status']}[/green]")


@app.command()
def projects():
    """List all projects."""
    client = PhiClient()
    projects = client.list_projects()
    for p in projects:
        rprint(f"  - {p['name']}")


if __name__ == "__main__":
    app()

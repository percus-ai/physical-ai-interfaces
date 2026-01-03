"""CLI entrypoint using Typer."""

import typer
from rich import print as rprint
from interfaces_cli.client import PercusClient

app = typer.Typer(help="Percus Physical AI CLI")


@app.command()
def health():
    """Check backend health."""
    client = PercusClient()
    result = client.health()
    rprint(f"[green]Backend status: {result['status']}[/green]")


@app.command()
def projects():
    """List all projects."""
    client = PercusClient()
    projects = client.list_projects()
    for p in projects:
        rprint(f"  - {p['name']}")


if __name__ == "__main__":
    app()

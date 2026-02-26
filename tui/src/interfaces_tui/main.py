"""TUI entrypoint using Textual."""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static


class PhiTUI(App):
    """Physical AI TUI Application."""

    TITLE = "Physical AI"
    CSS = """
    Screen {
        background: $surface;
    }
    #welcome {
        margin: 2;
        padding: 1 2;
        background: $panel;
        border: solid green;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "toggle_dark", "Toggle dark mode"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Welcome to Physical AI TUI", id="welcome")
        yield Footer()

    def action_toggle_dark(self) -> None:
        self.dark = not self.dark


def main():
    app = PhiTUI()
    app.run()


if __name__ == "__main__":
    main()

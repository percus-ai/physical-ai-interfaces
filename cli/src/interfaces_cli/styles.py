"""Hacker-style terminal styles for InquirerPy."""

from InquirerPy.utils import get_style

# Matrix-style green theme
hacker_style = get_style(
    {
        "questionmark": "#00ff00 bold",
        "answermark": "#00ff00",
        "answer": "#00ffff bold",
        "input": "#00ff00",
        "question": "#00ff00 bold",
        "answered_question": "#00ff00",
        "instruction": "#808080",
        "long_instruction": "#808080",
        "pointer": "#00ff00 bold",
        "checkbox": "#00ff00",
        "separator": "#00ff00",
        "skipped": "#808080",
        "validator": "#ff0000",
        "marker": "#00ff00",
        "fuzzy_prompt": "#00ff00",
        "fuzzy_info": "#808080",
        "fuzzy_border": "#00ff00",
        "fuzzy_match": "#00ffff bold",
    },
    style_override=False,
)


class Colors:
    """ANSI color codes."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Matrix theme colors
    GREEN = "\033[92m"
    BRIGHT_GREEN = "\033[32m"
    CYAN = "\033[96m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GRAY = "\033[90m"
    WHITE = "\033[97m"

    # Semantic colors
    SUCCESS = GREEN
    ERROR = RED
    WARNING = YELLOW
    INFO = CYAN
    MUTED = GRAY

    @classmethod
    def success(cls, text: str) -> str:
        return f"{cls.SUCCESS}{text}{cls.RESET}"

    @classmethod
    def error(cls, text: str) -> str:
        return f"{cls.ERROR}{text}{cls.RESET}"

    @classmethod
    def warning(cls, text: str) -> str:
        return f"{cls.WARNING}{text}{cls.RESET}"

    @classmethod
    def info(cls, text: str) -> str:
        return f"{cls.INFO}{text}{cls.RESET}"

    @classmethod
    def muted(cls, text: str) -> str:
        return f"{cls.MUTED}{text}{cls.RESET}"

    @classmethod
    def bold(cls, text: str) -> str:
        return f"{cls.BOLD}{text}{cls.RESET}"

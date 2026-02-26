"""Session-based file logging with 24-hour rotation."""

import logging
import re
import uuid
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional


def _find_repo_root() -> Path:
    """Find repository root by looking for data directory."""
    current = Path.cwd()
    for _ in range(10):
        if (current / "data").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return Path.cwd()


def get_logs_dir() -> Path:
    """Get the logs directory path."""
    repo_root = _find_repo_root()
    logs_dir = repo_root / "data" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def generate_session_id() -> str:
    """Generate a short unique session identifier."""
    return uuid.uuid4().hex[:6]


def get_next_index(logs_dir: Path, app_name: str) -> int:
    """Get the next available index by scanning existing log files."""
    pattern = re.compile(rf"^{app_name}_(\d+)_[a-f0-9]+_\d{{4}}-\d{{2}}-\d{{2}}\.log$")
    max_index = -1
    for f in logs_dir.glob(f"{app_name}_*.log"):
        match = pattern.match(f.name)
        if match:
            idx = int(match.group(1))
            max_index = max(max_index, idx)
    return max_index + 1


class SessionFileHandler(TimedRotatingFileHandler):
    """File handler with session-based naming and 24h rotation."""

    def __init__(self, app_name: str, session_id: Optional[str] = None):
        self.app_name = app_name
        self.session_id = session_id or generate_session_id()

        logs_dir = get_logs_dir()
        # Get next index from existing files (never resets)
        self.rotation_index = get_next_index(logs_dir, app_name)

        date_str = datetime.now().strftime("%Y-%m-%d")
        # Format: {app}_{index}_{session_id}_{date}.log
        filename = f"{app_name}_{self.rotation_index}_{self.session_id}_{date_str}.log"

        super().__init__(
            filename=str(logs_dir / filename),
            when="midnight",
            interval=1,
            backupCount=0,  # We handle rotation ourselves
        )
        self.setLevel(logging.DEBUG)
        self.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

    def doRollover(self):
        """Override to use custom naming for rotated files."""
        if self.stream:
            self.stream.close()
            self.stream = None

        self.rotation_index += 1
        date_str = datetime.now().strftime("%Y-%m-%d")
        logs_dir = get_logs_dir()
        new_filename = (
            f"{self.app_name}_{self.rotation_index}_{self.session_id}_{date_str}.log"
        )
        self.baseFilename = str(logs_dir / new_filename)

        if not self.delay:
            self.stream = self._open()

        # Update rollover time
        self.rolloverAt = self.computeRollover(int(datetime.now().timestamp()))


def setup_file_logging(
    app_name: str,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
) -> str:
    """Configure logging with console and file handlers.

    Args:
        app_name: Application name (e.g., 'cli', 'backend')
        console_level: Log level for console output
        file_level: Log level for file output

    Returns:
        The session ID used for the log file
    """
    root = logging.getLogger()
    root.setLevel(min(console_level, file_level))

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root.addHandler(console)

    # File handler
    file_handler = SessionFileHandler(app_name)
    file_handler.setLevel(file_level)
    root.addHandler(file_handler)

    logger = logging.getLogger(f"interfaces_{app_name}")
    logger.info(f"Log session started: {file_handler.session_id}")
    logger.info(f"Log file: {file_handler.baseFilename}")

    return file_handler.session_id

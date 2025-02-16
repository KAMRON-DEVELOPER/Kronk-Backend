import sys
from pathlib import Path

from loguru import logger as my_logger


def custom_log_sink(message):
    """Custom Loguru Sink - Extracts Stack Trace and Formats Logs."""
    # ANSI color codes for console
    RESET = "\033[0m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Log level mapping with colors and emojis
    LOG_LEVELS = {
        "TRACE": {"emoji": "🔍", "color": CYAN},
        "DEBUG": {"emoji": "🐛", "color": BLUE},
        "INFO": {"emoji": "💡", "color": GREEN},
        "WARNING": {"emoji": "🚨", "color": YELLOW},
        "ERROR": {"emoji": "🌋", "color": RED},
        "CRITICAL": {"emoji": "👾", "color": MAGENTA},
    }

    record = message.record
    message = record.get("message")
    full_path = Path(__file__).parent.parent.parent
    relative_path = Path(record.get("file").path).relative_to(full_path)

    # Extract log level information
    level = record["level"].name
    color = LOG_LEVELS.get(level, {}).get("color", WHITE)
    emoji = LOG_LEVELS.get(level, {}).get("emoji", "📌")

    # Print to standard output
    sys.stdout.write(f"{color}({relative_path})    {emoji} {message}{RESET}\n")


my_logger.remove()
my_logger.add(custom_log_sink, level="TRACE")

"""
utils.py
========
Shared utilities — load .env from a predictable location regardless
of which directory the user runs the project from.

All modules should import load_env() from here and call it once.
"""

import os
from pathlib import Path
from dotenv import load_dotenv


def load_env() -> Path:
    """
    Find and load the .env file.

    Search order:
      1. ai_outreach_agent/.env  (where .env.example lives)
      2. project root (.env next to main.py)
      3. python-dotenv default (current working directory)

    Returns the Path of the .env file that was loaded.
    """
    # Directory that THIS file (utils.py) lives in → ai_outreach_agent/
    pkg_dir = Path(__file__).parent
    root_dir = pkg_dir.parent

    candidates = [
        pkg_dir / ".env",
        root_dir / ".env",
    ]

    for candidate in candidates:
        if candidate.exists():
            load_dotenv(dotenv_path=candidate, override=False)
            return candidate

    # Fallback: let python-dotenv search upward from CWD
    load_dotenv()
    return Path(".env")

"""Validate the production env as data; runnable with Ubuntu's system Python.

Keep this dependency-free so preparation, bootstrap, deploy and recovery use the
same rules before a new application environment has been installed.
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

_REQUIRED = {
    "SHOPPING_ENV": "production",
    "SHOPPING_DATA_DIR": "/var/lib/shopping-app",
    "SHOPPING_HOST": "127.0.0.1",
    "SHOPPING_PORT": "8000",
    "SHOPPING_ALLOW_NON_LOOPBACK": "false",
}
_OPTIONAL = {
    "SHOPPING_OLLAMA_URL",
    "SHOPPING_OLLAMA_MODEL",
    "SHOPPING_APP_ORIGIN",
    "PYTHONDONTWRITEBYTECODE",
}


def validate_config(path: Path) -> None:
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in values or key not in _REQUIRED.keys() | _OPTIONAL:
            raise ValueError("Invalid production configuration")
        values[key] = value
    if any(values.get(key) != value for key, value in _REQUIRED.items()):
        raise ValueError("Invalid production configuration")
    if values.get("PYTHONDONTWRITEBYTECODE", "1") != "1":
        raise ValueError("Invalid production configuration")
    if values.get("SHOPPING_OLLAMA_URL", "http://127.0.0.1:11434") != "http://127.0.0.1:11434":
        raise ValueError("Invalid local model endpoint")
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", values.get("SHOPPING_OLLAMA_MODEL", "qwen3.5:9b")
    ):
        raise ValueError("Invalid model name")
    if "SHOPPING_APP_ORIGIN" in values:
        origin = values["SHOPPING_APP_ORIGIN"]
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?", origin)
            or not 1 <= (parsed.port or 443) <= 65535
        ):
            raise ValueError("Invalid application origin")


if __name__ == "__main__":
    try:
        validate_config(Path(sys.argv[1]))
    except (ValueError, OSError, IndexError):
        print("Unsupported production configuration", file=sys.stderr)
        sys.exit(1)

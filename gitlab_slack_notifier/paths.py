"""Where config, secrets and state live, and loading of the secrets file."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

APP = "gitlab-slack-notifier"
CONFIG_FILE = "config.toml"
STATE_FILE = "state.json"
SECRETS_FILE = "secrets.env"
LEGACY_SECRETS_FILE = ".env"


def default_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP


def resolve_home(explicit: Path | None = None, cwd: Path | None = None) -> Path:
    """Directory holding config.toml, secrets.env and state.json.

    Order: --home, $NOTIFIER_HOME, the current directory if it has a config.toml (running from a
    clone of the repo), then ~/.config/gitlab-slack-notifier.
    """
    if explicit:
        return explicit.expanduser().resolve()
    if env := os.environ.get("NOTIFIER_HOME"):
        return Path(env).expanduser().resolve()
    cwd = cwd or Path.cwd()
    if (cwd / CONFIG_FILE).is_file():
        return cwd.resolve()
    return default_home()


def parse_env(text: str) -> dict[str, str]:
    """Parse `KEY=value` / `export KEY=value` lines; quotes and trailing `# comments` are handled."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key.isidentifier():
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            try:
                parts = shlex.split(value, comments=True)
                value = parts[0] if parts else ""
            except ValueError:  # unbalanced quote: keep the raw value
                pass
        else:  # `#` starts a comment only after whitespace (tokens / URLs may contain one)
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        out[key] = value
    return out


def load_secrets(home: Path) -> list[Path]:
    """Load secrets files from `home` into os.environ (variables already set win). Returns loaded files."""
    loaded = []
    for name in (SECRETS_FILE, LEGACY_SECRETS_FILE):
        path = home / name
        if path.is_file():
            for key, value in parse_env(path.read_text()).items():
                os.environ.setdefault(key, value)
            loaded.append(path)
    return loaded


def write_secrets(path: Path, values: dict[str, str]) -> None:
    """Write a secrets file readable by the user only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{k}={shlex.quote(v)}\n" for k, v in values.items() if v)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(body)
    os.chmod(path, 0o600)

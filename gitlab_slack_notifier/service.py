"""Install the notifier as a background service: systemd user unit (Linux / WSL) or launchd agent (macOS)."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from xml.sax.saxutils import escape

from .paths import APP

LAUNCHD_LABEL = "com.github.lucarammel.gitlab-slack-notifier"
SYSTEMD_UNIT = f"{APP}.service"


def command(home: Path, interval: int) -> list[str]:
    return [sys.executable, "-u", "-m", "gitlab_slack_notifier", "--home", str(home), "--loop", str(interval)]


def source_dir() -> Path | None:
    """Repo directory when running from a clone (package not installed), so the service can import it."""
    pkg_parent = Path(__file__).resolve().parent.parent
    installed = {Path(sysconfig.get_paths()[k]).resolve() for k in ("purelib", "platlib")}
    return None if pkg_parent in installed else pkg_parent


def systemd_unit(home: Path, interval: int) -> str:
    env = f"Environment=PYTHONPATH={src}\n" if (src := source_dir()) else ""
    return f"""[Unit]
Description=GitLab / YouTrack -> Slack notifier
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory={home}
{env}ExecStart={shlex.join(command(home, interval))}
Restart=on-failure
RestartSec=30

[Install]
WantedBy=default.target
"""


def launchd_plist(home: Path, interval: int) -> str:
    args = "".join(f"\n    <string>{escape(a)}</string>" for a in command(home, interval))
    env = ""
    if src := source_dir():
        env = (
            "\n  <key>EnvironmentVariables</key>\n  <dict>\n"
            f"    <key>PYTHONPATH</key><string>{escape(str(src))}</string>\n  </dict>"
        )
    log = escape(str(home / "notifier.log"))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>{args}
  </array>
  <key>WorkingDirectory</key><string>{escape(str(home))}</string>{env}
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


def _run(*cmd: str, check: bool = True) -> bool:
    print("$", shlex.join(cmd))
    return subprocess.run(cmd, check=check).returncode == 0


def _systemd_available() -> bool:
    return bool(shutil.which("systemctl")) and Path("/run/systemd/system").is_dir()


def _systemd_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "systemd" / "user" / SYSTEMD_UNIT


def _launchd_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def install(home: Path, interval: int = 120) -> None:
    if sys.platform == "darwin":
        path = _launchd_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        domain = f"gui/{os.getuid()}"
        _run("launchctl", "bootout", f"{domain}/{LAUNCHD_LABEL}", check=False)
        path.write_text(launchd_plist(home, interval))
        _run("launchctl", "bootstrap", domain, str(path))
        print(f"\nInstalled {path}\nLogs: tail -f {home / 'notifier.log'}")
        return
    if sys.platform.startswith("linux"):
        if not _systemd_available():
            sys.exit(
                "systemd is not running. On WSL, add to /etc/wsl.conf:\n  [boot]\n  systemd=true\n"
                "then run `wsl --shutdown` from Windows and retry.\n"
                f"Or run it in a terminal: {shlex.join(command(home, interval))}"
            )
        path = _systemd_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(systemd_unit(home, interval))
        _run("systemctl", "--user", "daemon-reload")
        _run("systemctl", "--user", "enable", SYSTEMD_UNIT)
        _run("systemctl", "--user", "restart", SYSTEMD_UNIT)
        if not _run("loginctl", "enable-linger", os.environ.get("USER", ""), check=False):
            print("(could not enable linger: the service will only run while you are logged in)")
        print(f"\nInstalled {path}\nLogs: journalctl --user -u {APP} -f")
        return
    sys.exit(
        f"No service support for {sys.platform}: run it from WSL, or keep a terminal open with\n"
        f"  {shlex.join(command(home, interval))}"
    )


def uninstall() -> None:
    if sys.platform == "darwin":
        path = _launchd_path()
        _run("launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}", check=False)
    else:
        path = _systemd_path()
        _run("systemctl", "--user", "disable", "--now", SYSTEMD_UNIT, check=False)
    if path.exists():
        path.unlink()
        if sys.platform != "darwin":
            _run("systemctl", "--user", "daemon-reload", check=False)
    print(f"Removed {path}")

"""Running the server as a background service (`the_frame_v2 service install`, phase 11 §14.4).

The unit files are generated rather than shipped, because the two things they must get right are
known only on the machine: the **absolute path of this interpreter's console script** (a `uv`
virtualenv, a pipx shim, a system install — there is no stable name) and the data directory the
user actually chose. Both are written into the file, so the service does not depend on a PATH or
on a shell profile.

Nothing here starts or stops anything: the file is written, and the two commands that enable it
are printed. A tool that silently ran `systemctl` for the user would be a tool they cannot audit.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

SERVICE_NAME = "the_frame_v2"


class ServiceError(Exception):
    """Something about this machine makes an installable unit impossible."""


@dataclass(frozen=True, slots=True)
class Plan:
    """What `service install` would write, and what the user has to run afterwards."""

    kind: str
    path: Path
    content: str
    enable: tuple[str, ...]
    disable: tuple[str, ...]


def executable() -> str:
    """The absolute path of the `the_frame_v2` console script for *this* interpreter."""
    script = Path(sys.argv[0])
    if script.name.startswith("the_frame_v2") and script.exists():
        return str(script.resolve())
    candidate = Path(sys.executable).parent / "the_frame_v2"
    if candidate.exists():
        return str(candidate.resolve())
    found = shutil.which("the_frame_v2")
    if found:
        return str(Path(found).resolve())
    # Last resort: the module entry point, which works for any interpreter that can import it.
    return f"{sys.executable} -m the_frame_v2"


def systemd_unit(exe: str, data_dir: Path, environment: dict[str, str]) -> str:
    env = "\n".join(f'Environment="{key}={value}"' for key, value in sorted(environment.items()))
    return f"""[Unit]
Description=the_frame_v2 — prepare pictures for an art-mode TV
Documentation=https://github.com/Nenuphar12/the_frame_v2
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exe} serve
Environment="THE_FRAME_V2_DATA_DIR={data_dir}"
{env}
Restart=on-failure
RestartSec=5
# The library is the only thing this service needs to write.
ReadWritePaths={data_dir}
PrivateTmp=yes
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only

[Install]
WantedBy=default.target
"""


def launchd_plist(exe: str, data_dir: Path, environment: dict[str, str], logs: Path) -> str:
    args = "".join(f"\n    <string>{part}</string>" for part in [*exe.split(" "), "serve"])
    env = {"THE_FRAME_V2_DATA_DIR": str(data_dir), **environment}
    entries = "".join(
        f"\n    <key>{key}</key>\n    <string>{value}</string>"
        for key, value in sorted(env.items())
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{SERVICE_NAME}</string>
  <key>ProgramArguments</key>
  <array>{args}
  </array>
  <key>EnvironmentVariables</key>
  <dict>{entries}
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{logs / "the_frame_v2.log"}</string>
  <key>StandardErrorPath</key>
  <string>{logs / "the_frame_v2.err.log"}</string>
</dict>
</plist>
"""


def plan(data_dir: Path, *, public_url: str | None = None, system: str | None = None) -> Plan:
    """What installing a service on this machine means. Raises `ServiceError` on Windows."""
    system = system or platform.system()
    exe = executable()
    environment = {"THE_FRAME_V2_PUBLIC_URL": public_url} if public_url else {}

    if system == "Linux":
        home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        path = home / "systemd" / "user" / f"{SERVICE_NAME}.service"
        return Plan(
            kind="systemd (user)",
            path=path,
            content=systemd_unit(exe, data_dir, environment),
            enable=(
                "systemctl --user daemon-reload",
                f"systemctl --user enable --now {SERVICE_NAME}.service",
                # Without lingering the service stops when the last session closes — which for a
                # machine whose whole job is serving a library is never what is wanted.
                f"sudo loginctl enable-linger {os.environ.get('USER', '$USER')}",
            ),
            disable=(
                f"systemctl --user disable --now {SERVICE_NAME}.service",
                "systemctl --user daemon-reload",
            ),
        )

    if system == "Darwin":
        logs = Path.home() / "Library" / "Logs"
        path = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_NAME}.plist"
        return Plan(
            kind="launchd (user agent)",
            path=path,
            content=launchd_plist(exe, data_dir, environment, logs),
            enable=(f"launchctl load -w {path}",),
            disable=(f"launchctl unload -w {path}",),
        )

    raise ServiceError(
        f"No service template for {system}. On Windows, run the server with Task Scheduler "
        "or NSSM — see docs/user-guide.md."
    )

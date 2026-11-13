"""`kinenix-worker service install` and `uninstall`: the systemd service for any install, including pip (#153).

The unit is the one scripts/install_service.sh wrote for clones of the repository, with two differences:
ExecStart is the kinenix-worker next to the Python running this command, so it works for any venv, and the
working folder is the flows folder unless --working-dir names another. Running install again rewrites the
unit, so it follows an upgrade or a moved venv. worker.env and triggers.json are created when missing and never
overwritten. sudo is used only to write the unit and to run systemctl.
"""
import getpass
import os
import shutil
import subprocess  # nosec B404: runs sudo, tee, and systemctl with fixed arguments, never a shell
import sys
from pathlib import Path
from typing import Callable, List, Optional

SERVICE_NAME = "kinenix-worker"
UNIT_PATH = f"/etc/systemd/system/{SERVICE_NAME}.service"
DROP_IN_DIR = Path(f"/etc/systemd/system/{SERVICE_NAME}.service.d")

ENV_TEMPLATE = """# Kinenix Worker settings, loaded by the kinenix-worker service and by your shell.
# Connect to the Hub with `kinenix connect http://<hub-ip>:8080` (saved in ~/.kinenix/kinenix.env),
# or fill in the URL and key here; values here take precedence. Then: sudo systemctl restart kinenix-worker
export KINENIX_HUB_URL=
export KINENIX_HUB_API_KEY=
export KINENIX_WORKER_ID=$(hostname)
"""
TRIGGERS_TEMPLATE = '{\n  "triggers": []\n}\n'


class ServiceError(Exception):
    """The service cannot be installed here; the message says why and what to do instead."""


def no_systemd_message(platform: str) -> str:
    if platform.startswith("win"):
        instead = ("On Windows, start the worker at logon with Task Scheduler, for example:\n"
                   '  schtasks /Create /SC ONLOGON /TN "Kinenix Worker" '
                   '/TR "\\"<path to kinenix-worker.exe>\\" daemon --config %USERPROFILE%\\.kinenix\\triggers.json"')
    elif platform == "darwin":
        instead = ("On macOS, use a launchd agent in ~/Library/LaunchAgents that runs "
                   "`kinenix-worker daemon --config ~/.kinenix/triggers.json`.")
    else:
        instead = "Start `kinenix-worker daemon --config ~/.kinenix/triggers.json` with this system's service manager."
    return f"kinenix-worker service needs systemd (systemctl), which this system does not have.\n{instead}"


def worker_program() -> Path:
    """The kinenix-worker of the Python running this command: the venv's bin folder, or the one on PATH."""
    folder = Path(sys.executable).parent
    for name in ("kinenix-worker", "kinenix-worker.exe"):
        if (folder / name).is_file():
            return (folder / name).absolute()
    found = shutil.which("kinenix-worker")
    if found:
        return Path(found).absolute()
    raise ServiceError(f"kinenix-worker was not found next to {sys.executable} or on PATH. "
                       f"Install it in this environment: pip install \"kinenix[worker]\"")


def unit_text(user: str, program: Path, working_dir: Path, env_file: Path, triggers_file: Path) -> str:
    program, working_dir, env_file, triggers_file = (Path(p).as_posix() for p in (program, working_dir, env_file,
                                                                                   triggers_file))
    # worker.env is sourced by bash so it can keep the `export` lines that a login shell also uses
    return f"""[Unit]
Description=Kinenix Worker (unattended RPA daemon)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory={working_dir}
Environment=PYTHONUNBUFFERED=1
ExecStart=/bin/bash -c 'if [ -f "{env_file}" ]; then . "{env_file}"; fi; exec "{program}" daemon --config "{triggers_file}"'
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""


def drop_in_warning() -> Optional[str]:
    """Drop-in files override the unit this command writes, for example a hand-written ExecStart pointing at an
    older install; they are named, never removed."""
    try:
        found = sorted(DROP_IN_DIR.glob("*.conf"))
    except OSError:
        return None
    if not found:
        return None
    names = " ".join(str(p) for p in found)
    return (f"Warning: {len(found)} drop-in file(s) override this unit: {names}. If they set ExecStart or "
            f"WorkingDirectory, the service keeps using their values. Remove them unless you still need them: "
            f"sudo rm {names} && sudo systemctl daemon-reload && sudo systemctl restart {SERVICE_NAME}")


def _check_system(platform: str) -> None:
    if not platform.startswith("linux") or not shutil.which("systemctl"):
        raise ServiceError(no_systemd_message(platform))
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise ServiceError("Run kinenix-worker service as the user the worker should run as, not as root; "
                           "it uses sudo where needed.")


def _user_files(config_dir: Path, say: Callable[[str], None]) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    env_file, triggers_file = config_dir / "worker.env", config_dir / "triggers.json"
    if not env_file.exists():
        env_file.write_text(ENV_TEMPLATE, encoding="utf-8")
        say(f"Created {env_file} (edit it, or run `kinenix connect`, to connect to the Hub).")
    os.chmod(env_file, 0o600)
    if not triggers_file.exists():
        triggers_file.write_text(TRIGGERS_TEMPLATE, encoding="utf-8")
        say(f"Created {triggers_file} (no triggers yet: the worker only sends heartbeats).")


def _run(command: List[str], stdin: Optional[str] = None) -> None:
    subprocess.run(command, input=stdin, text=True, check=True,  # nosec B603: fixed command, no shell
                   stdout=subprocess.DEVNULL if stdin is not None else None)


def install(working_dir: Optional[Path] = None, dry_run: bool = False, say: Callable[[str], None] = print,
            run: Callable[..., None] = _run, platform: str = sys.platform) -> str:
    """Write the unit (or only return it with dry_run), enable it, and restart the service."""
    from kinenix.workspace import flows_dir

    config_dir = Path.home() / ".kinenix"
    folder = Path(working_dir).expanduser().absolute() if working_dir else flows_dir()
    user = getpass.getuser()
    try:
        program = worker_program()
    except ServiceError:
        if not dry_run:
            raise
        program = Path(sys.executable).parent / "kinenix-worker"
    text = unit_text(user, program, folder, config_dir / "worker.env", config_dir / "triggers.json")
    if dry_run:
        return text
    _check_system(platform)
    folder.mkdir(parents=True, exist_ok=True)
    _user_files(config_dir, say)
    run(["sudo", "tee", UNIT_PATH], stdin=text)
    run(["sudo", "systemctl", "daemon-reload"])
    run(["sudo", "systemctl", "enable", SERVICE_NAME])
    run(["sudo", "systemctl", "restart", SERVICE_NAME])
    say("")
    say(f"Service '{SERVICE_NAME}' installed and started (runs as {user}, starts at boot).")
    say(f"  Program:  {program}")
    say(f"  Folder:   {folder}")
    say(f"  Status:   systemctl status {SERVICE_NAME}")
    say(f"  Logs:     journalctl -u {SERVICE_NAME} -f")
    say(f"  Restart:  sudo systemctl restart {SERVICE_NAME}   (after editing worker.env or triggers.json)")
    say(f"  Update:   kinenix-worker service install   (again, after an upgrade or after moving the venv)")
    say(f"  Remove:   kinenix-worker service uninstall")
    warning = drop_in_warning()
    if warning:
        say("")
        say(warning)
    return text


def uninstall(say: Callable[[str], None] = print, run: Callable[..., None] = _run,
              platform: str = sys.platform) -> None:
    """Stop and remove the service; the files in ~/.kinenix stay."""
    _check_system(platform)
    try:
        run(["sudo", "systemctl", "disable", "--now", SERVICE_NAME])
    except subprocess.CalledProcessError:
        pass  # not installed or already stopped
    run(["sudo", "rm", "-f", UNIT_PATH])
    run(["sudo", "systemctl", "daemon-reload"])
    say(f"Service '{SERVICE_NAME}' removed. Files in ~/.kinenix were kept.")

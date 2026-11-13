"""#153: kinenix-worker service install / uninstall, for workers installed with pip as well as clones."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kinenix_worker import service


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("KINENIX_FLOWS_DIR", str(tmp_path / "flows"))
    monkeypatch.setattr(service.getpass, "getuser", lambda: "pi")
    monkeypatch.setattr(service, "worker_program", lambda: Path("/home/pi/venv/bin/kinenix-worker"))
    monkeypatch.setattr(service, "_check_system", lambda platform: None)
    return tmp_path


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, command, stdin=None):
        self.calls.append((command, stdin))


def test_unit_runs_the_worker_of_this_environment_in_the_flows_folder(home):
    text = service.install(dry_run=True)
    assert "User=pi\n" in text
    assert f"WorkingDirectory={(home / 'flows').as_posix()}\n" in text
    assert '"/home/pi/venv/bin/kinenix-worker" daemon --config ' in text
    assert f'. "{(home / ".kinenix" / "worker.env").as_posix()}"' in text
    assert (home / ".kinenix" / "triggers.json").as_posix() in text
    assert "Restart=always" in text and "WantedBy=multi-user.target" in text
    assert not (home / ".kinenix").exists()  # a dry run touches nothing


def test_working_dir_can_be_another_folder(home):
    assert f"WorkingDirectory={(home / 'repo').as_posix()}\n" in service.install(home / "repo", dry_run=True)


def test_install_writes_the_unit_with_sudo_and_restarts(home):
    run, said = Recorder(), []
    text = service.install(run=run, say=said.append)
    assert run.calls == [
        (["sudo", "tee", "/etc/systemd/system/kinenix-worker.service"], text),
        (["sudo", "systemctl", "daemon-reload"], None),
        (["sudo", "systemctl", "enable", "kinenix-worker"], None),
        (["sudo", "systemctl", "restart", "kinenix-worker"], None),
    ]
    assert (home / "flows").is_dir()
    assert "export KINENIX_HUB_URL=" in (home / ".kinenix" / "worker.env").read_text(encoding="utf-8")
    assert '"triggers": []' in (home / ".kinenix" / "triggers.json").read_text(encoding="utf-8")
    shown = "\n".join(said)
    assert "journalctl -u kinenix-worker -f" in shown and "kinenix-worker service uninstall" in shown


def test_install_again_keeps_the_users_files(home):
    config = home / ".kinenix"
    config.mkdir()
    (config / "worker.env").write_text("export KINENIX_HUB_URL=http://hub:8080\n", encoding="utf-8")
    (config / "triggers.json").write_text('{"triggers": [{"type": "schedule"}]}', encoding="utf-8")
    said = []
    service.install(run=Recorder(), say=said.append)
    assert (config / "worker.env").read_text(encoding="utf-8") == "export KINENIX_HUB_URL=http://hub:8080\n"
    assert "schedule" in (config / "triggers.json").read_text(encoding="utf-8")
    assert not any(line.startswith("Created") for line in said)


def test_uninstall_stops_and_removes_the_unit_even_when_not_installed(home):
    calls = []

    def run(command, stdin=None):
        calls.append(command)
        if "disable" in command:
            raise subprocess.CalledProcessError(1, command)

    said = []
    service.uninstall(run=run, say=said.append)
    assert calls == [["sudo", "systemctl", "disable", "--now", "kinenix-worker"],
                     ["sudo", "rm", "-f", "/etc/systemd/system/kinenix-worker.service"],
                     ["sudo", "systemctl", "daemon-reload"]]
    assert "Files in ~/.kinenix were kept" in said[0]


@pytest.mark.parametrize("platform, instead", [("win32", "schtasks /Create"), ("darwin", "launchd"),
                                               ("freebsd14", "service manager")])
def test_systems_without_systemd_are_told_what_to_use(platform, instead):
    with pytest.raises(service.ServiceError) as raised:
        service._check_system(platform)
    assert "needs systemd" in str(raised.value) and instead in str(raised.value)


def test_root_is_refused(monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda name: "/usr/bin/systemctl")
    monkeypatch.setattr(service.os, "geteuid", lambda: 0, raising=False)
    with pytest.raises(service.ServiceError, match="not as root"):
        service._check_system("linux")


def test_the_program_is_found_next_to_python(tmp_path, monkeypatch):
    (tmp_path / "kinenix-worker").write_text("", encoding="utf-8")
    monkeypatch.setattr(service.sys, "executable", str(tmp_path / "python"))
    assert service.worker_program() == (tmp_path / "kinenix-worker").absolute()


def test_cli_dry_run_prints_the_unit(tmp_path):
    env = {**os.environ, "KINENIX_FLOWS_DIR": str(tmp_path / "flows"), "KINENIX_SETTINGS_FILE": str(tmp_path / "k.env")}
    result = subprocess.run([sys.executable, "-m", "kinenix_worker.cli", "service", "install", "--dry-run"],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("[Unit]") and f"WorkingDirectory={(tmp_path / 'flows').as_posix()}" in result.stdout


def test_drop_ins_that_override_the_unit_are_named_not_removed(home, monkeypatch):
    drop_ins = home / "kinenix-worker.service.d"
    monkeypatch.setattr(service, "DROP_IN_DIR", drop_ins)
    assert service.drop_in_warning() is None
    drop_ins.mkdir()
    (drop_ins / "pypi.conf").write_text("[Service]\nExecStart=\n", encoding="utf-8")
    said = []
    service.install(run=Recorder(), say=said.append)
    warning = said[-1]
    assert warning.startswith("Warning: 1 drop-in file(s) override this unit") and "pypi.conf" in warning
    assert "sudo rm" in warning and (drop_ins / "pypi.conf").exists()

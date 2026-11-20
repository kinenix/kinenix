"""kinenix install and rollback, and the run lock they wait for (#235, part 2)."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from kinenix import exit_codes
from kinenix.cli import report_validation, resolve_flow_path
from kinenix.engine import run_lock
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import load_flow
from kinenix.packaging import commands, install, signing, trust

needs_ssh_keygen = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="needs OpenSSH ssh-keygen")

FLOW = """# Install Demo
> Version: {version}

## Steps

### 1. Greet (`logic.set_variable`)
- **name:** greeting
- **value:** ${{config.greeting}}
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A Kinenix home and flows folder of their own, a publisher key, and a source flow 'install_demo'."""
    monkeypatch.setenv("KINENIX_SETTINGS_FILE", str(tmp_path / "home" / "kinenix.env"))
    monkeypatch.setenv("KINENIX_FLOWS_DIR", str(tmp_path / "flows"))
    source = tmp_path / "source" / "install_demo"
    (source / "config").mkdir(parents=True)
    (source / "config" / "config.json").write_text('{"greeting": "Hello"}', encoding="utf-8")
    return tmp_path


def build(env_dir: Path, version: str) -> Path:
    """Packs the source flow at this version into env_dir/dist (a key is made the first time)."""
    if signing.read_public_key() is None:
        key = signing.create_key("office-pc", passphrase_prompt=False)
        trust.add(key.line, "office-pc", replace=True)
    source = env_dir / "source" / "install_demo"
    (source / "flow.md").write_text(FLOW.format(version=version), encoding="utf-8")
    assert commands.pack(str(source), None, str(env_dir / "dist"), resolve_flow_path, report_validation) == 0
    return env_dir / "dist" / f"install_demo-{version}.kinx"


def target(env_dir: Path) -> Path:
    return env_dir / "flows" / "install_demo"


def do_install(package: Path, replace=False, wait=0.0) -> int:
    return commands.install(str(package), replace, wait)


def rewrite(package: Path, out: Path, change) -> Path:
    """A copy of the package with change(entries: dict) applied to its entries."""
    with zipfile.ZipFile(package) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    change(entries)
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return out


# Run lock (no ssh-keygen needed)

def test_run_lock_marks_a_running_flow_and_ends_with_it(tmp_path, monkeypatch):
    monkeypatch.setenv("KINENIX_SETTINGS_FILE", str(tmp_path / "home" / "kinenix.env"))
    folder = tmp_path / "flows" / "demo"
    folder.mkdir(parents=True)
    assert run_lock.running_pids(folder) == []
    with run_lock.hold(folder):
        assert run_lock.running_pids(folder) == [os.getpid()]
        with run_lock.hold(folder):  # a second run of the same flow has its own mark
            assert run_lock.running_pids(folder) == [os.getpid(), os.getpid()]
        assert run_lock.running_pids(folder) == [os.getpid()]
    assert run_lock.running_pids(folder) == []


def test_lock_of_an_ended_process_does_not_count(tmp_path, monkeypatch):
    monkeypatch.setenv("KINENIX_SETTINGS_FILE", str(tmp_path / "home" / "kinenix.env"))
    folder = tmp_path / "flows" / "demo"
    done = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    dead_pid = int(done.stdout)
    lock_dir = run_lock.running_dir() / run_lock.flow_key(folder)
    lock_dir.mkdir(parents=True)
    (lock_dir / "stale.json").write_text(json.dumps({"pid": dead_pid}), encoding="utf-8")
    assert not run_lock.pid_alive(dead_pid)
    assert run_lock.running_pids(folder) == []
    assert not (lock_dir / "stale.json").exists()


def test_interpreter_holds_the_lock_during_a_top_level_run(tmp_path, monkeypatch):
    monkeypatch.setenv("KINENIX_SETTINGS_FILE", str(tmp_path / "home" / "kinenix.env"))
    folder = tmp_path / "flows" / "demo"
    folder.mkdir(parents=True)
    (folder / "flow.md").write_text("# Lock\n\n## Steps\n\n### 1. Wait (`logic.delay`)\n- **seconds:** 1\n",
                                    encoding="utf-8")
    seen = []
    interpreter = FlowInterpreter(logger=ExecutionLogger(log_dir=tmp_path / "logs"))
    runner = threading.Thread(target=interpreter.run_flow,
                              args=(load_flow(folder / "flow.md"), {"__flow_dir__": str(folder)}))
    runner.start()
    for _ in range(50):
        seen = run_lock.running_pids(folder)
        if seen:
            break
        time.sleep(0.05)
    runner.join()
    assert seen == [os.getpid()]
    assert run_lock.running_pids(folder) == []


def test_unknown_file_and_missing_trust(env, capsys):
    assert do_install(env / "nothing.kinx") == exit_codes.NOT_FOUND
    not_zip = env / "bad.kinx"
    not_zip.write_text("not a zip", encoding="utf-8")
    assert do_install(not_zip) == exit_codes.INVALID_FLOW
    assert "PACKAGE_DAMAGED" in capsys.readouterr().err


# Install (needs ssh-keygen)

@needs_ssh_keygen
def test_install_new_then_upgrade_keeps_the_machine_settings(env, capsys):
    first = build(env, "1.0.0")
    assert do_install(first) == exit_codes.OK
    installed = target(env)
    record = json.loads((installed / ".kinenix-deployed.json").read_text(encoding="utf-8"))
    assert (record["name"], record["version"], record["publisher"]["name"]) == ("install_demo", "1.0.0", "office-pc")
    assert sorted(p.name for p in installed.iterdir()) == [".kinenix-deployed.json", "config", "flow.md"]

    # This machine's own files
    (installed / ".env").write_text("TOKEN=local", encoding="utf-8")
    (installed / "config" / "local.json").write_text('{"greeting": "Sawasdee"}', encoding="utf-8")
    (installed / "output").mkdir()
    (installed / "output" / "result.csv").write_text("a,b", encoding="utf-8")

    second = build(env, "1.0.1")
    assert do_install(second) == exit_codes.OK
    out = capsys.readouterr().out
    assert "Installed install_demo 1.0.1 (was 1.0.0)" in out
    assert "> Version: 1.0.1" in (installed / "flow.md").read_text(encoding="utf-8")
    assert (installed / ".env").read_text(encoding="utf-8") == "TOKEN=local"
    assert "Sawasdee" in (installed / "config" / "local.json").read_text(encoding="utf-8")
    assert (installed / "output" / "result.csv").is_file()
    assert install.stored_versions("install_demo") == ["1.0.0", "1.0.1"]
    assert not list(installed.parent.glob(".install_demo.*"))  # no staging or old folder left


@needs_ssh_keygen
def test_installing_the_same_package_again_changes_nothing(env, capsys):
    package = build(env, "1.0.0")
    assert do_install(package) == exit_codes.OK
    assert do_install(package) == exit_codes.OK
    assert "already installed" in capsys.readouterr().out


@needs_ssh_keygen
def test_a_folder_not_installed_from_a_package_is_replaced_only_when_asked(env, capsys, monkeypatch):
    package = build(env, "1.0.0")
    handmade = target(env)
    (handmade / ".git").mkdir(parents=True)
    (handmade / "flow.md").write_text("# Hand Made\n", encoding="utf-8")
    (handmade / ".env").write_text("TOKEN=mine", encoding="utf-8")
    monkeypatch.setattr(install, "interactive", lambda: False)

    assert do_install(package) == exit_codes.USAGE
    assert "--replace" in capsys.readouterr().err
    assert (handmade / "flow.md").read_text(encoding="utf-8") == "# Hand Made\n"

    assert do_install(package, replace=True) == exit_codes.OK
    assert "Install Demo" in (handmade / "flow.md").read_text(encoding="utf-8")
    assert (handmade / ".env").read_text(encoding="utf-8") == "TOKEN=mine"
    saved = [p for p in install.packages_dir("install_demo").iterdir() if p.name.startswith("replaced-")]
    assert len(saved) == 1
    assert (saved[0] / ".git").is_dir() and (saved[0] / "flow.md").read_text(encoding="utf-8") == "# Hand Made\n"


@needs_ssh_keygen
def test_a_person_is_asked_before_a_folder_is_replaced(env, monkeypatch, capsys):
    package = build(env, "1.0.0")
    (target(env)).mkdir(parents=True)
    (target(env) / "flow.md").write_text("# Copied\n", encoding="utf-8")
    monkeypatch.setattr(install, "interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert do_install(package) == exit_codes.USAGE
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert do_install(package) == exit_codes.OK


@needs_ssh_keygen
def test_changed_extra_and_unsafe_files_are_refused(env, capsys):
    package = build(env, "1.0.0")

    def changed(entries):
        entries["flow.md"] += b"\n"

    def extra(entries):
        entries["assets/added.txt"] = b"x"

    for change, words in ((changed, "is not the file that was signed"),
                          (extra, "not in the manifest")):
        bad = rewrite(package, env / "bad.kinx", change)
        assert do_install(bad) == exit_codes.INVALID_FLOW
        err = capsys.readouterr().err
        assert "PACKAGE_DAMAGED" in err and words in err
    assert not target(env).exists()


@pytest.mark.parametrize("name", ["../evil.md", "/etc/passwd", "C:/x.md", "a\\..\\b.md", "output/x", ".env",
                                  ".kinenix-deployed.json", "config/local.json"])
def test_unsafe_paths(name):
    assert install._path_problem(name)


def test_safe_paths():
    for name in ("flow.md", "config/config.json", "@shared/notify.md", "assets/ไฟล์.xlsx"):
        assert install._path_problem(name) is None


@needs_ssh_keygen
def test_a_manifest_changed_after_signing_is_untrusted(env, capsys):
    package = build(env, "1.0.0")

    def renamed(entries):
        manifest = json.loads(entries["kinenix-package.json"])
        manifest["requires"] = None
        manifest["title"] = "Something Else"
        entries["kinenix-package.json"] = json.dumps(manifest).encode("utf-8")

    bad = rewrite(package, env / "bad.kinx", renamed)
    assert do_install(bad) == exit_codes.INVALID_FLOW
    assert "PACKAGE_UNTRUSTED" in capsys.readouterr().err


@needs_ssh_keygen
def test_a_publisher_this_machine_does_not_trust_is_refused(env, capsys):
    package = build(env, "1.0.0")
    trust.remove("office-pc")
    assert do_install(package) == exit_codes.INVALID_FLOW
    err = capsys.readouterr().err
    assert "PACKAGE_UNTRUSTED" in err and "office-pc" in err and "kinenix trust add" in err


@needs_ssh_keygen
def test_a_package_for_a_newer_kinenix_is_refused(env, capsys):
    # validate refuses a too-new Requires on the building machine, so change and sign the manifest by hand
    package = build(env, "1.0.0")

    def newer(entries):
        manifest = json.loads(entries["kinenix-package.json"])
        manifest["requires"] = "kinenix>=99.0.0"
        data = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
        entries["kinenix-package.json"] = data
        entries["kinenix-package.sig"] = signing.sign(data)

    bad = rewrite(package, env / "newer.kinx", newer)
    assert do_install(bad) == exit_codes.NEWER_KINENIX
    assert "PACKAGE_REQUIRES" in capsys.readouterr().err


@needs_ssh_keygen
def test_install_waits_for_a_run_and_gives_up_without_changing_anything(env, capsys):
    first = build(env, "1.0.0")
    assert do_install(first) == exit_codes.OK
    second = build(env, "1.0.1")
    with run_lock.hold(target(env)):
        assert do_install(second, wait=0) == exit_codes.TECHNICAL
        assert "still going on" in capsys.readouterr().err
        assert "1.0.0" in (target(env) / ".kinenix-deployed.json").read_text(encoding="utf-8")

    holder = run_lock.hold(target(env))
    holder.__enter__()
    released = threading.Timer(1.5, lambda: holder.__exit__(None, None, None))
    released.start()
    assert do_install(second, wait=1) == exit_codes.OK
    assert "Waiting for the run" in capsys.readouterr().out
    released.join()


@needs_ssh_keygen
def test_rollback_and_kept_packages(env, monkeypatch, capsys):
    monkeypatch.setenv("KINENIX_PACKAGES_KEEP", "2")
    for version in ("1.0.0", "1.0.1", "1.0.2"):
        assert do_install(build(env, version)) == exit_codes.OK
    assert install.stored_versions("install_demo") == ["1.0.1", "1.0.2"]
    assert commands.rollback("install_demo", None, 0) == exit_codes.OK
    assert '"version": "1.0.1"' in (target(env) / ".kinenix-deployed.json").read_text(encoding="utf-8")
    assert commands.rollback("install_demo", None, 0) == exit_codes.NOT_FOUND
    assert commands.rollback("install_demo", "1.0.2", 0) == exit_codes.OK
    assert commands.rollback("nothing_here", None, 0) == exit_codes.NOT_FOUND


@needs_ssh_keygen
@pytest.mark.skipif(sys.platform != "win32", reason="Windows keeps open files from being renamed")
def test_a_file_in_use_on_windows_keeps_the_old_version(env, monkeypatch, capsys):
    monkeypatch.setattr(install, "SWAP_RETRY_SECONDS", 1)
    assert do_install(build(env, "1.0.0")) == exit_codes.OK
    second = build(env, "1.0.1")
    with open(target(env) / "config" / "config.json", "rb"):
        package = install.open_package(second)
        with pytest.raises(install.InstallError) as refused:
            install.install(package, lambda folder, source: True, wait_minutes=0, retry_seconds=1)
    assert refused.value.code == "FILE_IN_USE"
    assert "config/config.json" in str(refused.value)
    assert "1.0.0" in (target(env) / ".kinenix-deployed.json").read_text(encoding="utf-8")
    assert not list(target(env).parent.glob(".install_demo.*"))
    assert do_install(second) == exit_codes.OK  # closed: it goes through


@needs_ssh_keygen
def test_installed_flow_runs_from_the_cli(env):
    package = build(env, "1.0.0")
    cli_env = {**os.environ, "KINENIX_HUB_URL": "", "KINENIX_NO_UPDATE_CHECK": "1", "PYTHONIOENCODING": "utf-8"}

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "kinenix.cli", *args], env=cli_env, capture_output=True,
                              text=True, encoding="utf-8", timeout=120, stdin=subprocess.DEVNULL)

    result = cli("install", str(package))
    assert result.returncode == 0, result.stderr
    result = cli("run", "install_demo", "--log-dir", str(env / "logs"))
    assert result.returncode == 0, result.stderr

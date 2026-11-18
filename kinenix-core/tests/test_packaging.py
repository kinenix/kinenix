"""kinenix publisher, pack, and trust: signed .kinx packages (#235, part 1)."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from kinenix import exit_codes
from kinenix.cli import report_validation, resolve_flow_path
from kinenix.engine.flow_content import PACKED_FILE, read_packed
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import load_flow
from kinenix.packaging import commands, signing, trust
from kinenix.packaging.pack import package_name, secret_like

needs_ssh_keygen = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="needs OpenSSH ssh-keygen")

FLOW = """# Pack Demo
> Version: 1.3.0

## Steps

### 1. Greet (`logic.set_variable`)
- **name:** greeting
- **value:** ${config.greeting}

### 2. Notify (`flow.call`)
- **flow:** @shared/notify.md
- **output_var:** note
"""

SHARED = """# Notify

## Steps

### 1. Return (`flow.return`)
- **value:** {"sent": "yes"}
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A Kinenix home of its own: the publisher key and allowed_signers live next to KINENIX_SETTINGS_FILE."""
    monkeypatch.setenv("KINENIX_SETTINGS_FILE", str(tmp_path / "home" / "kinenix.env"))
    return tmp_path / "home"


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "work" / "flows"
    flow_dir = root / "pack_demo"
    (flow_dir / "config").mkdir(parents=True)
    (flow_dir / "flow.md").write_text(FLOW, encoding="utf-8")
    (flow_dir / "config" / "config.json").write_text('{"greeting": "Hello"}', encoding="utf-8")
    (root / "@shared").mkdir()
    (root / "@shared" / "notify.md").write_text(SHARED, encoding="utf-8")
    return flow_dir


def make_key(name="office-pc"):
    key = signing.create_key(name, passphrase_prompt=False)
    trust.add(key.line, name, replace=True)
    return key


def pack(flow_dir, out, version=None):
    return commands.pack(str(flow_dir), version, str(out), resolve_flow_path, report_validation)


# Keys and trust (no ssh-keygen needed)

PUBLIC = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIDt0xdjCxIIX1qO5cZMrZtHWfnSpWOivXamkZIa92r2 office-pc"


def test_parse_public_key_and_key_id():
    key = signing.parse_public_key(PUBLIC)
    assert key.comment == "office-pc"
    assert key.key_id == "SHA256:boASZ/2j/zq/hdRe9MTEF2FeSvQnQMooyLYIUd4VKmE"


@pytest.mark.parametrize("text", ["", "ssh-rsa AAAAB3NzaC1yc2E= x", "ssh-ed25519 not-base64!", "ssh-ed25519 AAAA"])
def test_parse_public_key_refuses_other_text(text):
    with pytest.raises(signing.SigningError):
        signing.parse_public_key(text)


def test_trust_add_list_remove(home, capsys):
    assert commands.trust_add(PUBLIC, None) == exit_codes.OK  # the name comes from the key's comment
    assert [p.name for p in trust.load()] == ["office-pc"]
    assert 'office-pc namespaces="kinenix-package" ssh-ed25519' in trust.trust_file().read_text(encoding="utf-8")
    assert commands.trust_add(PUBLIC, "again") == exit_codes.USAGE
    assert "already trusted as 'office-pc'" in capsys.readouterr().err
    assert commands.trust_list() == exit_codes.OK
    assert "SHA256:boASZ" in capsys.readouterr().out
    assert commands.trust_remove("SHA256:boASZ/2j/zq/hdRe9MTEF2FeSvQnQMooyLYIUd4VKmE") == exit_codes.OK
    assert trust.load() == []
    assert commands.trust_remove("office-pc") == exit_codes.NOT_FOUND


def test_trust_add_reads_a_pub_file_and_refuses_a_used_name(home, tmp_path):
    pub = tmp_path / "office.pub"
    pub.write_text(PUBLIC + "\n", encoding="utf-8")
    assert trust.add(str(pub), "office").name == "office"
    other = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGGFv2Wn3QZ0fFJq5m2bT7wK8nZc1Yd9pXr4sLmE0aB1 lab"
    with pytest.raises(trust.TrustError, match="already used"):
        trust.add(other, "office")
    with pytest.raises(signing.SigningError, match="cannot be a publisher name"):
        trust.add(other, "lab pc")


def test_a_damaged_trust_file_is_reported(home):
    home.mkdir(parents=True)
    trust.trust_file().write_text("broken line\n", encoding="utf-8")
    with pytest.raises(trust.TrustError, match="line 1"):
        trust.load()


def test_missing_or_old_ssh_keygen_says_what_to_install(monkeypatch):
    monkeypatch.setattr(signing.shutil, "which", lambda name: None)
    with pytest.raises(signing.SigningError, match="OpenSSH Client"):
        signing.ssh_keygen()
    monkeypatch.setattr(signing.shutil, "which", lambda name: "/usr/bin/ssh-keygen")
    monkeypatch.setattr(signing, "openssh_version", lambda path: (7, 9))
    with pytest.raises(signing.SigningError, match="8.1 or later"):
        signing.ssh_keygen()


def test_secret_like_names():
    names = ["flow.md", "assets/server.pem", "config/api_token.txt", ".env.example", "assets/logo.png", "id_rsa"]
    assert secret_like(names) == ["assets/server.pem", "config/api_token.txt", "id_rsa"]


def test_package_name_is_the_folder_name(tmp_path):
    assert package_name(tmp_path / "Get Stock Data") == "get_stock_data"


# Signing (needs ssh-keygen)

@needs_ssh_keygen
def test_sign_and_verify(home):
    key = make_key()
    signature = signing.sign(b"manifest")
    assert signature.startswith(b"-----BEGIN SSH SIGNATURE-----")
    assert signing.verify(b"manifest", signature, key)
    assert not signing.verify(b"manifesT", signature, key)
    assert not signing.verify(b"manifest", signature, signing.parse_public_key(PUBLIC))
    listed = subprocess.run(["ssh-keygen", "-l", "-E", "sha256", "-f", str(signing.public_key_path())],
                            capture_output=True, text=True).stdout
    assert key.key_id in listed


@needs_ssh_keygen
def test_publisher_init_trusts_its_key_and_keeps_it(home, capsys):
    assert commands.publisher_init("office-pc", force=False, no_passphrase=True) == exit_codes.OK
    first = signing.read_public_key()
    assert [p.key_id for p in trust.load()] == [first.key_id]
    if os.name != "nt":
        assert (signing.private_key_path().stat().st_mode & 0o777) == 0o600
    assert commands.publisher_init(None, force=False, no_passphrase=True) == exit_codes.OK
    assert signing.read_public_key().key_id == first.key_id
    assert commands.publisher_init(None, force=True, no_passphrase=True) == exit_codes.OK
    second = signing.read_public_key()
    assert second.key_id != first.key_id and second.comment == "office-pc"
    assert [p.key_id for p in trust.load()] == [second.key_id]  # the old key is no longer trusted
    assert commands.publisher_show() == exit_codes.OK
    assert second.line in capsys.readouterr().out


# Packing (needs ssh-keygen)

@needs_ssh_keygen
def test_pack_builds_a_signed_package(home, bundle, tmp_path, capsys):
    key = make_key()
    for rel in (".env", "config/local.json", "output/result.csv", "logs/run.json", "tests/page.html"):
        (bundle / rel).parent.mkdir(parents=True, exist_ok=True)
        (bundle / rel).write_text('{"left": "out"}', encoding="utf-8")
    out = tmp_path / "dist"
    assert pack(bundle, out) == exit_codes.OK
    package = out / "pack_demo-1.3.0.kinx"
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        manifest_bytes = archive.read("kinenix-package.json")
        signature = archive.read("kinenix-package.sig")
        contents = {name: archive.read(name) for name in names}
    assert sorted(names) == ["@shared/notify.md", "config/config.json", "flow.md", "kinenix-package.json",
                             "kinenix-package.sig"]
    manifest = json.loads(manifest_bytes)
    assert (manifest["format"], manifest["name"], manifest["title"], manifest["version"]) == \
        (1, "pack_demo", "Pack Demo", "1.3.0")
    assert manifest["publisher"] == {"name": "office-pc", "key_id": key.key_id}
    assert manifest["shared"] == ["@shared/notify.md"]
    for rel, digest in manifest["files"].items():
        assert hashlib.sha256(contents[rel]).hexdigest() == digest
    assert signing.verify(manifest_bytes, signature, key)
    assert "1.3.0" in read_packed(bundle)
    assert "Package:" in capsys.readouterr().out


@needs_ssh_keygen
def test_unpacked_package_runs_with_its_own_shared_copy(home, bundle, tmp_path):
    make_key()
    assert pack(bundle, tmp_path / "dist") == exit_codes.OK
    installed = tmp_path / "elsewhere" / "pack_demo"  # no @shared folder anywhere above it
    with zipfile.ZipFile(tmp_path / "dist" / "pack_demo-1.3.0.kinx") as archive:
        archive.extractall(installed)
    interpreter = FlowInterpreter(logger=ExecutionLogger(log_dir=tmp_path / "logs"))
    ctx = interpreter.run_flow(load_flow(installed / "flow.md"), initial_vars={"__flow_dir__": str(installed)})
    assert not ctx.has_error, ctx.failure_details
    assert ctx.get_variable("note") == {"sent": "yes"}


@needs_ssh_keygen
def test_pack_refuses_a_changed_flow_that_kept_its_version(home, bundle, tmp_path, capsys):
    make_key()
    assert pack(bundle, tmp_path / "dist") == exit_codes.OK
    (bundle / "config" / "config.json").write_text('{"greeting": "Hi"}', encoding="utf-8")
    assert pack(bundle, tmp_path / "dist") == exit_codes.INVALID_FLOW
    assert "config/config.json changed" in capsys.readouterr().err
    assert pack(bundle, tmp_path / "dist", version="1.3.1") == exit_codes.OK
    assert list(read_packed(bundle)) == ["1.3.0", "1.3.1"]


@needs_ssh_keygen
def test_pack_needs_a_valid_version(home, bundle, tmp_path, capsys):
    make_key()
    (bundle / "flow.md").write_text(FLOW.replace("> Version: 1.3.0\n", ""), encoding="utf-8")
    assert pack(bundle, tmp_path / "dist") == exit_codes.USAGE
    assert "no version" in capsys.readouterr().err
    assert pack(bundle, tmp_path / "dist", version="1.3") == exit_codes.USAGE
    assert pack(bundle, tmp_path / "dist", version="2.0.0") == exit_codes.OK
    assert not (bundle / PACKED_FILE).read_text(encoding="utf-8").count("1.3.0")


def test_pack_without_a_key_says_how_to_make_one(home, bundle, tmp_path, capsys):
    assert pack(bundle, tmp_path / "dist") == exit_codes.TECHNICAL
    assert "kinenix publisher init" in capsys.readouterr().err
    assert not (bundle / PACKED_FILE).exists()


def test_pack_refuses_an_invalid_flow_and_a_single_file(home, bundle, tmp_path):
    (bundle / "flow.md").write_text(FLOW.replace("logic.set_variable", "logic.set_varable"), encoding="utf-8")
    assert pack(bundle, tmp_path / "dist") == exit_codes.INVALID_FLOW
    single = tmp_path / "single.md"
    single.write_text(FLOW, encoding="utf-8")
    assert pack(single, tmp_path / "dist") == exit_codes.USAGE


@needs_ssh_keygen
def test_pack_warns_about_secret_like_files(home, bundle, tmp_path, capsys):
    make_key()
    (bundle / "assets").mkdir()
    (bundle / "assets" / "server.pem").write_text("-----BEGIN-----", encoding="utf-8")
    assert pack(bundle, tmp_path / "dist") == exit_codes.OK
    assert "assets/server.pem looks like it may hold a secret" in capsys.readouterr().err


@needs_ssh_keygen
def test_cli_pack_and_trust(home, bundle, tmp_path):
    env = {**os.environ, "KINENIX_SETTINGS_FILE": str(home / "kinenix.env"), "KINENIX_HUB_URL": "",
           "KINENIX_NO_UPDATE_CHECK": "1", "PYTHONIOENCODING": "utf-8"}

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "kinenix.cli", *args], env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=120, stdin=subprocess.DEVNULL)

    assert cli("publisher", "init", "--name", "office-pc", "--no-passphrase").returncode == 0
    result = cli("pack", str(bundle), "-o", str(tmp_path / "dist"))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "dist" / "pack_demo-1.3.0.kinx").is_file()
    listed = cli("trust", "list")
    assert "office-pc" in listed.stdout and "(this machine)" in listed.stdout

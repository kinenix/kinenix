"""Ed25519 keys and signatures with OpenSSH's ssh-keygen (8.1 or later: `-Y sign` and `-Y verify`).

The private key never leaves the building machine. A package is signed by signing its manifest, which holds
the SHA-256 of every file, so the signature covers the whole package.
"""
import base64
import hashlib
import os
import re
import shutil
import socket
import subprocess  # nosec B404: runs only ssh-keygen, found on PATH, with fixed arguments
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from ..workspace import settings_file

NAMESPACE = "kinenix-package"
KEY_TYPE = "ssh-ed25519"
MIN_OPENSSH = (8, 1)
KEY_FILE = "publisher_ed25519"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
TIMEOUT = 120  # a person may be typing the key's passphrase


class SigningError(RuntimeError):
    """ssh-keygen is missing or too old, or a key or signature cannot be used."""


INSTALL_HINT = ("Install the OpenSSH client: on Windows, Settings > System > Optional features > OpenSSH Client; "
                "on Ubuntu or Raspberry Pi OS, sudo apt install openssh-client.")


def kinenix_home() -> Path:
    """~/.kinenix, or the folder of KINENIX_SETTINGS_FILE (tests point it to a temporary folder)."""
    return settings_file().parent


def publisher_dir() -> Path:
    return kinenix_home() / "publisher"


def private_key_path() -> Path:
    return publisher_dir() / KEY_FILE


def public_key_path() -> Path:
    return publisher_dir() / (KEY_FILE + ".pub")


def ssh_keygen() -> str:
    """The path of ssh-keygen 8.1 or later, or SigningError saying what is missing."""
    path = shutil.which("ssh-keygen")
    if not path:
        raise SigningError(f"ssh-keygen was not found. Signing flow packages needs OpenSSH 8.1 or later. "
                           f"{INSTALL_HINT}")
    version = openssh_version(path)
    if version is not None and version < MIN_OPENSSH:
        raise SigningError(f"{path} is OpenSSH {version[0]}.{version[1]}; signing flow packages needs 8.1 or "
                           f"later. {INSTALL_HINT}")
    return path


def openssh_version(keygen: str) -> Optional[Tuple[int, int]]:
    """The OpenSSH version next to ssh-keygen (`ssh -V`), None when it cannot be told."""
    ssh = Path(keygen).with_name("ssh.exe" if keygen.lower().endswith(".exe") else "ssh")
    if not ssh.is_file():
        return None
    try:
        result = subprocess.run([str(ssh), "-V"], capture_output=True, text=True, timeout=10)  # nosec B603
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"OpenSSH_(?:for_Windows_)?(\d+)\.(\d+)", result.stderr + result.stdout)
    return (int(match.group(1)), int(match.group(2))) if match else None


@dataclass
class PublicKey:
    """One `ssh-ed25519 AAAA... name` line."""
    blob: str
    comment: str = ""

    @property
    def line(self) -> str:
        return f"{KEY_TYPE} {self.blob}" + (f" {self.comment}" if self.comment else "")

    @property
    def key_id(self) -> str:
        """The SHA256 fingerprint ssh-keygen -l shows, such as SHA256:Xb3...; the manifest names the key by it."""
        digest = hashlib.sha256(base64.b64decode(self.blob)).digest()
        return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def parse_public_key(text: str) -> PublicKey:
    """An Ed25519 public key from its one-line form (what `kinenix publisher show` prints)."""
    parts = text.strip().split()
    if len(parts) < 2 or parts[0] != KEY_TYPE:
        raise SigningError("Not an Ed25519 public key. Copy the whole line `ssh-ed25519 AAAA... name` that "
                           "`kinenix publisher show` prints on the building machine.")
    try:
        raw = base64.b64decode(parts[1], validate=True)
    except ValueError:
        raise SigningError("The public key is damaged: its AAAA... part is not valid base64.") from None
    # The key blob starts with its type as an SSH string: 4-byte length, then the name
    expected = len(KEY_TYPE).to_bytes(4, "big") + KEY_TYPE.encode("ascii")
    if not raw.startswith(expected) or len(raw) != len(expected) + 4 + 32:
        raise SigningError("The public key is damaged or not Ed25519.")
    return PublicKey(blob=parts[1], comment=" ".join(parts[2:]))


def check_name(name: str) -> str:
    if not NAME_PATTERN.match(name or ""):
        raise SigningError(f"'{name}' cannot be a publisher name. Use up to 64 letters, digits, '.', '_', '-', "
                           f"or '@', without spaces, such as office-pc.")
    return name


def default_name() -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", socket.gethostname()).strip("-.")[:64]
    return name or "publisher"


def read_public_key() -> Optional[PublicKey]:
    path = public_key_path()
    return parse_public_key(path.read_text(encoding="utf-8")) if path.is_file() else None


def create_key(name: str, passphrase_prompt: bool) -> PublicKey:
    """Makes the publisher key with ssh-keygen. With passphrase_prompt, ssh-keygen asks for a passphrase
    (Enter for none); otherwise the key has none. The caller decides whether an existing key may go."""
    keygen = ssh_keygen()
    check_name(name)
    folder = publisher_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for path in (private_key_path(), public_key_path()):
        if path.exists():
            path.unlink()
    command = [keygen, "-q", "-t", "ed25519", "-C", name, "-f", str(private_key_path())]
    if not passphrase_prompt:
        command += ["-N", ""]
    try:
        result = subprocess.run(command, timeout=TIMEOUT,  # nosec B603: fixed arguments
                                stdin=None if passphrase_prompt else subprocess.DEVNULL,
                                capture_output=not passphrase_prompt, text=True)
    except subprocess.TimeoutExpired:
        raise SigningError("ssh-keygen did not finish making the key.") from None
    if result.returncode != 0 or not public_key_path().is_file():
        detail = (result.stderr or "").strip() if not passphrase_prompt else ""
        raise SigningError(f"ssh-keygen could not make the key{': ' + detail if detail else ''}.")
    if os.name != "nt":
        os.chmod(folder, 0o700)
        os.chmod(private_key_path(), 0o600)
    return read_public_key()


def sign(data: bytes) -> bytes:
    """The OpenSSH signature of data with the publisher key. ssh-keygen asks for the passphrase if the key
    has one; without a terminal such a key cannot be used."""
    keygen = ssh_keygen()
    if not private_key_path().is_file():
        raise SigningError("This machine has no publisher key. Run `kinenix publisher init` first.")
    with tempfile.TemporaryDirectory(prefix="kinenix-sign-") as tmp:
        message = Path(tmp) / "kinenix-package.json"
        message.write_bytes(data)
        interactive = sys.stdin is not None and sys.stdin.isatty()
        try:
            result = subprocess.run(  # nosec B603: fixed arguments
                [keygen, "-Y", "sign", "-f", str(private_key_path()), "-n", NAMESPACE, str(message)],
                # The passphrase prompt reads the terminal itself, so stderr ("Signing file ...") can be kept
                timeout=TIMEOUT, stdin=None if interactive else subprocess.DEVNULL,
                capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            raise SigningError("ssh-keygen did not finish signing (waiting for the key's passphrase?).") from None
        signature = message.with_name(message.name + ".sig")
        if result.returncode != 0 or not signature.is_file():
            lines = [line for line in (result.stderr or "").splitlines()
                     if not line.startswith(("Signing file", "Write signature"))]
            detail = " ".join(line.strip() for line in lines if line.strip())
            hint = "" if interactive else " If the key has a passphrase, run kinenix pack in a terminal."
            raise SigningError(f"ssh-keygen could not sign{': ' + detail if detail else ''}.{hint}")
        return signature.read_bytes()


def verify(data: bytes, signature: bytes, key: PublicKey, principal: str = "publisher") -> bool:
    """Whether signature is key's signature of data, in the kinenix-package namespace."""
    keygen = ssh_keygen()
    with tempfile.TemporaryDirectory(prefix="kinenix-verify-") as tmp:
        signers = Path(tmp) / "allowed_signers"
        signers.write_text(f'{principal} namespaces="{NAMESPACE}" {KEY_TYPE} {key.blob}\n', encoding="utf-8")
        sig_path = Path(tmp) / "kinenix-package.sig"
        sig_path.write_bytes(signature)
        try:
            result = subprocess.run(  # nosec B603: fixed arguments
                [keygen, "-Y", "verify", "-f", str(signers), "-I", principal, "-n", NAMESPACE, "-s", str(sig_path)],
                input=data, capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0

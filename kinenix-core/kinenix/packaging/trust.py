"""Publishers this machine accepts packages from: ~/.kinenix/allowed_signers, in OpenSSH's format.

Only the owner of the machine changes it, with `kinenix trust add / remove`; the Hub never sends keys to it
(docs/design/flow-deploy.md, sections 5 and 6). Each line is
`<name> namespaces="kinenix-package" ssh-ed25519 AAAA...`, so `ssh-keygen -Y verify` reads it as it is.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .signing import KEY_TYPE, NAMESPACE, PublicKey, SigningError, check_name, kinenix_home, parse_public_key

TRUST_FILE = "allowed_signers"


class TrustError(ValueError):
    """A publisher cannot be added or removed as asked."""


@dataclass
class Publisher:
    name: str
    key: PublicKey

    @property
    def key_id(self) -> str:
        return self.key.key_id

    def line(self) -> str:
        return f'{self.name} namespaces="{NAMESPACE}" {KEY_TYPE} {self.key.blob}'


def trust_file() -> Path:
    return kinenix_home() / TRUST_FILE


def load() -> List[Publisher]:
    path = trust_file()
    if not path.is_file():
        return []
    publishers: List[Publisher] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        parts = text.split()
        try:
            at = parts.index(KEY_TYPE)
            publishers.append(Publisher(parts[0], parse_public_key(" ".join(parts[at:at + 2]))))
        except (ValueError, SigningError):
            raise TrustError(f"{path}, line {number}, cannot be read. Fix or remove that line; "
                             f"`kinenix trust add` writes lines like `name namespaces=\"{NAMESPACE}\" "
                             f"ssh-ed25519 AAAA...`.") from None
    return publishers


def _save(publishers: List[Publisher]) -> None:
    path = trust_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# Publishers whose flow packages this machine installs. Change with kinenix trust add / remove.\n"
    path.write_text(header + "".join(p.line() + "\n" for p in publishers), encoding="utf-8")


def find(key_id: str) -> Optional[Publisher]:
    return next((p for p in load() if p.key_id == key_id), None)


def add(key_text: str, name: Optional[str] = None, replace: bool = False) -> Publisher:
    """Trusts a public key under a name (default: the key's comment). The same key twice, or a name already
    used by another key, is refused unless replace is set (publisher init replaces its own old key)."""
    text = key_text.strip()
    candidate = Path(text)
    if not text.startswith(KEY_TYPE) and len(text) < 1024 and candidate.is_file():
        text = candidate.read_text(encoding="utf-8").strip()
    key = parse_public_key(text)
    if not name and key.comment:
        name = key.comment.split()[0]
    if not name:
        raise TrustError("This key has no name. Give it one with --name, such as --name office-pc.")
    check_name(name)
    publishers = load()
    same_key = next((p for p in publishers if p.key_id == key.key_id), None)
    same_name = next((p for p in publishers if p.name == name), None)
    if same_key and same_key.name == name:
        return same_key
    if same_key and not replace:
        raise TrustError(f"This key is already trusted as '{same_key.name}' ({key.key_id}).")
    if same_name and not replace:
        raise TrustError(f"The name '{name}' is already used by another key ({same_name.key_id}). "
                         f"Choose another --name, or `kinenix trust remove {name}` first.")
    publishers = [p for p in publishers if p not in (same_key, same_name)]
    publisher = Publisher(name, PublicKey(key.blob, name))
    publishers.append(publisher)
    _save(publishers)
    return publisher


def remove(name_or_key_id: str) -> Publisher:
    publishers = load()
    match = next((p for p in publishers if name_or_key_id in (p.name, p.key_id)), None)
    if match is None:
        names = ", ".join(p.name for p in publishers) or "none"
        raise TrustError(f"No trusted publisher '{name_or_key_id}'. Trusted: {names}.")
    _save([p for p in publishers if p is not match])
    return match

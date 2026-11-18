"""`kinenix pack`: build `<name>-<version>.kinx`, a zip of the flow with a signed manifest (#235).

Layout (docs/design/flow-deploy.md, section 4):

    hello-1.3.0.kinx
        kinenix-package.json   manifest: name, version, the SHA-256 of every file, publisher key id, ...
        kinenix-package.sig    ssh-keygen -Y sign of the manifest
        flow.md, config/, subflows/, assets/
        @shared/...            the @shared/ subflows the flow calls

Installed as ~/kinenix-flows/<name>/, the copied @shared/ folder sits in the flow folder, which is the first
place a flow.call to @shared/... looks, so flow.md needs no change. The files are those whose content
.kinenix-packed.json records (engine/flow_content.py), so the version check and the package agree.
"""
import fnmatch
import hashlib
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .. import __version__
from ..engine.flow_content import (
    MANIFEST_FILE,
    PACKAGE_SUFFIX,
    SIGNATURE_FILE,
    bundle_files,
    content_files,
    record_packed,
    shared_files,
)
from ..models.flow import FlowDefinition
from ..scaffold import project_folder_name
from .signing import SigningError, read_public_key, sign, verify

FORMAT = 1
SIZE_WARNING = 50 * 1024 * 1024  # the Hub's default upload limit (flow-deploy.md, section 6)
# File names that often hold secrets; pack warns and still packs them (a template may be meant to go)
FLAGGED_PATTERNS = ("*.pem", "*.key", "*.pfx", "*.p12", "*.kdbx", "id_rsa*", "id_ed25519*", "id_ecdsa*", "*secret*",
               "*password*", "*passwd*", "*token*", "credentials*", ".env.*", ".netrc")


class PackError(ValueError):
    """The flow cannot be packed as asked."""


@dataclass
class PackResult:
    path: Path
    manifest: Dict[str, Any]
    size: int
    flagged_names: List[str] = field(default_factory=list)


def package_name(flow_dir: Path) -> str:
    """The flow folder's name, as kinenix init makes it ('Get stock data' -> get_stock_data)."""
    return project_folder_name(Path(flow_dir).resolve().name)


def package_file_name(name: str, version: str) -> str:
    return f"{name}-{version}{PACKAGE_SUFFIX}"


def flagged_names(names: List[str]) -> List[str]:
    found = []
    for name in names:
        base = name.rsplit("/", 1)[-1].lower()
        if base.endswith(".example"):
            continue
        if any(fnmatch.fnmatch(base, pattern) for pattern in FLAGGED_PATTERNS):
            found.append(name)
    return found


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(flow: FlowDefinition, flow_dir: Path, version: str, output_dir: Path) -> PackResult:
    """Builds and signs the package and records the version in .kinenix-packed.json. The caller has validated
    the flow, including that it did not change since this version was packed."""
    flow_dir = Path(flow_dir).resolve()
    key = read_public_key()
    if key is None:
        raise SigningError("This machine has no publisher key. Run `kinenix publisher init` first.")

    name = package_name(flow_dir)
    files = {**bundle_files(flow_dir), **shared_files(flow, flow_dir)}
    if "flow.md" not in files:
        raise PackError(f"{flow_dir} has no flow.md; kinenix pack builds a flow folder (a bundle).")

    manifest: Dict[str, Any] = {
        "format": FORMAT,
        "name": name,
        "title": flow.name,
        "version": version,
        "requires": flow.requires,
        "kinenix_version": __version__,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "publisher": {"name": key.comment.split()[0] if key.comment else "", "key_id": key.key_id},
        "files": {rel: _sha256(path) for rel, path in sorted(files.items())},
        "shared": sorted(rel for rel in files if rel.startswith("@shared/")),
    }
    data = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    signature = sign(data)
    if not verify(data, signature, key):
        raise SigningError("The signature ssh-keygen made does not verify with this machine's public key "
                           f"({key.key_id}). Run `kinenix publisher show` and check the key files.")

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / package_file_name(name, version)
    partial = target.with_name(target.name + ".part")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
        archive.writestr(MANIFEST_FILE, data)
        archive.writestr(SIGNATURE_FILE, signature)
        for rel, path in sorted(files.items()):
            archive.write(path, rel)
    os.replace(partial, target)  # a package of this version with the same content, built again, is replaced

    record_packed(flow_dir, version, content_files(flow.model_copy(update={"version": version}), flow_dir))
    return PackResult(path=target, manifest=manifest, size=target.stat().st_size,
                      flagged_names=flagged_names(list(files)))

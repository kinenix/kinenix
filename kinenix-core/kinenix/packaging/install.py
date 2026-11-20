"""`kinenix install` and `kinenix rollback`: check a signed .kinx package and put it in the flows folder (#235).

Design: docs/design/flow-deploy.md, sections 5 and 7. Every check runs before anything on the machine changes:
the signature against a publisher this machine trusts, the files against the manifest, the paths (threat model
T6), and `> Requires:`. The new version is unpacked next to the flow folder, the machine's own `.env`,
`config/local.json`, `output/`, and `logs/` are moved into it, and the folders are swapped by renaming once no
run of the flow is going on. Any failure puts the old folder back whole.
"""
import hashlib
import json
import os
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional

from .. import __version__, exit_codes
from ..engine import run_lock
from ..engine.flow_content import DEPLOYED_FILE, MANIFEST_FILE, PACKAGE_SUFFIX, SIGNATURE_FILE, version_problem
from ..engine.requires import requirement_problem, version_key
from ..scaffold import project_folder_name
from ..workspace import flows_dir
from . import trust
from .pack import package_file_name
from .signing import kinenix_home, verify

KEPT = (".env", "config/local.json", "output", "logs")  # the machine's own, never replaced
MAX_FILES = 10000
MAX_UNPACKED = 1024 * 1024 * 1024  # 1 GB unpacked; a zip that claims more is refused (zip bomb)
MAX_MANIFEST = 10 * 1024 * 1024
DEFAULT_KEEP = 10
DEFAULT_WAIT_MINUTES = 30
SWAP_RETRY_SECONDS = 120  # Windows: a scan or a program holding a file lets go within this time, or it does not
SOURCE_MARKERS = (".git", ".kinenix-packed.json")


class InstallError(Exception):
    """An install that did not happen; nothing on the machine changed. `code` is a stable name."""

    def __init__(self, code: str, message: str, exit_code: int):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


def _damaged(message: str) -> InstallError:
    return InstallError("PACKAGE_DAMAGED", message, exit_codes.INVALID_FLOW)


@dataclass
class Package:
    path: Path
    manifest: Dict
    publisher: trust.Publisher
    sha256: str

    @property
    def name(self) -> str:
        return self.manifest["name"]

    @property
    def version(self) -> str:
        return self.manifest["version"]


@dataclass
class InstallResult:
    package: Package
    target: Path
    status: str  # installed, unchanged
    previous_version: Optional[str] = None
    replaced_folder: Optional[Path] = None  # where a folder that was not installed from a package was saved
    kept: List[str] = field(default_factory=list)


def packages_dir(name: str) -> Path:
    return kinenix_home() / "packages" / name


def keep_count() -> int:
    try:
        return max(1, int(os.environ.get("KINENIX_PACKAGES_KEEP", DEFAULT_KEEP)))
    except ValueError:
        return DEFAULT_KEEP


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_problem(name: str) -> Optional[str]:
    """Why a zip entry name may not be unpacked, or None (threat model T6)."""
    if not name or "\\" in name or "\0" in name or name.startswith("/") or ":" in name:
        return "is not a plain relative path"
    parts = PurePosixPath(name).parts
    if any(part in ("", ".", "..") for part in parts) or name.endswith("/"):
        return "leaves the flow folder or is not a file"
    if parts[0] in KEPT or name in KEPT or name == DEPLOYED_FILE:
        return "would replace this machine's own settings or records"
    return None


def open_package(path: Path) -> Package:
    """Checks a package without unpacking it: signature, files, paths, and > Requires:."""
    path = Path(path)
    if not path.is_file():
        raise InstallError("FILE_NOT_FOUND", f"{path} was not found.", exit_codes.NOT_FOUND)
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise _damaged(f"{path.name} is not a readable package ({e}).") from None
    with archive:
        infos = {info.filename: info for info in archive.infolist()}
        for needed in (MANIFEST_FILE, SIGNATURE_FILE):
            if needed not in infos:
                raise _damaged(f"{path.name} has no {needed}; it was not built by kinenix pack.")
        if infos[MANIFEST_FILE].file_size > MAX_MANIFEST:
            raise _damaged(f"{path.name} has a manifest that is too large.")
        manifest_bytes = archive.read(MANIFEST_FILE)
        signature = archive.read(SIGNATURE_FILE)
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise _damaged(f"The manifest of {path.name} cannot be read.") from None
        if not isinstance(manifest, dict) or manifest.get("format") != 1:
            raise _damaged(f"{path.name} is in a package format this Kinenix ({__version__}) does not know; "
                           f"upgrade Kinenix here.")

        # 1. Signature, by a publisher this machine trusts
        publisher_info = manifest.get("publisher") if isinstance(manifest.get("publisher"), dict) else {}
        key_id = str(publisher_info.get("key_id", ""))
        named = str(publisher_info.get("name", "")) or "unknown"
        publisher = trust.find(key_id)
        if publisher is None:
            raise InstallError(
                "PACKAGE_UNTRUSTED",
                f"{path.name} is signed by '{named}' ({key_id or 'no key id'}), which this machine does not trust. "
                f"If you trust that machine, run `kinenix publisher show` there and `kinenix trust add` the line "
                f"it prints here.", exit_codes.INVALID_FLOW)
        if not verify(manifest_bytes, signature, publisher.key, publisher.name):
            raise InstallError(
                "PACKAGE_UNTRUSTED",
                f"The signature of {path.name} does not match the key of '{publisher.name}' ({key_id}): the "
                f"package was changed after it was signed, or signed with another key.", exit_codes.INVALID_FLOW)

        # 2. The signed manifest describes the package exactly
        name, version = manifest.get("name"), manifest.get("version")
        if not isinstance(name, str) or not name or project_folder_name(name) != name:
            raise _damaged(f"The package name '{name}' is not a flow folder name.")
        if not isinstance(version, str) or version_problem(version):
            raise _damaged(f"The package version '{version}' is not understood.")
        files = manifest.get("files")
        if not isinstance(files, dict) or "flow.md" not in files:
            raise _damaged(f"{path.name} lists no flow.md.")
        if len(files) > MAX_FILES:
            raise _damaged(f"{path.name} lists more than {MAX_FILES} files.")
        entries = set(infos) - {MANIFEST_FILE, SIGNATURE_FILE}
        extra, missing = sorted(entries - set(files)), sorted(set(files) - entries)
        if extra or missing:
            detail = "; ".join(filter(None, [f"not in the manifest: {', '.join(extra[:5])}" if extra else "",
                                             f"missing: {', '.join(missing[:5])}" if missing else ""]))
            raise _damaged(f"The files of {path.name} do not match its signed manifest ({detail}).")

        # 3. Paths stay in the flow folder (T6)
        for entry in files:
            problem = _path_problem(entry)
            if problem:
                raise _damaged(f"{path.name} holds '{entry}', which {problem}.")
        if sum(infos[entry].file_size for entry in files) > MAX_UNPACKED:
            raise _damaged(f"{path.name} would unpack to more than {MAX_UNPACKED // (1024 * 1024)} MB.")

        # 4. Every file is the one that was signed
        for entry, expected in files.items():
            digest = hashlib.sha256()
            try:
                with archive.open(entry) as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except (zipfile.BadZipFile, OSError, RuntimeError) as e:
                raise _damaged(f"{entry} in {path.name} cannot be read ({e}).") from None
            if digest.hexdigest() != expected:
                raise _damaged(f"{entry} in {path.name} is not the file that was signed.")

    # 5. This Kinenix can run it
    problem = requirement_problem(manifest.get("requires"))
    if problem:
        raise InstallError("PACKAGE_REQUIRES", problem, exit_codes.NEWER_KINENIX)
    return Package(path=path, manifest=manifest, publisher=publisher, sha256=_file_sha256(path))


def read_deployed(folder: Path) -> Optional[Dict]:
    path = Path(folder) / DEPLOYED_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def looks_like_source(folder: Path) -> bool:
    return any((Path(folder) / marker).exists() for marker in SOURCE_MARKERS)


def _wait_for_runs(target: Path, wait_minutes: float, on_wait: Callable[[List[int]], None]) -> None:
    deadline = time.monotonic() + max(0.0, wait_minutes) * 60
    told = False
    while True:
        pids = run_lock.running_pids(target)
        if not pids:
            return
        if time.monotonic() >= deadline:
            raise InstallError(
                "FLOW_RUNNING",
                f"A run of {target.name} is still going on (process {', '.join(map(str, pids))}); nothing was "
                f"changed. Install again when it has ended, or wait longer with --wait MINUTES.",
                exit_codes.TECHNICAL)
        if not told:
            on_wait(pids)
            told = True
        time.sleep(1)


def _files_in_use(folder: Path, limit: int = 3) -> List[str]:
    """Files that cannot be renamed, which on Windows means a program holds them open."""
    busy: List[str] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        probe = path.with_name(path.name + ".kinenix-probe")
        try:
            os.rename(path, probe)
        except OSError:
            busy.append(path.relative_to(folder).as_posix())
            if len(busy) >= limit:
                break
            continue
        try:
            os.rename(probe, path)
        except OSError:
            pass
    return busy


def _rename(source: Path, target: Path, retry_seconds: float, watched: Path) -> None:
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            os.rename(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                busy = _files_in_use(watched)
                named = f": {', '.join(busy)} {'is' if len(busy) == 1 else 'are'} in use" if busy else ""
                raise InstallError(
                    "FILE_IN_USE",
                    f"{watched} could not be replaced{named}. Close the program that has it open (Excel, an "
                    f"Explorer window, a terminal in that folder) and install again; the old version is "
                    f"unchanged. Kinenix never closes other programs.", exit_codes.TECHNICAL) from None
            time.sleep(1)


def _unpack(package: Package, staging: Path) -> None:
    with zipfile.ZipFile(package.path) as archive:
        for entry in package.manifest["files"]:
            destination = staging.joinpath(*PurePosixPath(entry).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, open(destination, "wb") as out:
                shutil.copyfileobj(source, out)


def _deployed_record(package: Package) -> Dict:
    return {"name": package.name, "title": package.manifest.get("title"), "version": package.version,
            "publisher": {"name": package.publisher.name, "key_id": package.publisher.key_id},
            "package_sha256": package.sha256, "kinenix_version": __version__,
            "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _move_kept(source: Path, destination: Path) -> List[str]:
    moved = []
    for rel in KEPT:
        old = source / rel
        if old.exists():
            new = destination / rel
            new.parent.mkdir(parents=True, exist_ok=True)
            os.rename(old, new)
            moved.append(rel)
    return moved


def store_package(package: Package, current_version: str) -> None:
    """Keeps the package for rollback, and the newest KINENIX_PACKAGES_KEEP versions (never the one in use)."""
    folder = packages_dir(package.name)
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / package_file_name(package.name, package.version)
    if package.path.resolve() != stored.resolve():
        shutil.copy2(package.path, stored)
    versions = []
    for path in folder.glob(f"{package.name}-*{PACKAGE_SUFFIX}"):
        version = path.name[len(package.name) + 1:-len(PACKAGE_SUFFIX)]
        if version_key(version) is not None:
            versions.append((version_key(version), version, path))
    versions.sort(reverse=True)
    for _, version, path in versions[keep_count():]:
        if version != current_version:
            path.unlink()


def stored_versions(name: str) -> List[str]:
    folder = packages_dir(name)
    found = []
    for path in folder.glob(f"{name}-*{PACKAGE_SUFFIX}") if folder.is_dir() else []:
        version = path.name[len(name) + 1:-len(PACKAGE_SUFFIX)]
        if version_key(version) is not None:
            found.append(version)
    return sorted(found, key=version_key)


def install(package: Package, confirm_replace: Callable[[Path, bool], bool],
            wait_minutes: float = DEFAULT_WAIT_MINUTES, on_wait: Callable[[List[int]], None] = lambda pids: None,
            target_root: Optional[Path] = None, retry_seconds: float = SWAP_RETRY_SECONDS) -> InstallResult:
    """Installs a checked package into <flows folder>/<name>. confirm_replace(folder, is_source) is asked only
    for a folder that was not installed from a package; False leaves everything as it is."""
    root = Path(target_root) if target_root else flows_dir()
    target = root / package.name
    deployed = read_deployed(target) if target.exists() else None
    previous = deployed.get("version") if deployed else None

    if deployed and previous == package.version and deployed.get("package_sha256") == package.sha256:
        store_package(package, package.version)
        return InstallResult(package, target, "unchanged", previous_version=previous)
    handmade = target.exists() and deployed is None
    if handmade and not confirm_replace(target, looks_like_source(target)):
        raise InstallError("REPLACE_REFUSED", f"{target} was left as it is; nothing was installed. "
                           f"To replace it, run again with --replace.", exit_codes.USAGE)

    _wait_for_runs(target, wait_minutes, on_wait)

    root.mkdir(parents=True, exist_ok=True)
    tag = f"{os.getpid()}-{int(time.time())}"
    staging = root / f".{package.name}.installing-{tag}"
    old = root / f".{package.name}.old-{tag}"
    try:
        _unpack(package, staging)
        (staging / DEPLOYED_FILE).write_text(json.dumps(_deployed_record(package), indent=2) + "\n",
                                             encoding="utf-8")
    except OSError as e:
        shutil.rmtree(staging, ignore_errors=True)
        raise InstallError("INSTALL_FAILED", f"Could not unpack {package.path.name}: {e}", exit_codes.TECHNICAL)

    kept: List[str] = []
    if target.exists():
        try:
            _rename(target, old, retry_seconds, target)
        except InstallError:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        try:
            kept = _move_kept(old, staging)
            _rename(staging, target, retry_seconds, staging)
        except (InstallError, OSError) as e:
            # Put everything back as it was
            _move_kept(staging, old)
            os.rename(old, target)
            shutil.rmtree(staging, ignore_errors=True)
            if isinstance(e, InstallError):
                raise
            raise InstallError("INSTALL_FAILED", f"Could not install into {target}: {e}", exit_codes.TECHNICAL)
    else:
        os.rename(staging, target)

    replaced_folder = None
    if old.exists():
        if handmade:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            replaced_folder = packages_dir(package.name) / f"replaced-{stamp}"
            replaced_folder.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(replaced_folder))
        else:
            shutil.rmtree(old, ignore_errors=True)
    store_package(package, package.version)
    return InstallResult(package, target, "installed", previous_version=previous,
                         replaced_folder=replaced_folder, kept=kept)


def rollback_package(name: str, to_version: Optional[str], target_root: Optional[Path] = None) -> Path:
    """The stored package that `kinenix rollback` installs: --to's version, or the newest before the one in use."""
    root = Path(target_root) if target_root else flows_dir()
    deployed = read_deployed(root / name)
    if deployed is None:
        raise InstallError("NOT_DEPLOYED", f"{root / name} was not installed from a package, so there is "
                           f"nothing to roll back to.", exit_codes.NOT_FOUND)
    versions = stored_versions(name)
    current = str(deployed.get("version", ""))
    if to_version:
        chosen = to_version if to_version in versions else None
    else:
        older = [v for v in versions if version_key(current) and version_key(v) < version_key(current)]
        chosen = older[-1] if older else None
    if chosen is None:
        kept_list = ", ".join(versions) or "none"
        wanted = f"version {to_version}" if to_version else f"a version before {current}"
        raise InstallError("VERSION_NOT_FOUND", f"No stored package of {name} for {wanted}. Stored: {kept_list} "
                           f"(in {packages_dir(name)}).", exit_codes.NOT_FOUND)
    return packages_dir(name) / package_file_name(name, chosen)


def interactive() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()

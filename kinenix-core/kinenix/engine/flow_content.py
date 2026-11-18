"""The content of a flow under its `> Version:`, and whether it changed since that version was packed (#234).

`kinenix pack` (docs/design/flow-deploy.md, section 4) records in `.kinenix-packed.json` the hash of each
version it built. `kinenix validate` and `pack` compare the flow folder with it, so a flow that changed but
kept its version is caught before two machines run different flows under one number.

The content is every file a package holds: the bundle files, without the ones a package leaves out, and the
`@shared/` subflows the flow calls, recorded as `@shared/<path>` so the hash does not depend on how a package
lays them out. Text files are hashed with LF line ends, so a checkout with CRLF (git on Windows) is the same
content as one with LF.
"""
import fnmatch
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..models.flow import FlowDefinition, Step
from .requires import version_key

PACKED_FILE = ".kinenix-packed.json"
DEPLOYED_FILE = ".kinenix-deployed.json"
IGNORE_FILE = ".kinenixignore"
# Never in a package: secrets and machine settings, run results, tests, and Kinenix's own records
LEFT_OUT_DIRS = {"output", "logs", "tests", ".git", "__pycache__"}
MANIFEST_FILE = "kinenix-package.json"
SIGNATURE_FILE = "kinenix-package.sig"
PACKAGE_SUFFIX = ".kinx"
LEFT_OUT_FILES = {".env", "config/local.json", PACKED_FILE, DEPLOYED_FILE, IGNORE_FILE, MANIFEST_FILE, SIGNATURE_FILE}
SHARED_PREFIX = "@shared/"
CHANGED_LISTED = 5


class PackedRecordError(ValueError):
    """.kinenix-packed.json cannot be read."""


def version_problem(version: Optional[str]) -> Optional[str]:
    """None when `> Version:` is absent or in the form X.Y.Z (with aN, bN, or rcN); otherwise what is wrong."""
    if version is None:
        return None
    text = str(version).strip()
    parts = text.split(".")
    if (version_key(text) is None or len(parts) != 3 or text.lower().startswith("v")
            or ".dev" in text.lower()):
        return (f"'> Version: {version}' is not understood. Write it as X.Y.Z, such as `> Version: 1.3.0`, "
                f"or with a pre-release, such as 1.3.0b1.")
    return None


def _ignore_patterns(flow_dir: Path) -> List[str]:
    path = flow_dir / IGNORE_FILE
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return [line.strip().rstrip("/") for line in lines if line.strip() and not line.strip().startswith("#")]


def _left_out(rel: str, patterns: List[str]) -> bool:
    parts = rel.split("/")
    if rel in LEFT_OUT_FILES or any(part in LEFT_OUT_DIRS for part in parts[:-1]):
        return True
    if parts[-1].lower().endswith((PACKAGE_SUFFIX, PACKAGE_SUFFIX + ".part")):  # packages built into the folder
        return True
    # A pattern matches the whole path, the file name, or a folder on the way
    for pattern in patterns:
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(parts[-1], pattern):
            return True
        if any(fnmatch.fnmatch("/".join(parts[:i]), pattern) for i in range(1, len(parts))):
            return True
    return False


def bundle_files(flow_dir: Path) -> Dict[str, Path]:
    """The files of the bundle a package holds, by their path in the folder (with /)."""
    flow_dir = Path(flow_dir)
    patterns = _ignore_patterns(flow_dir)
    files: Dict[str, Path] = {}
    for path in sorted(flow_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(flow_dir).as_posix()
        if not _left_out(rel, patterns):
            files[rel] = path
    return files


def _flow_calls(steps: Optional[List[Step]]):
    for step in steps or []:
        if step.action == "flow.call":
            yield step.parameters.get("flow")
        yield from _flow_calls(step.sub_steps)
        yield from _flow_calls(step.else_steps)


def _all_calls(flow: FlowDefinition):
    for steps in (flow.steps, flow.on_error_steps, flow.finally_steps):
        yield from _flow_calls(steps)


def _shared_name(path: Path) -> str:
    parts = path.parts
    index = max(i for i, part in enumerate(parts) if part == "@shared")
    return SHARED_PREFIX + "/".join(parts[index + 1:])


def shared_files(flow: FlowDefinition, flow_dir: Path) -> Dict[str, Path]:
    """The @shared/ subflows the flow calls, also through its own subflows and other shared ones.
    Targets built from ${...} are not followed; validate reports targets that are not found."""
    from .interpreter import load_subflow, resolve_subflow_path
    from .validation import _BundleVariables

    found: Dict[str, Path] = {}
    seen: Set[Path] = set()
    pending = [(flow, Path(flow_dir), Path(flow_dir))]
    while pending:
        current, base_dir, file_dir = pending.pop()
        for target in _all_calls(current):
            if not isinstance(target, str) or "${" in target:
                continue
            try:
                path = resolve_subflow_path(target, _BundleVariables(base_dir, file_dir)).resolve()
            except FileNotFoundError:
                continue
            if path in seen:
                continue
            seen.add(path)
            shared = target.strip().startswith(SHARED_PREFIX) or "@shared" in path.parts
            if shared:
                found[_shared_name(path)] = path
            try:
                child = load_subflow(path)
            except (OSError, ValueError):  # nosec B112: validate reports a subflow it cannot read; its file still counts
                continue
            pending.append((child, path.parent if shared else base_dir, path.parent))
    return found


def _file_hash(path: Path) -> str:
    data = path.read_bytes()
    if b"\0" not in data:
        try:
            data.decode("utf-8")
            data = data.replace(b"\r\n", b"\n")
        except UnicodeDecodeError:
            pass  # not text: hashed as it is
    return hashlib.sha256(data).hexdigest()


def content_files(flow: FlowDefinition, flow_dir: Path) -> Dict[str, str]:
    """{path in the package: SHA-256} for every file that makes up this version of the flow."""
    files = {**bundle_files(flow_dir), **shared_files(flow, flow_dir)}
    return {name: _file_hash(path) for name, path in sorted(files.items())}


def content_hash(files: Dict[str, str]) -> str:
    listing = "".join(f"{digest}  {name}\n" for name, digest in sorted(files.items()))
    return "sha256:" + hashlib.sha256(listing.encode("utf-8")).hexdigest()


def read_packed(flow_dir: Path) -> Dict[str, Dict]:
    """{version: record} from .kinenix-packed.json; empty when the flow was never packed."""
    path = Path(flow_dir) / PACKED_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise PackedRecordError(f"{PACKED_FILE} is not valid JSON: {e}") from None
    versions = data.get("versions") if isinstance(data, dict) else None
    if not isinstance(versions, dict):
        raise PackedRecordError(f'{PACKED_FILE} must hold {{"versions": {{...}}}}, as kinenix pack writes it.')
    return {str(k): v for k, v in versions.items() if isinstance(v, dict)}


def record_packed(flow_dir: Path, version: str, files: Dict[str, str]) -> None:
    """Adds or replaces the record of one packed version (kinenix pack calls it after building)."""
    path = Path(flow_dir) / PACKED_FILE
    versions = read_packed(flow_dir)
    versions[version] = {"content": content_hash(files), "files": dict(sorted(files.items())),
                         "packed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    ordered = dict(sorted(versions.items(), key=lambda item: version_key(item[0]) or ((), (), ())))
    path.write_text(json.dumps({"versions": ordered}, indent=2) + "\n", encoding="utf-8")


def _changes(old: Dict[str, str], new: Dict[str, str]) -> str:
    changed = [name for name in new if name in old and old[name] != new[name]]
    added = [name for name in new if name not in old]
    removed = [name for name in old if name not in new]
    words = [f"{name} changed" for name in changed] + [f"{name} added" for name in added] + \
            [f"{name} removed" for name in removed]
    more = f", and {len(words) - CHANGED_LISTED} more" if len(words) > CHANGED_LISTED else ""
    return ", ".join(words[:CHANGED_LISTED]) + more


def changed_since_packed(flow: FlowDefinition, flow_dir: Path) -> Optional[str]:
    """What changed since this `> Version:` was packed, or None when it was not packed or nothing changed."""
    version = (flow.version or "").strip()
    if not version:
        return None
    record = read_packed(flow_dir).get(version)
    if not record:
        return None
    files = content_files(flow, flow_dir)
    if content_hash(files) == record.get("content"):
        return None
    old = record.get("files") if isinstance(record.get("files"), dict) else {}
    detail = _changes(old, files)
    return (f"The flow changed since version {version} was packed ({detail or 'see ' + PACKED_FILE}); "
            f"raise `> Version:` in flow.md before packing it again, so two machines never run different "
            f"flows under one version.")

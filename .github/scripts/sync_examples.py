"""Copy the example bundles that `kinenix init` offers into the kinenix package.

Usage:
    python .github/scripts/sync_examples.py           copy flows/examples/* into kinenix-core/kinenix/examples/
    python .github/scripts/sync_examples.py --check   report differences without writing (exit 1 when out of date)

flows/examples/ is the source. The package holds a copy because pip installs only what is inside the package.
Per example, the copy contains flow.md, README.md, requirements.md, AGENTS.md and CLAUDE.md when present, other config/*.json files, saved test pages, input files, the config template as config/config.json,
subflows/*.md, and input data in assets/ (screenshots and other outputs are left out).
"""
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "flows" / "examples"
TARGET = REPO_ROOT / "kinenix-core" / "kinenix" / "examples"
EXAMPLES = ("hello", "bot_fx_rate", "first_flow", "quote_requests")
ASSET_SUFFIXES = (".xlsx", ".xls", ".csv", ".txt", ".pdf")


def expected_files(name: str) -> Dict[str, Path]:
    """Packaged relative path -> source file, for one example."""
    src = SOURCE / name
    files = {
        "flow.md": src / "flow.md",
        "README.md": src / "README.md",
        "requirements.md": src / "requirements.md",
        "config/config.json": src / "config" / "config.template.json",
    }
    # Instructions for AI assistants, other settings files (config/empty.json of the tutorial), and saved pages for
    # testing. A tutorial's solution/ stays in the repository: in the reader's project, an AI assistant would find
    # it and copy it instead of building the flow
    for name in ("AGENTS.md", "CLAUDE.md"):
        if (src / name).is_file():
            files[name] = src / name
    # Package data skips dotfiles, so .env.example is packaged as env.example (scaffold.DOTFILE_NAMES restores it)
    if (src / ".env.example").is_file():
        files["env.example"] = src / ".env.example"
    for pattern in ("config/*.json", "tests/pages/*.html", "input/*.csv"):
        for path in sorted(src.glob(pattern)):
            rel = path.relative_to(src).as_posix()
            if rel not in ("config/config.json", "config/config.template.json"):
                files[rel] = path
    subflows = src / "subflows"
    if subflows.is_dir():
        for path in sorted(subflows.glob("*.md")):
            files[f"subflows/{path.name}"] = path
    assets = src / "assets"
    if assets.is_dir():
        for path in sorted(assets.iterdir()):
            if path.is_file() and path.suffix.lower() in ASSET_SUFFIXES:
                files[f"assets/{path.name}"] = path
    return files


def problems() -> List[str]:
    found = []
    for name in EXAMPLES:
        expected = expected_files(name)
        for rel, source in expected.items():
            if not source.is_file():
                found.append(f"{name}: source {source.relative_to(REPO_ROOT)} is missing")
                continue
            copy = TARGET / name / rel
            if not copy.is_file():
                found.append(f"{name}: {rel} is not in the package")
            elif copy.read_bytes() != source.read_bytes():
                found.append(f"{name}: {rel} differs from {source.relative_to(REPO_ROOT)}")
        extra_dir = TARGET / name
        if extra_dir.is_dir():
            for path in extra_dir.rglob("*"):
                rel = path.relative_to(extra_dir).as_posix()
                if path.is_file() and rel not in expected:
                    found.append(f"{name}: {rel} is in the package but not in the example")
    if TARGET.is_dir():
        for path in TARGET.iterdir():
            if path.is_dir() and path.name not in EXAMPLES and path.name != "__pycache__":
                found.append(f"{path.name}: packaged but not listed in EXAMPLES")
    return found


def sync() -> None:
    for name in EXAMPLES:
        target_dir = TARGET / name
        expected = expected_files(name)
        if target_dir.is_dir():
            for path in sorted(target_dir.rglob("*"), reverse=True):
                rel = path.relative_to(target_dir).as_posix()
                if path.is_file() and rel not in expected:
                    path.unlink()
                elif path.is_dir() and not any(path.iterdir()):
                    path.rmdir()  # a folder left empty would still be copied into new projects
        for rel, source in expected.items():
            copy = target_dir / rel
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(source.read_bytes())
        print(f"synced {name}: {len(expected)} files")


if __name__ == "__main__":
    if "--check" in sys.argv:
        issues = problems()
        for issue in issues:
            print("OUT OF DATE:", issue)
        if issues:
            print("Run: python .github/scripts/sync_examples.py")
        sys.exit(1 if issues else 0)
    sync()

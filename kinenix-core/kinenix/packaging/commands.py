"""The `kinenix publisher`, `kinenix pack`, and `kinenix trust` commands; cli.py parses and calls these.

Each returns an exit code (kinenix/exit_codes.py). None is an MCP tool: signing is a person's approval and
trust decides what a machine runs (docs/design/agent-interface.md, section 13).
"""
import sys
from pathlib import Path
from typing import Callable, List, Optional

from .. import exit_codes
from ..engine.flow_content import version_problem
from ..engine.markdown import load_flow
from . import trust
from .pack import SIZE_WARNING, PackError, build
from .signing import SigningError, check_name, create_key, default_name, private_key_path, read_public_key


def _err(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)


def publisher_init(name: Optional[str], force: bool, no_passphrase: bool) -> int:
    existing = read_public_key()
    if existing and not force:
        print(f"This machine already has a publisher key: {existing.comment} ({existing.key_id}).")
        print("`kinenix publisher show` prints it. `kinenix publisher init --force` makes a new one; every "
              "machine that trusts the old key must then trust the new one.")
        return exit_codes.OK
    try:
        name = check_name(name or (existing.comment.split()[0] if existing and existing.comment else default_name()))
        interactive = not no_passphrase and sys.stdin is not None and sys.stdin.isatty()
        if interactive:
            print("ssh-keygen asks for a passphrase for the key. Press Enter twice for none; with one, "
                  "kinenix pack asks for it each time.")
        old_id = existing.key_id if existing else None
        key = create_key(name, passphrase_prompt=interactive)
        if old_id:
            try:
                trust.remove(old_id)
            except trust.TrustError:
                pass  # the old key was not trusted here
        trust.add(key.line, name, replace=True)
    except (SigningError, trust.TrustError) as e:
        _err(str(e))
        return exit_codes.TECHNICAL
    print(f"Created the publisher key '{name}' ({key.key_id}).")
    print(f"Private key: {private_key_path()} (keep it on this machine; never copy it to the Hub or a worker)")
    print("This machine now trusts it, so it can install its own packages.")
    _print_trust_hint(key.line, name)
    return exit_codes.OK


def _print_trust_hint(line: str, name: str) -> None:
    print()
    print("On each machine that should install packages from here, run:")
    print(f'  kinenix trust add "{line}" --name {name}')


def publisher_show() -> int:
    try:
        key = read_public_key()
    except SigningError as e:
        _err(str(e))
        return exit_codes.TECHNICAL
    if key is None:
        _err("This machine has no publisher key. Run `kinenix publisher init` first.")
        return exit_codes.NOT_FOUND
    name = key.comment.split()[0] if key.comment else default_name()
    print(f"Name:   {name}")
    print(f"Key id: {key.key_id}")
    print(f"Public key (safe to share):\n{key.line}")
    _print_trust_hint(key.line, name)
    return exit_codes.OK


def pack(flow_input: str, version: Optional[str], output: Optional[str],
         resolve: Callable[[str], Optional[Path]], report: Callable[..., List[str]]) -> int:
    """resolve and report are cli.resolve_flow_path and cli.report_validation."""
    path = resolve(flow_input)
    if path is None:
        _err(f"Could not find flow '{flow_input}'.")
        return exit_codes.NOT_FOUND
    if path.name.lower() != "flow.md":
        _err(f"{path} is a single flow file; kinenix pack builds a flow folder with a flow.md "
             f"(kinenix init makes one).")
        return exit_codes.USAGE
    try:
        flow = load_flow(path)
    except Exception as e:
        _err(f"Could not load {path}: {e}")
        return exit_codes.INVALID_FLOW
    version = (version or flow.version or "").strip()
    if not version:
        _err("The flow has no version. Add `> Version: 1.0.0` under the title of flow.md, or pass --version.")
        return exit_codes.USAGE
    problem = version_problem(version)
    if problem:
        _err(problem)
        return exit_codes.USAGE
    flow = flow.model_copy(update={"version": version})

    issues = report(flow, md_path=path, check_packed=True)
    if issues:
        _err(f"{len(issues)} problem(s) in {path}; fix them before packing (kinenix validate shows them).")
        return exit_codes.INVALID_FLOW
    try:
        result = build(flow, path.parent, version, Path(output) if output else Path.cwd())
    except SigningError as e:
        _err(str(e))
        return exit_codes.TECHNICAL
    except (PackError, OSError) as e:
        _err(str(e))
        return exit_codes.TECHNICAL

    files = result.manifest["files"]
    print(f"Packed {len(files)} files:")
    for rel in files:
        print(f"  {rel}")
    for rel in result.secret_like:
        print(f"Warning: {rel} looks like it may hold a secret, and it is in the package. Move secrets to "
              f".env, or list the file in .kinenixignore.", file=sys.stderr)
    if result.size > SIZE_WARNING:
        print(f"Warning: the package is {result.size / 1024 / 1024:.0f} MB; the Hub accepts 50 MB by default.",
              file=sys.stderr)
    publisher = result.manifest["publisher"]
    print(f"Signed by {publisher['name']} ({publisher['key_id']}).")
    print(f"Recorded version {version} in .kinenix-packed.json; keep that file in git.")
    print(f"Package: {result.path}")
    return exit_codes.OK


def trust_add(key_text: Optional[str], name: Optional[str]) -> int:
    if not key_text:
        _err('Give the public key: kinenix trust add "ssh-ed25519 AAAA... name" --name office-pc '
             '(kinenix publisher show prints it on the building machine).')
        return exit_codes.USAGE
    try:
        publisher = trust.add(key_text, name)
    except (SigningError, trust.TrustError) as e:
        _err(str(e))
        return exit_codes.USAGE
    print(f"This machine now trusts packages signed by '{publisher.name}' ({publisher.key_id}).")
    return exit_codes.OK


def trust_list() -> int:
    try:
        publishers = trust.load()
        own = read_public_key()
    except (SigningError, trust.TrustError) as e:
        _err(str(e))
        return exit_codes.TECHNICAL
    if not publishers:
        print("No trusted publishers. `kinenix trust add` adds one; `kinenix publisher init` trusts this "
              "machine's own key.")
        return exit_codes.OK
    width = max(len(p.name) for p in publishers)
    for p in publishers:
        mark = "  (this machine)" if own and own.key_id == p.key_id else ""
        print(f"{p.name.ljust(width)}  {p.key_id}{mark}")
    print(f"\nFile: {trust.trust_file()}")
    return exit_codes.OK


def trust_remove(target: Optional[str]) -> int:
    if not target:
        _err("Give the name or key id to remove, as `kinenix trust list` shows it.")
        return exit_codes.USAGE
    try:
        publisher = trust.remove(target)
    except trust.TrustError as e:
        _err(str(e))
        return exit_codes.NOT_FOUND
    print(f"Removed '{publisher.name}' ({publisher.key_id}); packages it signs are no longer installed here.")
    return exit_codes.OK

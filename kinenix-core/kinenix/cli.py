import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import __version__, exit_codes
from .models.context import local_now
from .models.flow import FlowDefinition
from .engine.interpreter import FlowInterpreter, new_run_id
from .engine.logger import ExecutionLogger
from .engine.markdown import (
    export_json_to_markdown,
    flow_to_json_text,
    load_flow,
    markdown_issues,
)
from .engine.stopping import install_signal_handlers
from .engine.validation import deprecated_uses, leftover_json_flows, validate_flow, validate_subflows
from .scaffold import (
    DEFAULT_EXAMPLE,
    EXAMPLES_DIR,
    NEW_PROJECT_TEMPLATE,
    available_examples,
    create_new_project,
    create_project,
    project_folder_name,
    update_agent_instructions,
)
from .workspace import (
    configured_flows_dir,
    ensure_flows_dir,
    flows_dir,
    prepare_flows_dir,
    save_flows_dir,
    settings_file as workspace_settings_file,
)


def override_config(name: str, flow_dir: Path) -> Dict[str, Any]:
    """The settings of `kinenix run --config FILE`: a JSON object, found as given or in the flow's folder (#106)."""
    candidates = [Path(name), flow_dir / name]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise FileNotFoundError(f"--config: '{name}' was not found (looked in the current folder and in {flow_dir}).")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        raise ValueError(f"--config: {path} is not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise ValueError(f"--config: {path} must hold a JSON object of settings, like config/config.json.")
    return data


def report_validation(flow: FlowDefinition, md_path: Optional[Path] = None) -> List[str]:
    """Print validation problems as warnings and return them; with md_path, also lines flow.md ignores
    and problems in the subflows of that bundle."""
    issues = []
    if md_path is not None and md_path.suffix.lower() == ".md" and md_path.is_file():
        issues.extend(markdown_issues(md_path.read_text(encoding="utf-8-sig")))
    issues.extend(validate_flow(flow))
    if md_path is not None:
        issues.extend(validate_subflows(flow, md_path.parent))
        issues.extend(leftover_json_flows(md_path))
    for issue in issues:
        print(f"Warning: {issue}", file=sys.stderr)
    return issues


def _get_project_root() -> Optional[Path]:
    curr = Path.cwd().resolve()
    for p in [curr] + list(curr.parents):
        if (p / ".git").exists() or (p / "kinenix-core").is_dir():
            return p
    return None


def _get_search_directories() -> List[Path]:
    dirs = [
        Path.cwd(),
        flows_dir(),  # the user's flows folder (KINENIX_FLOWS_DIR, saved setting, or ~/kinenix-flows)
        Path.cwd() / "flows",
        Path.cwd() / "examples",
        Path.home() / ".kinenix" / "flows",
    ]
    root = _get_project_root()
    if root:
        dirs.insert(1, root / "flows")
        dirs.append(root / "examples")

    unique_dirs = []
    seen = set()
    for d in dirs:
        if d.exists() and d.resolve() not in seen:
            seen.add(d.resolve())
            unique_dirs.append(d.resolve())
    return unique_dirs


def discover_flows() -> Dict[str, Tuple[Path, str]]:
    """
    Discovers flows across search directories: bundles, that is folders with a flow.md (#108).
    A single .md file is not listed; it runs by its path. Returns dict mapping alias to (file_path, name).
    """
    discovered: Dict[str, Tuple[Path, str]] = {}

    for search_dir in _get_search_directories():
        # 1. Discover Self-Contained Project Bundles (directories with a flow.md)
        for flow_file in search_dir.glob("**/flow.md"):
            parts = flow_file.parts
            if any(p.startswith(".") or p in ["__pycache__", "subflows", "solution", "node_modules", ".venv", "venv"] for p in parts):
                continue
            # The templates for `kinenix init` are not runnable projects; running one would write into the package
            if EXAMPLES_DIR in flow_file.resolve().parents or NEW_PROJECT_TEMPLATE in flow_file.resolve().parents:
                continue
            alias = flow_file.parent.name
            if alias in discovered:
                continue
            try:
                flow_def = load_flow(flow_file)
                name = flow_def.name or alias
                discovered[alias] = (flow_file, name)

                try:
                    rel = flow_file.parent.relative_to(search_dir)
                    rel_str = str(rel).replace("\\", "/")
                    # The bundle is the search directory itself (the current folder): "." is not a name
                    if rel_str not in ("", ".") and rel_str != alias and rel_str not in discovered:
                        discovered[rel_str] = (flow_file, name)
                except ValueError:
                    pass
            except Exception:  # nosec B112: a folder that cannot be read is left out of the list
                continue
    return discovered


def resolve_flow_path(flow_input: str) -> Optional[Path]:
    """
    Smart Flow Resolver: resolves a flow name, alias, project directory, or path into an absolute file path.
    Flows are flow.md files; a folder that only has a flow.json resolves to it, so loading it explains
    how to convert it.
    """
    direct_path = Path(flow_input)
    # 1. Exact file path
    if direct_path.is_file():
        return direct_path.resolve()

    # 2. Directory with flow.md (or only a flow.json, to be converted)
    if direct_path.is_dir():
        for name in ("flow.md", "flow.json"):
            if (direct_path / name).is_file():
                return (direct_path / name).resolve()

    # 3. Direct path without the .md extension
    p = Path(f"{flow_input}.md")
    if p.is_file():
        return p.resolve()

    # 4. Search discovered flows
    flows = discover_flows()
    if flow_input in flows:
        return flows[flow_input][0].resolve()

    # 5. Search directories for project bundles or files
    for search_dir in _get_search_directories():
        candidates = [
            search_dir / flow_input / "flow.md",
            search_dir / flow_input,
            search_dir / f"{flow_input}.md",
        ]
        for c in candidates:
            if c.is_file():
                return c.resolve()
            if c.is_dir() and (c / "flow.md").is_file():
                return (c / "flow.md").resolve()

        for matched in search_dir.glob(f"**/{flow_input}/flow.md"):
            if matched.is_file():
                return matched.resolve()

    return None


def main():
    parser = argparse.ArgumentParser(prog="kinenix", description="kinenix - Enterprise RPA CLI Runner")
    parser.add_argument("-v", "--version", action="version", version=f"kinenix {__version__}")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Run an RPA Flow by name or path (e.g. 'kinenix run rpachallenge')")
    run_parser.add_argument("flow_file", help="Flow name, bundle folder, or path to a flow.md file")
    run_parser.add_argument("--vars", help="Optional JSON string of variables to override", default=None)
    run_parser.add_argument("--config", dest="config_file", default=None,
                            help="A JSON file whose keys replace the same keys of config/config.json for this run, "
                                 "for example config/test.json pointing to saved pages (relative to the flow's folder)")
    run_parser.add_argument("--log-dir", help="Directory to save execution JSON logs (default: auto-detected project root 'logs/')", default=None)
    run_parser.add_argument("--hub", "--orchestrator", dest="hub", help="Optional Hub URL to transmit telemetry (e.g. http://localhost:8080); --orchestrator is the name from before the rename to Hub", default=None)
    run_parser.add_argument("--worker-id", help="Identifier for this worker node (default: local-worker)", default=None)

    # Command: init
    init_parser = subparsers.add_parser(
        "init", help="Create a project for a new task (kinenix init \"Get stock data\"), or copy an example (--example)")
    init_parser.add_argument("name", nargs="?", default=None,
                             help="Task name, e.g. \"Get stock data\"; the folder becomes get_stock_data")
    init_parser.add_argument("--dir", default=None, help="Folder to create instead of the one derived from the name")
    init_parser.add_argument("--example", "-e", default=None,
                             help="Copy a complete example instead of starting a new task; see --list")
    init_parser.add_argument("--list", action="store_true", help="List the available examples")
    init_parser.add_argument("--update-agents", action="store_true",
                             help="Rewrite AGENTS.md and CLAUDE.md of an existing project (NAME is its folder or "
                                  "flow name; default: the current folder) from the current template")

    # Command: flows-dir
    flows_dir_parser = subparsers.add_parser("flows-dir", help="Show or set the folder where your flows are kept")
    flows_dir_parser.add_argument("path", nargs="?", default=None, help="New flows folder to remember")

    # Command: actions
    actions_parser = subparsers.add_parser("actions", help="List every action and the parameters it accepts")
    actions_parser.add_argument("filter", nargs="?", default=None, help="Only actions starting with this, e.g. web or csv.write")

    # Command: compile
    compile_parser = subparsers.add_parser(
        "compile", help="Show the compiled form of a flow.md as JSON (for inspection; Kinenix runs flow.md itself)")
    compile_parser.add_argument("markdown_file", help="Path to flow.md file or project directory containing flow.md")
    compile_parser.add_argument("-o", "--output", help="Write the JSON to this file instead of printing it", default=None)
    compile_parser.add_argument("--strict", action="store_true", help="Exit with code 1 when validation finds problems (for CI)")

    # Command: validate
    validate_parser = subparsers.add_parser("validate", help="Check a flow for unknown actions and parameters that would be ignored")
    validate_parser.add_argument("flow_file", help="Flow name, bundle directory, or flow.md")

    # Command: export-md
    export_parser = subparsers.add_parser(
        "export-md", help="Convert a flow.json from Kinenix 0.2.0b3 or older into flow.md (once)")
    export_parser.add_argument("json_file", help="Path to flow.json file or project directory containing flow.json")
    export_parser.add_argument("-o", "--output", help="Optional output flow.md path", default=None)

    # Command: list
    subparsers.add_parser("list", help="List all discovered RPA Flows available to run")

    # Command: hub
    # "orchestrator" is the name from before the rename to Hub and still works as an alias
    hub_parser = subparsers.add_parser("hub", aliases=["orchestrator"], help="Start the Kinenix Hub, set it up, or show its workers and executions")
    hub_parser.add_argument("action", nargs="?", choices=["start", "status", "logs", "report", "query", "setup", "show-key"], default="start",
                             help="'start' runs the server (default; asks setup questions on first run); "
                                  "'status' shows workers and recent executions of a running server; "
                                  "'logs [ID]' shows the steps of one execution (latest when ID is omitted; --flow NAME for a flow's latest); "
                                  "'report [ID]' shows the short report of the latest run (--flow NAME, --limit N for more); "
                                  "'query' reads runs, steps, and failures (read-only; see --list); "
                                  "'setup' changes the saved settings; 'show-key' prints the worker API key")
    hub_parser.add_argument("target", nargs="?", default=None,
                             help="For 'logs' and 'report': execution ID or its first characters, as shown by 'status'. "
                                  "For 'query': a view or table name (v_failures), or one SQL SELECT in quotes")
    hub_parser.add_argument("--url", default=None,
                             help="Hub URL for 'status' and 'logs' (default: http://127.0.0.1:<port>); "
                                  "for 'query', ask that Hub instead of reading hub.db on this machine")
    hub_parser.add_argument("--limit", type=int, default=None,
                             help="Recent executions shown by 'status' (default: 10); reports shown by 'report' (default: 1); "
                                  "rows returned by 'query' (default: 50)")
    query_options = hub_parser.add_argument_group("query options")
    query_options.add_argument("--list", action="store_true", help="List tables and views, their row counts, and what they answer")
    query_options.add_argument("--describe", metavar="NAME", default=None, help="Show the columns of a table or view and what they mean")
    query_options.add_argument("--since", default=None, help="Only rows from this time: today, yesterday, 30m, 12h, 7d, 2w, or a date (2026-10-12)")
    query_options.add_argument("--flow", default=None,
                               help="'logs' and 'report': the latest run of this flow (exact name or part of it); "
                                    "'query': only rows of this flow (flow_name)")
    query_options.add_argument("--worker", default=None, help="Only rows of this worker (worker_id)")
    query_options.add_argument("--status", default=None, help="Only rows with this status (success, failed, skipped)")
    query_options.add_argument("--filter", action="append", metavar="COLUMN=VALUE", help="Only rows where a column has this value; repeat for more")
    query_options.add_argument("--format", choices=["table", "json", "csv", "md"], default="table", help="Output format (default: table)")
    query_options.add_argument("--output", metavar="FILE", default=None, help="Write the rows to a file instead of the screen")
    query_options.add_argument("--expand", action="store_true", help="Show whole values, and details columns as JSON objects")
    hub_parser.add_argument("--no-prompt", action="store_true", help="Never ask questions (for services and scripts); use the environment and saved settings only")
    hub_parser.add_argument("--port", type=int, default=None, help="Port to bind the hub server (default: $KINENIX_HUB_PORT or 8080)")
    hub_parser.add_argument("--host", default=None, help="Host to bind the hub server (default: $KINENIX_HUB_HOST or 127.0.0.1; use 0.0.0.0 to accept remote connections)")

    # Command: connect
    connect_parser = subparsers.add_parser(
        "connect", help="Send runs and worker heartbeats from this machine to a Hub (saved in ~/.kinenix/kinenix.env)")
    connect_parser.add_argument("url", nargs="?", default=None,
                                help="Hub address, e.g. http://192.168.1.137:8080 or 192.168.1.137 (port 8080 when omitted); "
                                     "without it, shows the Hub in use")
    connect_parser.add_argument("--key", default=None,
                                help="Worker API key (asked when omitted; on the Hub, `kinenix hub show-key` prints it)")
    connect_parser.add_argument("--off", action="store_true", help="Stop sending runs to a Hub")
    connect_parser.add_argument("--no-check", action="store_true", help="Save without checking that the Hub answers")

    # Command: version
    subparsers.add_parser("version", help="Show kinenix version and environment details")

    # Command: install-browsers
    subparsers.add_parser("install-browsers", help="Download and install Playwright Chromium browser")

    args, extras = parser.parse_known_args()
    # argparse cannot read a positional after options that follow another positional
    # (`kinenix hub query --url URL "SELECT ..."`), so the one left over is the target
    if (extras and getattr(args, "command", None) in ("hub", "orchestrator") and args.target is None
            and len(extras) == 1 and not extras[0].startswith("-")):
        args.target, extras = extras[0], []
    if extras:
        parser.error(f"unrecognized arguments: {' '.join(extras)}")

    if args.command == "version":
        print(f"Kinenix:      v{__version__}")
        print(f"Python:       {platform.python_version()} ({platform.python_implementation()})")
        print(f"Platform:     {platform.system()} {platform.release()} ({platform.machine()})")
        sys.exit(0)

    elif args.command == "install-browsers":
        import subprocess  # nosec B404: runs only the fixed install command below
        print("Installing Playwright Chromium browser for kinenix...")
        res = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])  # nosec B603: fixed arguments
        if res.returncode == 0:
            print("Chromium browser successfully installed.")
        else:
            print("Installation failed. On Linux/Raspberry Pi, you may also need: sudo playwright install-deps chromium", file=sys.stderr)
        sys.exit(res.returncode)

    elif args.command == "init":
        examples = available_examples()
        if args.list:
            print("Examples (kinenix init <folder> --example <name>):\n")
            for name, description, needs_browser in examples:
                # Examples with their pages saved in tests/pages run without internet
                offline = (EXAMPLES_DIR / name / "tests" / "pages").is_dir()
                note = ("  [needs a browser; runs offline]" if offline else "  [needs a browser and internet]")                     if needs_browser else ""
                print(f"  {name:<16}{description}{note}")
            print('\nFor a new task of your own: kinenix init "Task name"')
            sys.exit(0)

        if args.update_agents:
            # An existing project: its folder, a flow name, or the current folder
            found = resolve_flow_path(args.name) if args.name else None
            project = found.parent if found else Path(args.name or ".")
            try:
                written = update_agent_instructions(project)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(exit_codes.NOT_FOUND)
            if not written:
                print(f"AGENTS.md and CLAUDE.md in {project.resolve()} are already current.")
            for path in written:
                print(f"Updated {path}")
            if (project / "AGENTS.md.bak").is_file() and written:
                print("The previous AGENTS.md is in AGENTS.md.bak; copy back anything specific to this project.")
            sys.exit(0)

        if not args.example and not args.name:
            print('Error: give the task a name, for example: kinenix init "Get stock data"', file=sys.stderr)
            print(f"       or copy a complete example: kinenix init --example {DEFAULT_EXAMPLE}  (see --list)",
                  file=sys.stderr)
            sys.exit(exit_codes.USAGE)

        # Projects go into the flows folder (asked the first time), unless --dir names a folder
        base = None if args.dir else ensure_flows_dir(interactive=sys.stdin.isatty())
        try:
            if args.example:
                # With an example, the positional argument is the folder name, used as typed (my-bot stays my-bot)
                target = Path(args.dir) if args.dir else base / (args.name or args.example)
                created = create_project(target, args.example)
            else:
                target = Path(args.dir) if args.dir else base / project_folder_name(args.name)
                created = create_new_project(args.name, target)
        except ValueError as e:  # an unknown example, or a name that gives no folder name
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(exit_codes.NOT_FOUND if "Unknown example" in str(e) else exit_codes.USAGE)
        except FileExistsError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(exit_codes.USAGE)

        # Inside the flows folder a flow runs by its folder name from anywhere; elsewhere use its path
        run_name = created.name if base and created.parent == base.resolve() else str(created)
        print(f"Created {created}" + (f" from the '{args.example}' example." if args.example
                                      else f" for '{args.name.strip()}'.") + "\n")
        print("Next steps:")
        if args.example:
            if next((nb for name, _, nb in examples if name == args.example), False):
                print("  kinenix install-browsers        # once per machine; this example drives a web browser")
            print(f"  kinenix run {run_name}")
            print(f"  Edit flow.md (the flow) and config/config.json (its values) in {created}; see its README.md")
        else:
            print(f"  1. Describe the task in {created / 'requirements.md'}")
            print(f"  2. Open {created} in your AI assistant and ask it to build the flow from requirements.md")
            print("     (it follows AGENTS.md; or write flow.md yourself)")
            print(f"  3. kinenix validate {run_name}")
            print(f"  4. kinenix run {run_name}")
        sys.exit(0)

    elif args.command == "flows-dir":
        if args.path:
            path = prepare_flows_dir(Path(args.path), use_git=False)
            save_flows_dir(path)
            print(f"Flows folder set to {path} (saved in {workspace_settings_file()}).")
            if os.environ.get("KINENIX_FLOWS_DIR"):
                print("Note: KINENIX_FLOWS_DIR is set in the environment and takes precedence over this setting.")
            sys.exit(0)
        chosen = configured_flows_dir()
        source = ("KINENIX_FLOWS_DIR" if os.environ.get("KINENIX_FLOWS_DIR")
                  else f"saved in {workspace_settings_file()}" if chosen else "default; not chosen yet")
        print(f"{flows_dir()}  ({source})")
        sys.exit(0)

    elif args.command == "actions":
        from .actions.registry import ActionRegistry
        from . import actions as _all_actions  # noqa: F401  (registers every action)

        names = sorted(n for n in ActionRegistry.list_actions() if not args.filter or n.startswith(args.filter))
        if not names:
            print(f"No action starts with '{args.filter}'.", file=sys.stderr)
            sys.exit(exit_codes.NOT_FOUND)
        width = max(len(n) for n in names) + 2
        print("Actions and the parameters they accept (details: docs/actions_reference.md)")
        print("[...] is what the action can do outside the run: email, files, web, network\n")
        for name in names:
            action = ActionRegistry.get(name)
            params = action.accepted_parameters
            listed = ", ".join(params) if params else "(none)"
            effects = [kind for kind in (action.side_effects or ()) if kind != "none"]
            marker = f"  [{', '.join(effects)}]" if effects else ""
            print(f"  {name:<{width}}{listed}{marker}")
        print("\nEvery step also accepts: description, output_var, condition, on_error, max_retries, retry_interval, fallback_step_id")
        sys.exit(0)

    elif args.command == "validate":
        resolved_path = resolve_flow_path(args.flow_file)
        if not resolved_path:
            print(f"Error: Could not find flow '{args.flow_file}'.", file=sys.stderr)
            sys.exit(exit_codes.NOT_FOUND)
        source = resolved_path
        try:
            flow_def = load_flow(source)
        except Exception as e:
            print(f"Error loading flow at '{source}': {e}", file=sys.stderr)
            sys.exit(exit_codes.INVALID_FLOW)
        issues = report_validation(flow_def, md_path=source)
        for notice in deprecated_uses(flow_def):  # still runs in 1.x, so not counted as a problem
            print(f"Deprecated: {notice}", file=sys.stderr)
        if issues:
            print(f"{len(issues)} problem(s) in {source}", file=sys.stderr)
            sys.exit(exit_codes.INVALID_FLOW)
        print(f"OK: {source} ({flow_def.name})")
        sys.exit(0)

    elif args.command == "compile":
        src = Path(args.markdown_file).resolve()
        if src.is_dir() and (src / "flow.md").is_file():
            src = src / "flow.md"
        if not src.is_file():
            print(f"Error: Markdown flow file not found at: {src}", file=sys.stderr)
            sys.exit(exit_codes.NOT_FOUND)
        try:
            flow_def = load_flow(src)
            text = flow_to_json_text(flow_def)
            if args.output:
                out = Path(args.output).resolve()
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                print(f"Compiled {src} -> {out}", file=sys.stderr)
            else:
                sys.stdout.write(text)
            issues = report_validation(flow_def, md_path=src)
            sys.exit(exit_codes.INVALID_FLOW if issues and args.strict else exit_codes.OK)
        except Exception as e:
            print(f"Compilation error: {e}", file=sys.stderr)
            sys.exit(exit_codes.INVALID_FLOW)

    elif args.command == "export-md":
        print("Deprecated: kinenix export-md will be removed in Kinenix 2.0; convert any flow.json left from "
              "0.2.0b3 or older with Kinenix 1.x first.", file=sys.stderr)
        src = Path(args.json_file).resolve()
        if src.is_dir() and (src / "flow.json").is_file():
            src = src / "flow.json"
        if not src.is_file():
            print(f"Error: JSON flow file not found at: {src}", file=sys.stderr)
            sys.exit(exit_codes.NOT_FOUND)
        out = Path(args.output).resolve() if args.output else None
        try:
            target = export_json_to_markdown(src, output_md_path=out)
            print(f"Successfully exported: {src}")
            print(f"Output saved to:       {target}")
            sys.exit(0)
        except Exception as e:
            print(f"Export error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "list":
        flows = discover_flows()
        if not flows:
            print(f"No flows found in the flows folder ({flows_dir()}) or the current directory.")
            print("Tip: You can specify the path of a bundle folder or flow.md: kinenix run <path>")
            sys.exit(0)

        # Deduplicate by resolved file path so the same flow isn't printed multiple times for different aliases
        unique_flows: Dict[Path, Tuple[str, str, List[str]]] = {}
        for alias, (path, name) in flows.items():
            resolved = path.resolve()
            if resolved not in unique_flows:
                unique_flows[resolved] = (alias, name, [alias])
            else:
                unique_flows[resolved][2].append(alias)

        print("\nAvailable Flows in kinenix:")
        print("-" * 80)
        for path, (primary_alias, name, all_aliases) in sorted(
            unique_flows.items(), key=lambda item: min(item[1][2], key=len)
        ):
            clean_alias = min(all_aliases, key=len)
            print(f"  {clean_alias:<18} | {name:<35} | {path}")
        print("-" * 80)
        print("To run a flow: kinenix run <flow_name>\n")
        sys.exit(0)

    elif args.command == "run":
        if any(a == "--orchestrator" or a.startswith("--orchestrator=") for a in sys.argv[1:]):
            print("Deprecated: --orchestrator is now --hub; the old name will be removed in Kinenix 2.0.", file=sys.stderr)
        resolved_path = resolve_flow_path(args.flow_file)
        if not resolved_path:
            print(f"Error: Could not find flow '{args.flow_file}'.", file=sys.stderr)
            flows = discover_flows()
            if flows:
                print("\nAvailable flows you can run:", file=sys.stderr)
                for alias, (_, name) in sorted(flows.items()):
                    print(f"  - {alias:<16} ({name})", file=sys.stderr)
            print("\nTip: You can also give the path of a bundle folder or flow.md: kinenix run <path>", file=sys.stderr)
            sys.exit(exit_codes.NOT_FOUND)

        try:
            flow_def = load_flow(resolved_path)
        except Exception as e:
            print(f"Error loading flow at '{resolved_path}': {str(e)}", file=sys.stderr)
            sys.exit(exit_codes.INVALID_FLOW)

        extra_vars = {}
        if args.vars:
            try:
                extra_vars = json.loads(args.vars)
            except Exception as e:
                print(f"Error parsing --vars JSON: {str(e)}", file=sys.stderr)
                sys.exit(exit_codes.USAGE)

        if args.config_file:
            try:
                extra_vars["config"] = {**override_config(args.config_file, resolved_path.parent),
                                        **(extra_vars.get("config") or {})}
            except FileNotFoundError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(exit_codes.NOT_FOUND)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(exit_codes.USAGE)

        # The first line of every run names it, so a person, a script, or an agent can ask about it later
        run_id = new_run_id(local_now())
        print(f"Run {run_id}", flush=True)
        extra_vars["__run_id__"] = run_id

        report_validation(flow_def, md_path=resolved_path)
        if not flow_def.steps:
            print(f"Error: {resolved_path} has no steps, so there is nothing to run.", file=sys.stderr)
            sys.exit(exit_codes.INVALID_FLOW)

        extra_vars["__flow_dir__"] = str(resolved_path.parent)
        if args.hub:
            extra_vars["hub_url"] = args.hub
        if args.worker_id:
            extra_vars["worker_id"] = args.worker_id

        logger = ExecutionLogger(log_dir=args.log_dir, flow_path=resolved_path)
        interpreter = FlowInterpreter(logger=logger)
        install_signal_handlers()
        try:
            context = interpreter.run_flow(flow_def, initial_vars=extra_vars)
        except KeyboardInterrupt:
            print("\nStopped (Ctrl+C).", file=sys.stderr)
            sys.exit(exit_codes.INTERRUPTED)
        sys.exit(exit_codes.for_run(context))

    elif args.command == "connect":
        from . import connect
        if args.off:
            sys.exit(connect.disconnect())
        if not args.url:
            sys.exit(connect.show())
        key = args.key
        if key is None and sys.stdin is not None and sys.stdin.isatty():
            import getpass
            key = getpass.getpass("Worker API key (Enter if the Hub has none): ").strip()
        sys.exit(connect.connect(args.url, key or None, verify=not args.no_check))

    elif args.command in ("hub", "orchestrator"):
        if args.command == "orchestrator":
            print("Deprecated: 'kinenix orchestrator' is now 'kinenix hub'; the old name will be removed in Kinenix 2.0.", file=sys.stderr)
        try:
            from rich.console import Console
            from kinenix_hub import config as hub_config
            from kinenix_hub import console as hub_console
        except ImportError as e:
            print(f"Error: the Hub is not installed ({e}).")
            print("Install it with: pip install -e kinenix-hub")
            sys.exit(1)
        import importlib
        console = Console()
        interactive = hub_console.can_prompt() and not args.no_prompt

        # First start: ask the setup questions once and save them to the settings file
        first_run = args.action == "start" and not hub_config.settings_exist() and interactive
        if args.action == "setup" or first_run:
            if not hub_console.can_prompt():
                console.print("[bold red]Error:[/] setup needs an interactive terminal.")
                sys.exit(exit_codes.USAGE)
            try:
                hub_console.run_setup(console, hub_config.SETTINGS_FILE)
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Setup cancelled. Nothing was saved.[/]")
                sys.exit(exit_codes.INTERRUPTED)
            importlib.reload(hub_config)
            if args.action == "setup":
                console.print("Start the Hub with: [bold]kinenix hub[/]")
                sys.exit(0)

        if args.action == "show-key":
            if not hub_config.API_KEY:
                console.print("No worker API key is set. Create one with: [bold]kinenix hub setup[/]")
                sys.exit(exit_codes.NOT_FOUND)
            console.print(hub_config.API_KEY, soft_wrap=True)
            # The key alone goes to standard output, so `$(kinenix hub show-key)` keeps working
            urls = hub_console.browser_urls(args.host or hub_config.HOST, args.port or hub_config.PORT)
            Console(stderr=True).print(f"[dim]On a worker: kinenix connect {urls[-1]} --key <this key>[/]")
            sys.exit(0)

        port = args.port or hub_config.PORT

        if args.action in ("query", "report"):
            from kinenix_hub import query_console
            command = query_console.report_command if args.action == "report" else None
            sys.exit(query_console.main(console, Console(stderr=True), args, hub_config, interactive, command))

        if args.action in ("status", "logs"):
            import requests
            url = args.url or f"http://127.0.0.1:{port}"
            # Same credentials the server reads; unset password works only against a localhost server
            auth = (hub_config.DASHBOARD_USER, hub_config.DASHBOARD_PASSWORD) if hub_config.DASHBOARD_PASSWORD else None
            while True:
                try:
                    with console.status(f"Reading {url}..."):
                        if args.action == "status":
                            data = hub_console.fetch_status(url, auth, args.limit or 10)
                        else:
                            data = hub_console.fetch_execution_log(url, auth, args.target, args.flow)
                    break
                except LookupError as e:
                    console.print(f"[bold red]Error:[/] {e}")
                    sys.exit(exit_codes.NOT_FOUND)
                except requests.HTTPError as e:
                    code = e.response.status_code
                    # Ask once for the password when the server requires one and none was given
                    if code == 401 and auth is None and interactive:
                        password = hub_console.ask_secret(console, f"Dashboard password for '{hub_config.DASHBOARD_USER}'")
                        if password:
                            auth = (hub_config.DASHBOARD_USER, password)
                            continue
                    hint = " Check KINENIX_HUB_DASHBOARD_USER and KINENIX_HUB_DASHBOARD_PASSWORD against the server's values." if code in (401, 403) else ""
                    console.print(f"[bold red]Error:[/] {url} returned HTTP {code}.{hint}")
                    sys.exit(exit_codes.UNREACHABLE if code in (401, 403) else
                             exit_codes.NOT_FOUND if code == 404 else exit_codes.TECHNICAL)
                except requests.RequestException as e:
                    console.print(f"[bold red]Error:[/] cannot reach {url}. Is the Hub running? ({e.__class__.__name__})")
                    sys.exit(exit_codes.UNREACHABLE)
            if args.action == "status":
                hub_console.print_status(console, url, data)
            else:
                hub_console.print_execution_log(console, data)
            sys.exit(0)

        import uvicorn
        from kinenix_hub import app as hub_app
        host = args.host or hub_config.HOST
        hub_console.print_banner(
            console, host, port, hub_config.CENTRAL_LLM_URL,
            api_key_set=bool(hub_config.API_KEY),
            dashboard_password_set=hub_config.dashboard_password_required(),
        )
        hub_console.hide_uvicorn_bind_url()
        uvicorn.run(hub_app.app, host=host, port=port)
        sys.exit(0)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

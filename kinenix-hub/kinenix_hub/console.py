"""Terminal output for `kinenix hub`: the startup banner and the `status` command."""
import logging
import secrets
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .settings_file import hash_password, read_saved_settings, write_settings

WORKER_STATUS_STYLES = {"online": "green", "busy": "yellow", "offline": "red"}
EXECUTION_STATUS_STYLES = {"success": "green", "partial": "dark_orange", "interrupted": "yellow", "failed": "red", "running": "yellow"}
STEP_STATUS_STYLES = {"success": "green", "failed": "red", "skipped": "dim"}


def lan_ip() -> Optional[str]:
    """IP address of the interface used for outbound traffic (no packets are sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") else ip


def browser_urls(host: str, port: int) -> List[str]:
    """URLs a person can open for a given bind address; 0.0.0.0 itself is not a valid browser address."""
    if host in ("0.0.0.0", "::"):  # nosec B104: a comparison, nothing is bound here
        urls = [f"http://127.0.0.1:{port}"]
        ip = lan_ip()
        if ip:
            urls.append(f"http://{ip}:{port}")
        return urls
    return [f"http://{host}:{port}"]


class _HideBindUrl(logging.Filter):
    """Drops uvicorn's "Uvicorn running on http://0.0.0.0:..." line; the banner already shows URLs that open."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not str(record.msg).startswith("Uvicorn running on")


def hide_uvicorn_bind_url() -> None:
    logging.getLogger("uvicorn.error").addFilter(_HideBindUrl())


def print_banner(console: Console, host: str, port: int, llm_url: str, api_key_set: bool, dashboard_password_set: bool) -> None:
    remote = host in ("0.0.0.0", "::")  # nosec B104: a comparison, nothing is bound here
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan", no_wrap=True)
    grid.add_column(overflow="fold")

    urls = browser_urls(host, port)
    if len(urls) > 1 and dashboard_password_set:
        # Seen over ssh, 127.0.0.1 opens the viewer's own machine; the LAN address works from every machine
        grid.add_row("Dashboard", Text(urls[1]) + Text(f"  (on this machine: {urls[0]})", style="dim"))
    else:
        grid.add_row("Dashboard", urls[0])
    if len(urls) > 1:
        grid.add_row("Worker URL", Text(urls[1], style="bold"))
    grid.add_row("Listening on", f"{host}:{port} " + ("(all interfaces)" if remote else "(this address only)"))
    if len(urls) > 1:
        grid.add_row("Connect a worker", Text(f"kinenix connect {urls[1]}", style="bold") + Text("  (key: kinenix hub show-key)", style="dim"))
    grid.add_row("Worker API key", Text("set", style="green") if api_key_set else Text("not set: localhost workers only", style="yellow"))
    grid.add_row("Dashboard login", Text("set", style="green") if dashboard_password_set else Text("not set: localhost viewers only", style="yellow"))
    grid.add_row("Central LLM", llm_url)

    console.print(Panel(grid, title="[bold]Kinenix Hub[/]", subtitle="[dim]Ctrl+C to stop[/]",
                        border_style="cyan", expand=False))


def can_prompt() -> bool:
    """Prompts are shown only in an interactive terminal, never when run as a service or from a script."""
    return sys.stdin is not None and sys.stdin.isatty()


def ask_secret(console: Console, label: str) -> str:
    return console.input(f"[bold cyan]{label}[/]: ", password=True).strip()


def ask_text(console: Console, label: str, default: str) -> str:
    return console.input(f"[bold cyan]{label}[/] [dim]\\[{default}][/]: ").strip() or default


def ask_yes_no(console: Console, label: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        answer = console.input(f"[bold cyan]{label}[/] [dim]\\[{hint}][/]: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        console.print("[red]Please answer y or n.[/]")


def _ask_port(console: Console, default: str) -> str:
    while True:
        port = ask_text(console, "Port", default)
        if port.isdigit() and 0 < int(port) < 65536:
            return port
        console.print("[red]Enter a number between 1 and 65535.[/]")


def _ask_new_password(console: Console, label: str) -> str:
    """Hidden input asked twice; an empty answer means no change."""
    while True:
        password = ask_secret(console, label)
        if not password or ask_secret(console, "Repeat dashboard password") == password:
            return password
        console.print("[red]Passwords do not match. Try again.[/]")


def _ask_send_local_runs(console: Console, values: Dict[str, str]) -> None:
    """Offers to send runs and heartbeats from this machine to this Hub (kinenix connect, saved in kinenix.env)."""
    from kinenix.workspace import save_settings, saved_settings, settings_file

    local_url = f"http://127.0.0.1:{values.get('KINENIX_HUB_PORT', '8080')}"
    current = saved_settings().get("KINENIX_HUB_URL", "").rstrip("/")
    local = current == local_url or not current
    question = ("Send runs from this machine (kinenix run, kinenix-worker) to this Hub?" if local else
                f"This machine sends runs to {current}. Send them to this Hub instead?")
    if ask_yes_no(console, question, default=local):
        save_settings({"KINENIX_HUB_URL": local_url, "KINENIX_HUB_API_KEY": values.get("KINENIX_HUB_API_KEY") or None})
        console.print(f"[green]Saved[/] {settings_file()}: runs on this machine go to {local_url}")
    elif current == local_url:
        save_settings({"KINENIX_HUB_URL": None, "KINENIX_HUB_API_KEY": None})
        console.print(f"Runs on this machine are no longer sent to {local_url}.")


def run_setup(console: Console, path: Path) -> Dict[str, str]:
    """Interactive first-run setup. Saves the answers to the settings file and returns them."""
    values = read_saved_settings(path)  # carries over a pre-rename orchestrator.env
    console.print(Panel(
        "Answers are saved to " + str(path) + "\nso next time `kinenix hub` starts without questions.\n"
        "[dim]Run `kinenix hub setup` again to change them.[/]",
        title="[bold]Kinenix Hub setup[/]", border_style="cyan", expand=False,
    ))

    remote = ask_yes_no(console, "Allow workers on other machines (e.g. a Raspberry Pi) to connect?",
                        default=values.get("KINENIX_HUB_HOST", "0.0.0.0") != "127.0.0.1")  # nosec B104
    # Every address only when the person answers yes; the Hub then needs the worker key (docs/hub.md)
    values["KINENIX_HUB_HOST"] = "0.0.0.0" if remote else "127.0.0.1"  # nosec B104
    values["KINENIX_HUB_PORT"] = _ask_port(console, values.get("KINENIX_HUB_PORT", "8080"))

    new_key = None
    if remote:
        has_key = bool(values.get("KINENIX_HUB_API_KEY"))
        typed = ask_secret(console, "Worker API key (Enter to keep the current key)" if has_key
                           else "Worker API key (Enter to generate a new one)")
        if typed:
            values["KINENIX_HUB_API_KEY"] = typed
        elif not has_key:
            new_key = values["KINENIX_HUB_API_KEY"] = secrets.token_urlsafe(32)

        user = values.get("KINENIX_HUB_DASHBOARD_USER", "admin")
        has_password = bool(values.get("KINENIX_HUB_DASHBOARD_PASSWORD_HASH"))
        password = _ask_new_password(
            console,
            f"Dashboard password for '{user}' " + ("(Enter to keep the current password)" if has_password
                                                   else "(Enter to allow localhost viewers only)"),
        )
        if password:
            values["KINENIX_HUB_DASHBOARD_PASSWORD_HASH"] = hash_password(password)

    write_settings(path, values)
    console.print(f"[green]Saved[/] {path}")
    _ask_send_local_runs(console, values)
    if new_key:
        console.print(Panel(
            f"{new_key}\n\n[dim]Set it on each worker as KINENIX_HUB_API_KEY.\n"
            "Show it again with: kinenix hub show-key[/]",
            title="[bold]New worker API key[/]", border_style="yellow", expand=False,
        ))
    return values


def fetch_status(base_url: str, auth: Optional[Tuple[str, str]], limit: int) -> Dict[str, Any]:
    """Read workers and recent executions. Raises requests.RequestException on network or HTTP errors."""
    base_url = base_url.rstrip("/")
    workers = requests.get(f"{base_url}/api/v1/workers", auth=auth, timeout=5)
    workers.raise_for_status()
    executions = requests.get(f"{base_url}/api/v1/executions", params={"limit": limit}, auth=auth, timeout=5)
    executions.raise_for_status()
    return {"workers": workers.json()["workers"], "executions": executions.json()["executions"]}


def _ago(iso_timestamp: Optional[str], now: Optional[datetime] = None) -> str:
    if not iso_timestamp:
        return "-"
    try:
        then = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return iso_timestamp
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    seconds = int(((now or datetime.now(timezone.utc)) - then).total_seconds())
    if seconds < 60:
        return f"{max(seconds, 0)}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _local_time(iso_timestamp: Optional[str]) -> str:
    """A stored UTC time as this machine's local time, for people: 2026-10-15 14:06:27 +07:00."""
    if not iso_timestamp:
        return "-"
    try:
        value = datetime.fromisoformat(iso_timestamp)
    except ValueError:
        return iso_timestamp
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone()
    offset = local.strftime("%z")
    return f"{local:%Y-%m-%d %H:%M:%S} {offset[:3]}:{offset[3:]}"


def _styled(value: str, styles: Dict[str, str]) -> Text:
    return Text(value or "-", style=styles.get(value, ""))


def partial_text(details: Any) -> str:
    """What failed in a run that finished anyway: work items when the flow counts them, otherwise steps."""
    details = details if isinstance(details, dict) else {}
    total, failed = details.get("items_total"), details.get("items_failed")
    if total and failed:
        return f"{failed} of {total} items failed"
    count = details.get("failure_count")
    return f"{count} step(s) failed and the run went on" if count else "some steps failed and the run went on"


def print_status(console: Console, base_url: str, data: Dict[str, Any], now: Optional[datetime] = None) -> None:
    workers = Table(title=f"Workers ({len(data['workers'])})", title_justify="left", title_style="bold")
    for column in ("Worker", "IP", "Status", "Task", "CPU", "RAM", "Last seen"):
        workers.add_column(column, no_wrap=column in ("Status", "CPU", "Last seen"))
    for w in sorted(data["workers"], key=lambda w: w["id"]):
        cpu = w.get("cpu_percent")
        workers.add_row(
            w["id"],
            w.get("ip_address") or "-",
            _styled(w.get("status"), WORKER_STATUS_STYLES),
            w.get("current_task") or "-",
            f"{cpu:.0f}%" if cpu is not None else "-",
            w.get("ram_usage") or "-",
            _ago(w.get("last_heartbeat"), now),
        )

    executions = Table(title=f"Recent executions ({len(data['executions'])})", title_justify="left", title_style="bold")
    for column in ("ID", "When", "Flow", "Worker", "Status", "Duration", "Failure"):
        executions.add_column(column, no_wrap=column in ("ID", "When", "Status", "Duration"))
    for e in data["executions"]:
        failure = "-"
        if e.get("has_error"):
            failure = e.get("ai_summary") or e.get("error_message") or e.get("failed_step_name") or "failed"
        elif e.get("status") == "partial":
            failure = partial_text(e.get("details"))
        elif e.get("status") == "interrupted":
            failure = "stopped on request"
        executions.add_row(
            Text(short_id(e.get("id")), style="dim"),
            _ago(e.get("created_at"), now),
            Text(e.get("flow_name") or "-"),
            Text(e.get("worker_id") or "-"),
            _styled(e.get("status"), EXECUTION_STATUS_STYLES),
            f"{e.get('duration_seconds') or 0:.1f}s",
            Text(failure, style="red" if e.get("has_error") else ("dark_orange" if e.get("status") == "partial" else "")),
        )

    console.print(f"[bold]Kinenix Hub[/] [dim]{base_url}[/]")
    console.print(workers if data["workers"] else "[dim]No workers have sent a heartbeat yet.[/]")
    console.print(executions if data["executions"] else "[dim]No executions recorded yet.[/]")
    if data["executions"]:
        console.print("[dim]Step details: kinenix hub logs <ID>  (latest run when ID is omitted)[/]")


SHORT_ID_LENGTH = 8


def short_id(execution_id: Optional[str]) -> str:
    return (execution_id or "-")[:SHORT_ID_LENGTH]


def fetch_execution_log(base_url: str, auth: Optional[Tuple[str, str]], id_prefix: Optional[str],
                        flow: Optional[str] = None) -> Dict[str, Any]:
    """Find an execution by ID prefix (latest when None) among recent runs and return it with its steps.

    With `flow`, the latest run of that flow (an exact name or part of one), found by the Hub.
    Raises LookupError when no or several executions match, and requests.RequestException on network or HTTP errors.
    """
    base_url = base_url.rstrip("/")
    if flow:
        params = {"flow": flow, "run": id_prefix} if id_prefix else {"flow": flow}
        res = requests.get(f"{base_url}/api/v1/query/runs", params=params, auth=auth, timeout=10)
        if res.status_code == 400:
            raise LookupError(res.json().get("detail", res.text))
        if res.status_code == 404:
            raise LookupError("This Hub is too old for --flow; give the execution ID instead.")
        res.raise_for_status()
        execution_id = res.json()["runs"][0]["execution_id"]
        res = requests.get(f"{base_url}/api/v1/executions/{execution_id}/steps", auth=auth, timeout=5)
        res.raise_for_status()
        return res.json()
    res = requests.get(f"{base_url}/api/v1/executions", params={"limit": 200}, auth=auth, timeout=5)
    res.raise_for_status()
    executions = res.json()["executions"]
    if not executions:
        raise LookupError("No executions recorded yet.")

    if id_prefix:
        # The Hub's execution id, or the run id that `kinenix run` prints first (also ${run.id} and log names)
        matches = [e for e in executions if e["id"].startswith(id_prefix)
                   or str((e.get("details") or {}).get("run_id") or "").startswith(id_prefix)]
        if not matches:
            raise LookupError(f"No recent execution or run ID starts with '{id_prefix}'.")
        if len(matches) > 1:
            raise LookupError(f"'{id_prefix}' matches {len(matches)} executions; type more characters of the ID.")
        execution_id = matches[0]["id"]
    else:
        execution_id = executions[0]["id"]

    res = requests.get(f"{base_url}/api/v1/executions/{execution_id}/steps", auth=auth, timeout=5)
    res.raise_for_status()
    return res.json()


def print_execution_log(console: Console, data: Dict[str, Any], now: Optional[datetime] = None) -> None:
    e = data["execution"]
    failed = bool(e.get("has_error"))

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold cyan", no_wrap=True)
    header.add_column(overflow="fold")
    header.add_row("Flow", Text(e.get("flow_name") or "-"))
    header.add_row("Worker", Text(e.get("worker_id") or "-"))
    header.add_row("Status", _styled(e.get("status"), EXECUTION_STATUS_STYLES))
    if e.get("status") == "partial":
        header.add_row("", Text(partial_text(e.get("details")), style="dark_orange"))
    header.add_row("Started", f"{_local_time(e.get('start_time'))} ({_ago(e.get('created_at'), now)})")
    header.add_row("Duration", f"{e.get('duration_seconds') or 0:.1f}s")
    header.add_row("ID", e.get("id") or "-")
    if failed:
        header.add_row("Failed step", Text(e.get("failed_step_name") or e.get("failed_step_id") or "-", style="red"))
        header.add_row("Error", Text(e.get("error_message") or "-", style="red"))
        if e.get("ai_summary"):
            header.add_row("AI summary", Text(e["ai_summary"]))
        if e.get("ai_suggestion"):
            header.add_row("Suggestion", Text(e["ai_suggestion"]))
    console.print(Panel(header, title="[bold]Execution[/]", border_style="red" if failed else "green", expand=False))

    steps = data.get("steps") or []
    if not steps:
        console.print("[dim]No step details were recorded for this execution.[/]")
        return

    table = Table(title=f"Steps ({len(steps)})", title_justify="left", title_style="bold")
    for column in ("#", "Step", "Action", "Status", "Duration", "Error"):
        table.add_column(column, no_wrap=column in ("#", "Status", "Duration"))
    for number, step in enumerate(steps, start=1):
        duration = step.get("duration_seconds")
        error = step.get("error_message") or "-"
        if step.get("error_type") and step.get("error_message"):
            error = f"{step['error_type']}: {step['error_message']}"
        if step.get("root_cause"):
            # The worker's diagnosis reads better than Playwright's call log (#111); the dashboard keeps the full message
            error = step["root_cause"] + (f"\nFix: {step['suggested_fix']}" if step.get("suggested_fix") else "")
        name = step.get("step_name") or step.get("step_id") or "-"
        if step.get("item"):
            name += f"\n({step['item']})"
        table.add_row(
            str(number),
            Text(name),
            Text(step.get("action") or "-", style="dim"),
            _styled(step.get("status"), STEP_STATUS_STYLES),
            f"{duration:.1f}s" if isinstance(duration, (int, float)) else "-",
            Text(error, style="red" if step.get("error_message") else ""),
        )
    console.print(table)

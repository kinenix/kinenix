import argparse
import json
import sys

from kinenix import exit_codes
from kinenix.engine.stopping import install_signal_handlers
from pathlib import Path

from rich.console import Console

from . import __version__, display
from .hub_client import HeartbeatThread, HubClient
from .logs import configure_logging
from .runner import WorkerRunner


def main():
    parser = argparse.ArgumentParser(
        prog="kinenix-worker",
        description="Kinenix Worker: Unattended Robot Daemon and Edge Execution Engine"
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"kinenix-worker {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: info
    subparsers.add_parser("info", help="Display worker machine hardware, architecture, and runtime stats")

    # Command: ping
    subparsers.add_parser("ping", help="Check the connection and API key to the Hub (KINENIX_HUB_URL)")

    # Command: run
    run_parser = subparsers.add_parser("run", help="Execute a flow or project bundle on this worker")
    run_parser.add_argument("flow_path", help="Flow name, project bundle directory, or path to a flow.md")
    run_parser.add_argument("--sandbox", action="store_true", help="Run from a separate copy of the bundle in ~/.kinenix/workspaces (not isolation: the flow keeps your rights)")
    run_parser.add_argument("--vars", type=str, help="JSON string of variables to inject (e.g. '{\"env\":\"prod\"}')")
    run_parser.add_argument("--log-dir", type=str, help="Custom directory path to store execution logs")

    # Command: watch
    watch_parser = subparsers.add_parser("watch", help="Watch a directory and automatically trigger a flow when new files appear")
    watch_parser.add_argument("directory", help="Directory path to watch")
    watch_parser.add_argument("--flow", required=True, help="Flow name, bundle directory, or flow.md to execute")
    watch_parser.add_argument("--pattern", default="*.*", help="File matching pattern (e.g. '*.xlsx', '*.csv')")
    watch_parser.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    watch_parser.add_argument("--sandbox", action="store_true", help="Run each time from a separate copy of the bundle (not isolation)")
    watch_parser.add_argument("--vars", type=str, help="JSON string of variables to inject")

    # Command: schedule
    sched_parser = subparsers.add_parser("schedule", help="Execute a flow on a scheduled time interval")
    sched_parser.add_argument("--flow", required=True, help="Flow name, bundle directory, or flow.md to execute")
    sched_parser.add_argument("--interval", type=float, default=60.0, help="Interval in seconds between runs")
    sched_parser.add_argument("--cron", type=str, default=None,
                              help="Five-field cron expression in local time, e.g. '0 8 1 * *' (overrides --interval)")
    sched_parser.add_argument("--sandbox", action="store_true", help="Run each time from a separate copy of the bundle (not isolation)")
    sched_parser.add_argument("--vars", type=str, help="JSON string of variables to inject")

    # Command: daemon
    daemon_parser = subparsers.add_parser("daemon", help="Run multi-trigger daemon using a configuration file")
    daemon_parser.add_argument("--config", default="triggers.json", help="Path to triggers.json configuration file")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    console = Console()
    client = HubClient()
    runner = WorkerRunner(client=client)

    if args.command == "info":
        display.print_info(console, runner.get_system_info(), client)
        sys.exit(0)

    if args.command == "ping":
        with console.status(f"Contacting {client.url or 'Hub'}..."):
            result = client.ping()
        display.print_ping(console, client, result)
        sys.exit(exit_codes.OK if result["authorized"] else exit_codes.UNREACHABLE)

    def start_heartbeats() -> None:
        if client.enabled:
            HeartbeatThread(client).start()
            console.print(f"[dim]Sending heartbeats to {client.url} as '{client.worker_id}'[/]")

    if args.command == "run":
        extra_vars = {}
        if args.vars:
            try:
                extra_vars = json.loads(args.vars)
            except Exception as e:
                print(f"Error parsing --vars JSON: {e}", file=sys.stderr)
                sys.exit(exit_codes.USAGE)

        # Keep heartbeats going during long flows so the worker is not shown as offline mid-run
        start_heartbeats()
        install_signal_handlers()
        try:
            res = runner.execute_flow(
                flow_path_or_alias=args.flow_path,
                extra_vars=extra_vars,
                use_sandbox=args.sandbox,
                log_dir=args.log_dir
            )

            display.print_run_result(console, res)
            sys.exit(res["exit_code"])

        except KeyboardInterrupt:
            print("\nStopped (Ctrl+C).", file=sys.stderr)
            sys.exit(exit_codes.INTERRUPTED)
        except FileNotFoundError as e:
            print(f"Worker execution failed: {e}", file=sys.stderr)
            sys.exit(exit_codes.NOT_FOUND)
        except Exception as e:
            print(f"Worker execution failed with error: {e}", file=sys.stderr)
            sys.exit(exit_codes.TECHNICAL)

    if args.command == "watch":
        configure_logging()
        from .triggers.watcher import FileWatcherTrigger

        extra_vars = {}
        if args.vars:
            try:
                extra_vars = json.loads(args.vars)
            except Exception as e:
                print(f"Error parsing --vars JSON: {e}", file=sys.stderr)
                sys.exit(exit_codes.USAGE)

        watcher = FileWatcherTrigger(
            watch_dir=args.directory,
            flow_path=args.flow,
            pattern=args.pattern,
            poll_interval=args.interval,
            use_sandbox=args.sandbox,
            extra_vars=extra_vars,
            runner=runner
        )
        print(f"Watching directory '{args.directory}' for pattern '{args.pattern}'...")
        print(f"Target flow: {args.flow}")
        print("Press Ctrl+C to stop.")
        start_heartbeats()
        watcher.run_loop()
        sys.exit(0)

    if args.command == "schedule":
        configure_logging()
        from .triggers.scheduler import CronSchedulerTrigger

        extra_vars = {}
        if args.vars:
            try:
                extra_vars = json.loads(args.vars)
            except Exception as e:
                print(f"Error parsing --vars JSON: {e}", file=sys.stderr)
                sys.exit(exit_codes.USAGE)

        try:
            scheduler = CronSchedulerTrigger(
                flow_path=args.flow,
                interval_seconds=args.interval,
                use_sandbox=args.sandbox,
                extra_vars=extra_vars,
                runner=runner,
                cron=args.cron
            )
        except ValueError as e:
            print(f"Invalid --cron: {e}", file=sys.stderr)
            sys.exit(exit_codes.USAGE)
        print(f"Scheduled flow '{args.flow}' to run {scheduler.describe()}...")
        print("Press Ctrl+C to stop.")
        start_heartbeats()
        scheduler.run_loop()
        sys.exit(0)

    if args.command == "daemon":
        configure_logging()
        from .triggers.manager import TriggerManager

        manager = TriggerManager(runner=runner)
        try:
            manager.load_from_config(args.config)
            print(f"Loaded triggers from '{args.config}'. Running daemon...")
            print("Press Ctrl+C to stop.")
            start_heartbeats()
            manager.start_all(blocking=True)
            sys.exit(0)
        except Exception as e:
            print(f"Failed to start trigger daemon: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()


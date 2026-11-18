"""config/local.json: machine settings merged over config/config.json at every run (#233)."""
import json
import subprocess
import sys
from pathlib import Path

from kinenix import exit_codes
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import load_flow
from kinenix.engine.validation import validate_flow

FLOW = """# Local Config

## Steps

### 1. Keep Site (`logic.set_variable`)
- **name:** seen_site
- **value:** ${config.site}

### 2. Keep Printer (`logic.set_variable`)
- **name:** seen_printer
- **value:** ${config.printer}

### 3. Keep Folders (`logic.set_variable`)
- **name:** seen_folders
- **value:** ${config.folders}
"""

SUBFLOW_CALL = """
### 4. Call Subflow (`flow.call`)
- **flow:** ./subflows/read_site.md
- **output_var:** sub
"""

SUBFLOW = """# Read Site

## Steps

### 1. Return Site (`flow.return`)
- **outputs:** {"site": "${config.site}"}
"""


def make_bundle(tmp_path: Path, local=None, flow_text=FLOW) -> Path:
    bundle = tmp_path / "bundle"
    (bundle / "config").mkdir(parents=True)
    (bundle / "flow.md").write_text(flow_text, encoding="utf-8")
    (bundle / "config" / "config.json").write_text(json.dumps(
        {"site": "https://test.example", "printer": "Office", "folders": {"in": "a", "out": "b"}}), encoding="utf-8")
    if local is not None:
        text = local if isinstance(local, str) else json.dumps(local)
        (bundle / "config" / "local.json").write_text(text, encoding="utf-8")
    return bundle


def run(bundle: Path, tmp_path: Path, config=None):
    flow = load_flow(bundle / "flow.md")
    interpreter = FlowInterpreter(logger=ExecutionLogger(log_dir=tmp_path / "logs"))
    initial = {"__flow_dir__": str(bundle)}
    if config is not None:
        initial["config"] = config
    return interpreter.run_flow(flow, initial_vars=initial)


def test_without_local_json_config_json_is_used(tmp_path):
    ctx = run(make_bundle(tmp_path), tmp_path)
    assert not ctx.has_error
    assert ctx.get_variable("seen_site") == "https://test.example"


def test_local_json_replaces_top_level_keys(tmp_path):
    bundle = make_bundle(tmp_path, {"site": "https://prod.example", "folders": {"in": "x"}})
    ctx = run(bundle, tmp_path)
    assert not ctx.has_error
    assert ctx.get_variable("seen_site") == "https://prod.example"
    assert ctx.get_variable("seen_printer") == "Office"
    # A key holding an object is replaced whole, as with --config
    assert ctx.get_variable("config")["folders"] == {"in": "x"}
    # Each config key is also a variable of its own
    assert ctx.get_variable("site") == "https://prod.example"


def test_config_from_the_caller_wins_over_local_json(tmp_path):
    bundle = make_bundle(tmp_path, {"site": "https://prod.example", "printer": "Lab"})
    ctx = run(bundle, tmp_path, config={"site": "tests/pages/site.html"})
    assert ctx.get_variable("seen_site") == "tests/pages/site.html"
    assert ctx.get_variable("seen_printer") == "Lab"


def test_local_json_is_read_at_every_run(tmp_path):
    bundle = make_bundle(tmp_path, {"site": "https://one.example"})
    assert run(bundle, tmp_path).get_variable("seen_site") == "https://one.example"
    (bundle / "config" / "local.json").write_text(json.dumps({"site": "https://two.example"}), encoding="utf-8")
    assert run(bundle, tmp_path).get_variable("seen_site") == "https://two.example"


def test_subflow_of_the_bundle_sees_local_json(tmp_path):
    bundle = make_bundle(tmp_path, {"site": "https://prod.example"}, FLOW + SUBFLOW_CALL)
    (bundle / "subflows").mkdir()
    (bundle / "subflows" / "read_site.md").write_text(SUBFLOW, encoding="utf-8")
    ctx = run(bundle, tmp_path)
    assert not ctx.has_error, ctx.failure_details
    assert ctx.get_variable("sub")["site"] == "https://prod.example"


def test_invalid_local_json_stops_the_run(tmp_path):
    bundle = make_bundle(tmp_path, "{not json")
    ctx = run(bundle, tmp_path)
    assert ctx.has_error
    assert ctx.failure_details.exception_class == "LocalConfigError"
    assert "local.json" in ctx.failure_details.error_message
    assert ctx.get_variable("seen_site") is None
    assert exit_codes.for_run(ctx) == exit_codes.INVALID_FLOW


def test_local_json_that_is_not_an_object_stops_the_run(tmp_path):
    ctx = run(make_bundle(tmp_path, "[1, 2]"), tmp_path)
    assert ctx.has_error
    assert "JSON object" in ctx.failure_details.error_message


def test_log_names_the_keys_not_the_values(tmp_path, caplog):
    bundle = make_bundle(tmp_path, {"site": "https://secret-host.internal"})
    with caplog.at_level("INFO"):
        run(bundle, tmp_path)
    lines = [r.getMessage() for r in caplog.records if "local.json" in r.getMessage()]
    assert lines and "site" in lines[0]
    assert all("secret-host" not in line for line in lines)


def test_validate_reports_an_invalid_local_json(tmp_path):
    bundle = make_bundle(tmp_path, "{not json")
    issues = validate_flow(load_flow(bundle / "flow.md"), bundle)
    assert any("local.json" in issue for issue in issues)
    good = make_bundle(tmp_path / "good", {"site": "x"})
    assert not any("local.json" in issue for issue in validate_flow(load_flow(good / "flow.md"), good))


def test_cli_run_applies_local_json_and_config_on_top(tmp_path):
    bundle = make_bundle(tmp_path, {"site": "https://prod.example", "printer": "Lab"})
    (bundle / "config" / "test.json").write_text(json.dumps({"site": "tests/pages/site.html"}), encoding="utf-8")
    env_file = tmp_path / "kinenix.env"
    import os
    env = {**os.environ, "KINENIX_SETTINGS_FILE": str(env_file), "KINENIX_HUB_URL": "", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-m", "kinenix.cli", "run", str(bundle), "--config", "config/test.json",
                             "--log-dir", str(tmp_path / "logs")], env=env, capture_output=True, text=True,
                            encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    assert "Applied machine settings from config/local.json: printer, site" in result.stdout + result.stderr
    log = next((tmp_path / "logs").rglob("*.json"))
    assert "tests/pages/site.html" in log.read_text(encoding="utf-8")


def test_validate_reports_an_invalid_local_json_once_with_subflows(tmp_path):
    """Seen on the Pi: the bundle's subflow repeated the problem. The CLI reports it once, as one sentence."""
    from kinenix.engine.validation import validate_subflows

    bundle = make_bundle(tmp_path, "{oops", FLOW + SUBFLOW_CALL)
    (bundle / "subflows").mkdir()
    (bundle / "subflows" / "read_site.md").write_text(SUBFLOW, encoding="utf-8")
    flow = load_flow(bundle / "flow.md")
    issues = validate_flow(flow, bundle) + validate_subflows(flow, bundle)
    local = [issue for issue in issues if "local.json" in issue]
    assert len(local) == 1
    assert "(char 1). A run stops" in local[0]

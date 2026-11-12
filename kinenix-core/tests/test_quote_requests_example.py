"""0.5.0b1: the quote_requests example runs end to end against its saved insurer page, as its README says."""
import csv

import pytest

from kinenix import scaffold
from kinenix.engine import requires
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import load_flow


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(requires, "__version__", "999.0")  # the example requires the version being developed
    return scaffold.create_project(tmp_path / "quotes", example="quote_requests")


def _rows(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_the_example_ships_what_its_readme_lists(project):
    for name in ("flow.md", "subflows/quote_one.md", "requirements.md", "config/config.json", "input/requests.csv",
                 "tests/pages/quote.html", ".env.example"):
        assert (project / name).is_file(), name
    assert not (project / "env.example").exists()


def test_five_requests_three_quoted_two_failed_with_their_reasons(project, chromium, tmp_path):
    context = FlowInterpreter(logger=ExecutionLogger(log_dir=tmp_path / "logs")).run_flow(
        load_flow(project / "flow.md"),
        initial_vars={"__flow_dir__": str(project), "config": {"headless": True}})
    assert not context.has_error, context.failure_details and context.failure_details.error_message
    assert context.items == {"total": 5, "done": 3, "failed": 2}

    packages = _rows(project / "output" / "packages.csv")
    assert [(p["request_id"], p["package_name"]) for p in packages] == [
        ("R001", "Comprehensive Standard"), ("R001", "Comprehensive Plus"), ("R001", "Comprehensive Lady"),
        ("R002", "Two Plus Saver"), ("R002", "Two Plus Extra"),
        ("R003", "Comprehensive Standard"), ("R003", "Comprehensive Plus"), ("R003", "Comprehensive Lady")]
    assert all(float(p["premium_thb_per_year"]) > 0 for p in packages)

    failed = {r["request_id"]: r["reason"] for r in _rows(project / "output" / "failed_requests.csv")}
    assert set(failed) == {"R004", "R005"}
    # error.root_cause names the value and what the site offers (#219)
    assert failed["R004"] == "The value 'CX-30' is not one of the options in step 'Choose Model'. The page offers: CX-3."
    assert failed["R005"] == "brand, model, and sub_model are required"
    assert sorted(p.name for p in (project / "output" / "screenshots").iterdir()) == ["R001.png", "R002.png", "R003.png"]

    # The customer's name stays out of the log written to disk, which is also what the Hub receives (config redact);
    # the run itself still has it, since redaction works on copies
    logs = [p for p in (tmp_path / "logs").rglob("*.json*")]
    assert logs and all("Somchai Jaidee" not in p.read_text(encoding="utf-8") for p in logs)

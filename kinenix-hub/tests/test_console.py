from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests
from rich.console import Console

from kinenix.workspace import save_settings, saved_settings
from kinenix_hub import console as hub_console
from kinenix_hub.settings_file import read_settings, verify_password, write_settings

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)


def _console() -> Console:
    return Console(record=True, width=160, color_system=None)


def test_browser_urls_never_offer_wildcard_address(monkeypatch):
    monkeypatch.setattr(hub_console, "lan_ip", lambda: "192.168.1.132")
    assert hub_console.browser_urls("0.0.0.0", 8080) == ["http://127.0.0.1:8080", "http://192.168.1.132:8080"]
    assert hub_console.browser_urls("127.0.0.1", 9000) == ["http://127.0.0.1:9000"]

    monkeypatch.setattr(hub_console, "lan_ip", lambda: None)
    assert hub_console.browser_urls("0.0.0.0", 8080) == ["http://127.0.0.1:8080"]


def test_banner_shows_worker_url_and_auth_state(monkeypatch):
    monkeypatch.setattr(hub_console, "lan_ip", lambda: "192.168.1.132")
    console = _console()
    hub_console.print_banner(console, "0.0.0.0", 8080,
                              api_key_set=True, dashboard_password_set=False)
    out = console.export_text()
    assert "http://192.168.1.132:8080" in out
    assert "localhost viewers only" in out
    assert "http://0.0.0.0" not in out


def test_the_dashboard_url_works_from_other_machines_when_they_may_log_in(monkeypatch):
    # Over ssh, http://127.0.0.1 opened the viewer's own machine, not the Hub
    monkeypatch.setattr(hub_console, "lan_ip", lambda: "192.168.1.137")
    console = _console()
    hub_console.print_banner(console, "0.0.0.0", 8080,
                              api_key_set=True, dashboard_password_set=True)
    dashboard = [line for line in console.export_text().splitlines() if "Dashboard " in line][0]
    assert "http://192.168.1.137:8080  (on this machine: http://127.0.0.1:8080)" in dashboard


def test_bind_url_log_line_is_hidden():
    import logging
    hide = hub_console._HideBindUrl()
    make = lambda msg: logging.LogRecord("uvicorn.error", logging.INFO, "", 0, msg, None, None)
    assert not hide.filter(make("Uvicorn running on %s://%s:%d (Press CTRL+C to quit)"))
    assert hide.filter(make("Application startup complete."))


@pytest.mark.parametrize("timestamp, expected", [
    ("2026-10-03T11:59:55+00:00", "5s ago"),
    ("2026-10-03T11:45:00+00:00", "15m ago"),
    ("2026-10-03T09:00:00", "3h ago"),
    ("2026-09-30T12:00:00+00:00", "3d ago"),
    (None, "-"),
])
def test_ago(timestamp, expected):
    assert hub_console._ago(timestamp, NOW) == expected


def test_print_status_renders_workers_and_failures():
    data = {
        "workers": [{
            "id": "rpi4-01", "ip_address": "192.168.1.50", "status": "busy", "current_task": "RPA Challenge",
            "cpu_percent": 41.2, "ram_usage": "0.9 / 1.8 GB", "last_heartbeat": "2026-10-03T11:59:58+00:00",
        }],
        "executions": [{
            "flow_name": "RPA Challenge", "worker_id": "rpi4-01", "status": "failed", "duration_seconds": 8.42,
            "has_error": True, "error_message": "Selector not found on submit button", "created_at": "2026-10-03T11:58:00+00:00",
        }],
    }
    console = _console()
    hub_console.print_status(console, "http://127.0.0.1:8080", data, now=NOW)
    out = console.export_text()
    for expected in ("rpi4-01", "busy", "41%", "2s ago", "failed", "8.4s", "Selector not found", "2m ago"):
        assert expected in out


def test_print_status_empty():
    console = _console()
    hub_console.print_status(console, "http://127.0.0.1:8080", {"workers": [], "executions": []})
    out = console.export_text()
    assert "No workers" in out and "No executions" in out


@pytest.fixture(autouse=True)
def no_saved_hub():
    """Each test starts without a Hub saved in kinenix.env (a test file set by conftest.py)."""
    save_settings({"KINENIX_HUB_URL": None, "KINENIX_HUB_API_KEY": None})


def _scripted_console(monkeypatch, *answers) -> Console:
    """Console whose input() returns the given answers in order, for plain and hidden prompts alike."""
    console = _console()
    queue = list(answers)
    monkeypatch.setattr(console, "input", lambda prompt="", password=False: queue.pop(0))
    return console


def test_setup_first_run_generates_key_and_hashes_password(monkeypatch, tmp_path):
    path = tmp_path / "hub.env"
    # remote? port, api key (generate), password, typo repeat, password, repeat, send this machine's runs here?
    console = _scripted_console(monkeypatch, "", "", "", "first", "typo", "second", "second", "")
    values = hub_console.run_setup(console, path)
    out = console.export_text()

    saved = read_settings(path)
    assert saved == values
    assert saved["KINENIX_HUB_HOST"] == "0.0.0.0"
    assert saved["KINENIX_HUB_PORT"] == "8080"
    assert len(saved["KINENIX_HUB_API_KEY"]) >= 40 and saved["KINENIX_HUB_API_KEY"] in out
    assert "second" not in path.read_text(encoding="utf-8")
    assert verify_password("second", saved["KINENIX_HUB_DASHBOARD_PASSWORD_HASH"])
    assert "Passwords do not match" in out
    # Runs on the Hub machine go to this Hub without setting KINENIX_HUB_URL
    assert saved_settings() == {"KINENIX_HUB_URL": "http://127.0.0.1:8080", "KINENIX_HUB_API_KEY": saved["KINENIX_HUB_API_KEY"]}


def test_setup_rerun_keeps_existing_credentials(monkeypatch, tmp_path):
    path = tmp_path / "hub.env"
    write_settings(path, {"KINENIX_HUB_HOST": "0.0.0.0", "KINENIX_HUB_PORT": "8080",
                          "KINENIX_HUB_API_KEY": "old-key", "KINENIX_HUB_DASHBOARD_PASSWORD_HASH": "h"})
    # keep remote, change port, keep key, keep password, send this machine's runs here
    values = hub_console.run_setup(_scripted_console(monkeypatch, "", "9000", "", "", "y"), path)
    assert values == {"KINENIX_HUB_HOST": "0.0.0.0", "KINENIX_HUB_PORT": "9000",
                      "KINENIX_HUB_API_KEY": "old-key", "KINENIX_HUB_DASHBOARD_PASSWORD_HASH": "h"}
    assert saved_settings() == {"KINENIX_HUB_URL": "http://127.0.0.1:9000", "KINENIX_HUB_API_KEY": "old-key"}


def test_setup_local_only_asks_no_credentials(monkeypatch, tmp_path):
    path = tmp_path / "hub.env"
    console = _scripted_console(monkeypatch, "maybe", "n", "abc", "8081", "")
    values = hub_console.run_setup(console, path)
    assert values == {"KINENIX_HUB_HOST": "127.0.0.1", "KINENIX_HUB_PORT": "8081"}
    assert saved_settings() == {"KINENIX_HUB_URL": "http://127.0.0.1:8081"}  # no key: localhost needs none
    out = console.export_text()
    assert "Please answer y or n" in out and "between 1 and 65535" in out


def test_setup_does_not_take_over_a_machine_that_reports_elsewhere(monkeypatch, tmp_path):
    save_settings({"KINENIX_HUB_URL": "http://192.168.1.137:8080", "KINENIX_HUB_API_KEY": "remote-key"})
    console = _scripted_console(monkeypatch, "n", "", "")  # local only, port, keep sending elsewhere (default no)
    hub_console.run_setup(console, tmp_path / "hub.env")
    assert saved_settings() == {"KINENIX_HUB_URL": "http://192.168.1.137:8080", "KINENIX_HUB_API_KEY": "remote-key"}


def test_setup_answering_no_stops_sending_to_this_hub(monkeypatch, tmp_path):
    save_settings({"KINENIX_HUB_URL": "http://127.0.0.1:8080", "KINENIX_HUB_API_KEY": "k"})
    hub_console.run_setup(_scripted_console(monkeypatch, "n", "", "n"), tmp_path / "hub.env")
    assert "KINENIX_HUB_URL" not in saved_settings()


def test_fetch_status_passes_auth_and_raises_on_http_error():
    ok = MagicMock(status_code=200)
    ok.json.side_effect = [{"workers": [{"id": "w"}]}, {"executions": []}]
    with patch("kinenix_hub.console.requests.get", return_value=ok) as get:
        data = hub_console.fetch_status("http://orch:8080/", ("admin", "pw"), 5)
    assert data == {"workers": [{"id": "w"}], "executions": []}
    assert get.call_args_list[0].args[0] == "http://orch:8080/api/v1/workers"
    assert get.call_args_list[1].kwargs["params"] == {"limit": 5}
    assert all(c.kwargs["auth"] == ("admin", "pw") for c in get.call_args_list)

    denied = MagicMock(status_code=401)
    denied.raise_for_status.side_effect = requests.HTTPError(response=denied)
    with patch("kinenix_hub.console.requests.get", return_value=denied):
        with pytest.raises(requests.HTTPError):
            hub_console.fetch_status("http://orch:8080", None, 5)


def test_logs_finds_an_execution_by_the_run_id_that_kinenix_run_prints():
    listing = MagicMock(status_code=200)
    listing.json.return_value = {"executions": [
        {"id": "a1b2c3", "details": {"run_id": "20261028T101500-abcd"}},
        {"id": "d4e5f6", "details": None},
    ]}
    steps = MagicMock(status_code=200)
    steps.json.return_value = {"id": "a1b2c3", "steps": []}
    with patch("kinenix_hub.console.requests.get", side_effect=[listing, steps]) as get:
        assert hub_console.fetch_execution_log("http://hub:8080", None, "20261028T1015")["id"] == "a1b2c3"
    assert get.call_args_list[1].args[0] == "http://hub:8080/api/v1/executions/a1b2c3/steps"

    with patch("kinenix_hub.console.requests.get", return_value=listing):
        with pytest.raises(LookupError, match="execution or run ID"):
            hub_console.fetch_execution_log("http://hub:8080", None, "nothing")

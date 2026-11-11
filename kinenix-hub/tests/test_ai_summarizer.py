"""Failure analysis: Business errors are named as such, and nothing is guessed when the error is not recognized."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from kinenix_hub import console as hub_console
from kinenix_hub.services import ai_summarizer
from kinenix_hub.services.ai_summarizer import analyze_failure


@pytest.fixture
def no_llm():
    with patch("kinenix_hub.services.ai_summarizer.requests.post", side_effect=requests.ConnectionError("down")) as post:
        yield post


def test_business_error_is_reported_as_a_business_rule_without_the_llm(no_llm):
    result = analyze_failure("Demo Failures", "Stop Here", "stopping on purpose for the test",
                             "BusinessRuleError", error_type="Business")
    assert result["category"] == ai_summarizer.BUSINESS["th_label"]
    assert "stopping on purpose for the test" in result["summary"]
    assert "Selector" not in result["summary"] and "Selector" not in result["suggestion"]
    assert result["confidence"] == 100.0
    no_llm.assert_not_called()


def test_unrecognized_error_is_unknown_not_a_selector_guess(no_llm):
    result = analyze_failure("Flow", "Step", "Something odd happened", "RuntimeError", error_type="Technical")
    assert result["category"] == ai_summarizer.UNKNOWN["th_label"]
    assert result["confidence"] == 0.0 and "Something odd happened" in result["summary"]


@pytest.mark.parametrize("message, exception, category", [
    ("Timeout 30000ms exceeded", "TimeoutError", "Page Load / Network Timeout"),
    ("Excel file not found: ./assets/x.xlsx", "FileNotFoundError", "File / Resource Missing"),
    ("strict mode violation: locator resolved to 2 elements", "Error", "UI Selector Not Found / DOM Changed"),
    ("Accept cookies dialog blocked the click", "Error", "Cookie Consent / Security Modal"),
])
def test_rules_when_the_llm_is_unavailable(no_llm, message, exception, category):
    assert analyze_failure("Flow", "Step", message, exception)["category"] == ai_summarizer.CATEGORIES[category]["th_label"]


def test_an_llm_answer_outside_the_list_falls_back_to_the_rules():
    answer = MagicMock(status_code=200)
    answer.json.return_value = {"choice": "Something Else"}
    with patch("kinenix_hub.services.ai_summarizer.requests.post", return_value=answer):
        result = analyze_failure("Flow", "Step", "Timeout 5000ms exceeded", "TimeoutError")
    assert result["category"] == ai_summarizer.CATEGORIES["Page Load / Network Timeout"]["th_label"]


def test_the_llm_choice_is_used():
    answer = MagicMock(status_code=200)
    answer.json.return_value = {"choice": "Data Validation / Format Error", "score": 0.7}
    with patch("kinenix_hub.services.ai_summarizer.requests.post", return_value=answer):
        result = analyze_failure("Flow", "Step", "x", "ValueError")
    assert result["category"] == ai_summarizer.CATEGORIES["Data Validation / Format Error"]["th_label"]
    assert result["confidence"] == 70.0


def test_local_time_in_logs():
    shown = hub_console._local_time("2026-10-15T07:06:27.036829+00:00")
    expected = datetime(2026, 10, 15, 7, 6, 27, tzinfo=timezone.utc).astimezone()
    assert shown.startswith(f"{expected:%Y-%m-%d %H:%M:%S} ")
    assert hub_console._local_time(None) == "-" and hub_console._local_time("not a time") == "not a time"


def test_rule_suggestions_name_only_parameters_that_exist():
    """`ai_match` exists only on web.select_option, so a general selector hint must not suggest it (#171)."""
    from kinenix_hub.services.ai_summarizer import CATEGORIES
    assert not [name for name, rule in CATEGORIES.items() if "ai_match" in rule["suggestion"]]

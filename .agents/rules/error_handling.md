# Error Handling & Telemetry Standards

This document establishes exception handling classification and error telemetry requirements for **Kinenix**.

---

## 1. Exception Classification

All runtime exceptions encountered in flows and actions must be categorized into one of two distinct categories:

### A. Technical Exceptions
- **Definition:** Failures caused by infrastructure, network instability, system crashes, or unrecoverable selector timeouts after retry limits.
- **Examples:** Connection drop, 502 Bad Gateway, browser process crash.
- **Responsible Party:** RPA Engineer / Developer.
- **Handling:** Trigger automatic retry if configured, capture diagnostics, log technical stack trace, and alert engineering.

### B. Business Exceptions
- **Definition:** Deviations from expected business logic or invalid input data.
- **Examples:** Spreadsheet invoice amount does not balance, mandatory customer ID missing, customer account status is suspended.
- **Responsible Party:** Business Operations / Workflow Owner.
- **Handling:** Do not retry blindly; record business reason, capture state screenshot, and dispatch a structured business alert to LINE or the dashboard.

### Names
- Record and display only `Technical` and `Business` (`error_type`, `${error.type}`, the Hub). These values are part of the 1.x promise; do not rename them or add a third type.
- Parameters that choose a type (`category` of `flow.fail`, `rule_error`) accept `system` for `technical`, so developers from other RPA tools can write the name they know. Use `error_category()` in `kinenix/actions/flow_control.py` for any new one. The mapping table lives in [docs/logging.md, section 3](../../docs/logging.md#3-exception-classification).

---

## 2. Structured Error Telemetry for AI Diagnostics

When an action or flow step fails, the runtime engine must compile a structured JSON error context block:

- **Failed Step Details:** Step ID, action type, configured parameters (with sensitive data masked).
- **Runtime Environment:** Active URL (for web), current sheet and cell/row coordinates (for Excel), execution timestamp.
- **Visual Evidence:** Absolute file path to the error screenshot taken immediately at point of failure.
- **Diagnostics Payload:** Clean structured JSON ready for ingestion by Local SLMs for root-cause diagnosis without manual parsing.

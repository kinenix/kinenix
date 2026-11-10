# Testing Standards & Quality Assurance

This document defines testing conventions, validation benchmarks, and regression prevention guidelines for **Kinenix**.

---

## 1. Unit Testing (`kinenix-core`)

- **Framework:** Use `pytest` for all unit and component tests.
- **Location:** Place test files under `kinenix-core/tests/` with the standard naming convention `test_*.py`.
- **Scope of Coverage:**
  - Action execution logic (`BaseAction` subclasses).
  - Variable context interpolation, expression evaluation, and environment resolution.
  - Flow schema parsing and Pydantic model validation.
- **Mocking External Dependencies:**
  - Mock network calls, external databases, and third-party APIs in unit tests to ensure fast, deterministic test execution without external network dependency.

---

## 2. Benchmark & End-to-End Verification

- **Benchmark Suites:** Use real-world validation scenarios (the examples in `flows/examples/`, and those that need a real website in [kinenix/examples](https://github.com/kinenix/examples)) to verify end-to-end flow integrity.
- **Regression Prevention:** Whenever updating the core engine or interpreter, execute benchmark verification to ensure backward compatibility for existing flow schemas.
- **Deterministic Assertions:** End-to-end tests must verify final outputs, step count metrics, and generated log structures.

# Contributing to SudoAgent

Thanks for taking the time to contribute. This doc explains how to set up the repo, run checks, and propose changes safely.

## Ground rules

- Keep changes small and reviewable.
- Prefer adding tests with behavior changes.
- Fail closed. If something goes wrong during policy evaluation, approval, or logging, the action should not execute.
- Avoid adding new dependencies unless there is a strong reason.

## Project goals (v0.1)

SudoAgent is a synchronous runtime guard for sensitive actions:
- Policy returns ALLOW, DENY, or REQUIRE_APPROVAL.
- Approval is interactive by default (terminal y/n).
- Audit logging is append-only JSONL.
- Inputs may be untrusted. Avoid UI deception and avoid leaking secrets to logs.

## Repository layout

- `src/sudoagent/` core library
  - `engine.py` guard and execution flow
  - `types.py` typed models
  - `policies.py` policy protocol and built-in policies
  - `notifiers/` approvers (interactive, headless, etc.)
  - `loggers/` audit loggers (JSONL, etc.)
  - `errors.py` exception types
- `examples/` runnable demos
- `tests/` pytest tests
- `docs/` architecture notes

## Prerequisites

- Python 3.10, 3.11, or 3.12
- pip
- Git

## Setup (local dev)

Create and activate a virtual environment, then install in editable mode.

macOS or Linux:
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

## Running checks

Tests:

```bash
pytest -q
```

Lint:

```bash
ruff check .
```

Typecheck:

```bash
mypy src
```

Recommended pre-flight before opening a PR:

```bash
ruff check . && mypy src && pytest -q
```

## How to contribute

### 1) Fix a bug

Best PRs include:

- a failing test that reproduces the bug
- the fix
- the test passing

### 2) Add a new extension (policy, approver, logger)

SudoAgent is designed to be pluggable via small interfaces:

- Policy: implement Policy.evaluate(ctx) -> PolicyResult
- Approver: implement Approver.approve(ctx, result, request_id) -> bool
- Audit logger: implement AuditLogger.log(entry) -> None

Guidelines:

- Keep implementations minimal and predictable.
- Do not throw on common user input. If something might fail (serialization, formatting), handle it safely.
- Do not leak obvious secrets. If you add new logging surfaces, consider redaction.

### 3) Add an example

Examples should be runnable with:

```bash
python examples/<file>.py
```

Examples are treated like docs:

- Prefer clarity over cleverness.
- Catch ApprovalDenied so the demo does not end in a stack trace.
- Use keyword arguments in examples when your policy reads ctx.kwargs.

### 4) Add or adjust docs

Keep docs practical:

- Show how to use the public API.
- Describe assumptions and failure modes.
- Avoid large conceptual essays in v0.1.

## Code style

- Python 3.10+
- Type hints for public functions and most internal ones.
- Keep functions short and readable.
- Avoid Any. If you must use it, isolate it and justify it in one line.
- No async in v0.1.
- Prefer Protocol interfaces over inheritance.
- Avoid heavy refactors in unrelated areas.

## Tests

We use pytest.

When you add behavior:

- Add tests for allow, deny, and require-approval paths if relevant.
- Include fail-closed tests (exceptions in policy, approver, logger).
- Keep tests deterministic and fast.

## Commits and PRs

### Branches

Create a feature branch:

```bash
git checkout -b feat/<short-name>
```

### Commit messages

Use Conventional Commits where practical:

- feat: new feature
- fix: bug fix
- docs: documentation only
- test: tests only
- chore: tooling, maintenance
- refactor: code change without behavior change

### Pull requests

A good PR description includes:

- what changed
- why it changed
- how to test it
- any security or backward-compat implications

## Reporting bugs / requesting features

Open a GitHub issue with:

- what you expected
- what happened instead
- minimal repro steps
- environment (OS, Python version)

If the issue is security-sensitive, do not open a public issue. See SECURITY.md.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

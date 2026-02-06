# SudoAgent OSS Guide

This guide is for OSS users who want to evaluate, integrate, or extend SudoAgent quickly without reading the full spec.

## What SudoAgent is

SudoAgent is a runtime authorization boundary for tool/function calls:
policy -> (optional) approval -> (optional) budgets -> tamper-evident ledger -> execute -> outcome evidence.

It exists to close the trust gap between probabilistic agent decisions and deterministic execution.

## What SudoAgent is not

- Not an agent framework or orchestrator.
- Not a workflow engine.
- Not full IAM/RBAC/SSO.
- Not a sandbox or isolation layer.

## Quickstart

Install:

```bash
pip install sudoagent
```

Run a demo:

```bash
python examples/quickstart.py
sudoagent verify sudo_ledger.jsonl
```

## Core concepts (plain language)

- Policy: deterministic gate returning ALLOW, DENY, or REQUIRE_APPROVAL.
- Approver: optional human/system gate (interactive by default).
- Ledger: tamper-evident evidence with hash chaining.
- Audit log: operational record for debugging; not tamper-evident.
- Decision hash: binds approval and outcome to a specific decision.
- Reason codes: stable, searchable failure/approval categories.

## Two output files

By default SudoAgent writes:

- `sudo_audit.jsonl`: operational record; not tamper-evident.
- `sudo_ledger.jsonl`: tamper-evident evidence; verifiable with `sudoagent verify`.

## Multi-agent usage (recommended conventions)

Use a stable `agent_id` that encodes ownership:

- `team:service:instance`
- Examples: `payments:refund-bot:prod-01`, `support:triage:staging`

Budgets can be set per agent or per tool; policies can branch on `ctx.metadata["agent_id"]`.

## Approval patterns (sync + async)

Recommended patterns:
- CLI prompt (dev/demo, sync)
- Polling/webhook approver (async service paths)
- Slack or HTTP approver (custom)
- Auto-approve in CI or demos via environment variable

Timeout handling:
- Approver should enforce a timeout.
- On timeout: deny and log `APPROVAL_PROCESS_FAILED`.
- Agent may retry with a new request_id.

Engine choice:
- Use `AsyncSudoEngine` in async runtimes (FastAPI/aiohttp/Jupyter).
- Use `SudoEngine` in sync runtimes; it wraps the async core.
- `SudoEngine` defaults to a JSONL ledger at `sudo_ledger.jsonl` (or pass a ledger / set `SUDOAGENT_LEDGER_PATH`).

## Policy versioning (best practice)

Include a version in `policy_id`:

- Good: `RefundPolicy:v2`
- Avoid: `RefundPolicy`

Ledger entries store `policy_id` and `policy_hash` at decision time, so historical evidence remains valid even after policy changes.

## JSONL vs SQLite (which to choose?)

- JSONL ledger: simple, inspectable, single-writer. Good for local/dev and many production cases.
- SQLite WAL ledger: better for multi-process on one host and richer queries.

## Signing (optional)

Signing adds `entry_signature` to ledger entries:

```bash
pip install "sudoagent[crypto]"
sudoagent keygen --private-key keys/private.pem --public-key keys/public.pem
sudoagent verify sudo_ledger.jsonl --public-key keys/public.pem
```

## Troubleshooting

Install issues:
- Use Python 3.10+
- Upgrade pip: `python -m pip install -U pip`
- For signing tests: `pip install "sudoagent[crypto]"`

Verify fails:
- Ledger may be edited or truncated.
- Check that canonical JSON is intact (no manual edits).

## Latency and performance

SudoAgent adds measurable latency because it writes durable evidence (decision + outcome)
to disk. On a typical dev laptop with local SSD:

- JSONL ledger: ~45-70 ms per call (p50-p95)
- SQLite WAL ledger: ~39-60 ms per call (p50-p95)
- Approval path (auto-approve): ~46-86 ms (p50-p95)

This is expected: each guarded call performs two durable writes and hash chaining.
For high-stakes actions (refunds, infra changes), this overhead is usually acceptable.
For ultra-low-latency paths, use policy to allow the call without approval, or avoid
guarding those paths.

Tips to reduce latency:

- Prefer SQLite WAL over JSONL for multi-process.
- Use fast local SSD (avoid network filesystems).
- Disable signing unless required.
- Guard only high-risk actions.

## Where to read next

- Architecture: `docs/architecture.md`
- Ledger guide: `docs/v2_ledger.md`
- Quickstart: `docs/quickstart.md`
- FAQ: `docs/faq.md`
- Adapters: `docs/adapters.md`

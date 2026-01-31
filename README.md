# sudoagent

<p align="center">
  <img src="https://raw.githubusercontent.com/lemnk/Sudo-agent/main/docs/sudoagent_logo.png" width="120" alt="SudoAgent Logo" />
</p>

<p align="center">
  <a href="https://github.com/lemnk/Sudo-agent/actions/workflows/ci.yml">
    <img src="https://github.com/lemnk/Sudo-agent/actions/workflows/ci.yml/badge.svg" alt="CI" />
  </a>
  <a href="https://pypi.org/project/sudoagent/">
    <img src="https://img.shields.io/pypi/v/sudoagent.svg" alt="PyPI" />
  </a>
  <a href="https://pypi.org/project/sudoagent/">
    <img src="https://img.shields.io/pypi/pyversions/sudoagent.svg" alt="Python versions" />
  </a>
  <a href="https://pypi.org/project/sudoagent/">
    <img src="https://img.shields.io/pypi/dm/sudoagent.svg" alt="PyPI - Downloads" />
  </a>
  <a href="https://pepy.tech/project/sudoagent">
    <img src="https://pepy.tech/badge/sudoagent" alt="Downloads (pepy)" />
  </a>
  <a href="https://github.com/lemnk/Sudo-agent">
    <img src="https://img.shields.io/github/stars/lemnk/Sudo-agent.svg?style=social" alt="GitHub stars" />
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/pypi/l/sudoagent.svg" alt="License" />
  </a>
</p>

SudoAgent is the smallest possible boundary that gives you verifiable, fail-closed control (policy/approvals/budgets) plus tamper-evident evidence and receipts—so you don’t have to re-implement and re-audit that stack in every service.

Version: 2.0.0 (v2 ledger/verification)

## Who is this for?

- Teams letting agents or automation call real systems (payments, prod data, infra) and need a fail-closed boundary.
- Engineers who want proof an action was authorized (and, if required, approved) before it executed.
- Security/ops who need tamper-evident evidence they can verify later.
- If you already have budgets, approvals, tamper-evident logging, receipts, and verification wired correctly across your services, you don’t need SudoAgent.

## What it is / isn’t
- It is: a synchronous authorization boundary around tool/function calls with deterministic redaction and a tamper-evident ledger.
- It is not: an agent orchestrator, scheduler, or sandbox. Policies are Python today for determinism; signed policy bundles (OPA/Rego or YAML) are a roadmap item for code-less changes.

## Repository map (start here)

- `src/sudoagent/` — core SDK (engine, ledger backends, budgets, approvals, adapters).
- `examples/` — runnable demos (quickstart, workflow demo).
- `tests/` — pytest suite (engine, ledger verification, adapters).
- `docs/` — guides and references (quickstart, OSS guide, ledger spec, architecture, FAQ).
- `gateway/` — _reserved for future control-plane work_ (not present today).

## Start here (docs)

- Quick intro: [`docs/quickstart.md`](docs/quickstart.md)
- OSS overview: [`docs/oss_guide.md`](docs/oss_guide.md)
- How the ledger works: [`docs/v2_ledger.md`](docs/v2_ledger.md)
- Architecture: [`docs/architecture.md`](docs/architecture.md)
- Operations/FAQ: [`docs/faq.md`](docs/faq.md)

## What it does

SudoAgent wraps a function call and enforces one of three outcomes:

- **allow**: execute immediately
- **deny**: block the call, raise `ApprovalDenied`
- **require_approval**: request approval; executes only if approved

Defaults (dev-friendly / quickstart):
- Audit log: `sudo_audit.jsonl` (operational record; not tamper-evident)
- Ledger: `sudo_ledger.jsonl` (tamper-evident but dev-only; single-writer, local)
- Budgets/approvals: in-memory

Recommended default for real use or multi-process on one host:
- Evidence: `SQLiteLedger(Path("sudo_ledger.sqlite"))` (WAL, fsync)
- Budgets: `from sudoagent.budgets import persistent_budget` and pass `budget_manager=persistent_budget("budgets.sqlite", agent_limit=..., tool_limit=...)`
- Approvals: `approval_store=SQLiteApprovalStore(Path("approvals.sqlite"))` for durable state/timeouts

Sharding guidance: use one ledger file per domain/env (e.g., `ledgers/prod-payments.sqlite`, `ledgers/prod-support.sqlite`) to avoid a global mutex and keep verification fast.

## How it works

1. You create a `SudoEngine` with a required policy.
2. You decorate functions with `@sudo.guard()` or call `sudo.execute(func, ...)`.
3. The engine evaluates the policy, optionally invokes the approver, writes the decision to the ledger + audit log, and then executes (or denies).

Key behavior:
- Decision logging happens *before* execution and is fail-closed. If logging fails, execution is blocked and `AuditLogError` is raised.
- Outcome logging happens *after* execution and is best-effort. Logging failures do not affect the return value.
- Approved actions produce two audit entries (decision + outcome). Denied actions produce one (decision only).
- Entries for the same call are linked by `request_id` (UUID4).
- Audit entries include timestamp, action, decision, reason, and safe representations of args/kwargs.

See [docs/architecture.md](docs/architecture.md) for the full execution flow and audit semantics.

## Install

```bash
pip install sudoagent
```

Optional extras:
- Signing / receipts: `pip install "sudoagent[crypto]"`
- Adapters: `pip install "sudoagent[langchain]"`, `pip install "sudoagent[crewai]"`, `pip install "sudoagent[autogen]"`
- SQLite helpers (if you prefer explicit deps): standard library only; no extra install required.

Dev install:

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Quickstart

Run the demo:

```bash
python examples/quickstart.py
```

What happens:
- A low-value refund is allowed automatically.
- A high-value refund triggers an interactive approval prompt.
- Decisions/outcomes are written to `sudo_audit.jsonl` and `sudo_ledger.jsonl` (dev-only path for the demo).

Prefer SQLite for anything real:
```bash
SUDOAGENT_LEDGER=sqlite python examples/workflow_demo.py  # or instantiate SQLiteLedger in your code
```

For a 5-minute walkthrough and production checklist, see [docs/quickstart.md](docs/quickstart.md).
OSS guide: [docs/oss_guide.md](docs/oss_guide.md).
FAQ / gotchas: [docs/faq.md](docs/faq.md) (includes asyncio guidance).

Full workflow demo (approval + budgets + verify):

```bash
SUDOAGENT_AUTO_APPROVE=1 python examples/workflow_demo.py
sudoagent verify sudo_ledger.jsonl
```

v2 ledger demo (decision_hash + verification):

```bash
python examples/v2_demo.py
sudoagent verify sudo_ledger.jsonl
# Or JSON output
sudoagent verify sudo_ledger.jsonl --json
```
(The demo writes `sudo_ledger.jsonl` in the current directory; delete it between runs if you want a fresh ledger.)

CLI export/filter/search:

```bash
sudoagent export sudo_ledger.jsonl --format json
sudoagent filter sudo_ledger.jsonl --request-id <id>
sudoagent search sudo_ledger.jsonl --query refund_user
```

Signing and receipts:

```bash
pip install "sudoagent[crypto]"
sudoagent keygen --private-key keys/private.pem --public-key keys/public.pem
sudoagent verify sudo_ledger.jsonl --public-key keys/public.pem
sudoagent receipt sudo_ledger.jsonl --request-id <id>
```

To run non-interactively (CI/demo):

```bash
SUDOAGENT_AUTO_APPROVE=1 python examples/quickstart.py
```

On Windows PowerShell:

```powershell
$env:SUDOAGENT_AUTO_APPROVE="1"; python examples/quickstart.py
```

## Examples at a glance
- `examples/quickstart.py`: allow + approval using JSONL defaults.
- `examples/v2_demo.py`: shows the v2 ledger hashing/verification flow.
- `examples/workflow_demo.py`: approval + budgets + verification; set `SUDOAGENT_AUTO_APPROVE=1` to auto-approve in CI.

## Basic usage

```python
from sudoagent import ApprovalDenied, Context, Decision, PolicyResult, SudoEngine

class HighValueRefundPolicy:
    def evaluate(self, ctx: Context) -> PolicyResult:
        refund_amount = ctx.kwargs.get("refund_amount", 0)
        if refund_amount <= 500:
            return PolicyResult(decision=Decision.ALLOW, reason="within limit")
        return PolicyResult(decision=Decision.REQUIRE_APPROVAL, reason="over limit")

policy = HighValueRefundPolicy()
sudo = SudoEngine(policy=policy)

@sudo.guard()
def refund_user(user_id: str, refund_amount: float) -> None:
    print(f"Refunding {refund_amount} to {user_id}")

refund_user("user_1", refund_amount=10.0)

try:
    refund_user("user_2", refund_amount=1500.0)
except ApprovalDenied as e:
    print(f"Denied: {e}")
```

## Core concepts

- **Context**: captures the function call (action name, redacted args/kwargs, metadata).
- **Policy**: returns `ALLOW`, `DENY`, or `REQUIRE_APPROVAL` with a reason.
- **Approver**: handles the approval step. Default is `InteractiveApprover` (terminal y/n).
- **AuditLogger**: writes audit entries. Default is `JsonlAuditLogger`.
- **Budgets**: optional rate limits via `BudgetManager` (pass `budget_cost` to `execute`/`guard` for spend accounting). Use `persistent_budget(...)` for durable counters.
- **Fail-closed**: if policy, approval, or decision logging fails, execution is blocked.
- **decision_hash**: SHA-256 over canonical decision payload (request_id, intent, parameters, actor, policy_hash).
- **policy_id**: stable policy identifier (class name by default).
- **policy_hash**: SHA-256 over canonicalized policy identifier (class name by default).
- **Ledger schema**: entries include `schema_version`, `ledger_version`, `agent_id`, `policy_id`, `policy_hash`, and redacted args/kwargs metadata.
- **Ledger verification**: `sudoagent verify <ledger_path>` checks schema/ledger versions, hash chain, and decision_hash references.

## Reason codes

Stable, searchable reason codes are emitted in decision metadata and ledger entries:
- `POLICY_ALLOW_LOW_RISK`
- `POLICY_DENY_HIGH_RISK`
- `POLICY_REQUIRE_APPROVAL_HIGH_VALUE`
- `POLICY_EVALUATION_FAILED`
- `BUDGET_EXCEEDED_AGENT_RATE`
- `BUDGET_EXCEEDED_TOOL_RATE`
- `BUDGET_EVALUATION_FAILED`
- `APPROVAL_DENIED`
- `APPROVAL_PROCESS_FAILED`
- `LEDGER_WRITE_FAILED_DECISION`

## Security

- Threat model: see [THREAT_MODEL.md](THREAT_MODEL.md).
- Security policy: see [SECURITY.md](SECURITY.md).
- Rich markup in approval prompts is escaped to prevent terminal injection.
- Redaction is centralized and applied before policy evaluation, approval prompts, and ledger hashing.
- Audit logging redacts sensitive key names (`api_key`, `token`, `password`, etc.) and values (JWT-like strings, `sk-` prefixes, PEM blocks).
- Decision logging failures raise `AuditLogError` and block execution. Outcome logging failures do not block.
- Denied actions log the decision only. Approved actions log decision and outcome, linked by `request_id`.
- SudoAgent is not a sandbox; protect the host and secrets separately.

Example audit entries:
```json
{"event":"decision","request_id":"...","action":"...","decision":"allow","reason":"within limit",...}
{"event":"outcome","request_id":"...","outcome":"success",...}
```

Limitations:
- This is not a sandbox. Side effects inside the guarded function are not prevented.
- The default audit log (`sudo_audit.jsonl`) is not tamper-evident and is intended for single-process use.
- The default JSONL ledger (`sudo_ledger.jsonl`) is single-writer; for multi-process on one host, use `SQLiteLedger`.

## Extending

SudoAgent is designed for dependency injection:
- Implement `Policy.evaluate(ctx) -> PolicyResult`.
- Implement `Approver.approve(ctx, result, request_id) -> bool` (Slack/UI/etc.).
- Implement `Ledger` for custom evidence stores.
- Implement `AuditLogger` for operational logging sinks.

Notes:
- Policy is required at construction. Pass `AllowAllPolicy()` explicitly for permissive mode.
- `InteractiveApprover` is intended for local development. For production, implement a custom approver.
- For persistence: prefer `SQLiteLedger`, `persistent_budget`, and `SQLiteApprovalStore` in multi-process or long-running scenarios.

Adapters:
- LangChain: `pip install "sudoagent[langchain]"` + [docs/adapters.md](docs/adapters.md)
- CrewAI: `pip install "sudoagent[crewai]"`
- AutoGen: `pip install "sudoagent[autogen]"`

## Roadmap

See [ROADMAP.md](ROADMAP.md) for a short, best-effort plan.

Big picture:
- OSS “embedded engine” stays: synchronous guard + tamper-evident ledger, local by default, SQLite recommended for multi-process.
- Future “gateway/control plane” (commercial) will layer on: multi-host ledger, richer approvals, SIEM/export integrations, hosted ops. No timelines or promises here; OSS remains usable on its own.

## Support policy

We support the latest minor release line. See [SUPPORT.md](SUPPORT.md) for details.

## Contributing

Small PRs are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

```bash
pytest -q
ruff check .
mypy src
```

## License

MIT License. See LICENSE.

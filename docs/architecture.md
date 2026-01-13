# Architecture

SudoAgent is a small runtime guard for sensitive operations. It enforces **policy decisions**, optional **human approval**, and **append-only audit logging** at the moment side effects would occur.

The core idea: **make "should this run?" a first-class runtime decision**.

---

## One-page mental model

Think of SudoAgent as `sudo` for function calls:

- **Policy** answers: *Should this run?* (`ALLOW` / `DENY` / `REQUIRE_APPROVAL`)
- **Approver** answers: *If approval is required, do we proceed?* (yes/no)
- **AuditLogger** records: *What decision happened and why?*

Key invariant: **if anything goes wrong, the action does not execute.**

### Minimal flow

```
call → Context → Policy → (ALLOW | DENY | REQUIRE_APPROVAL)
                            |       |
                            |       └→ raise ApprovalDenied
                            |
                            └→ Approver → (approved? yes → execute, no → raise ApprovalDenied)
                                        |
                                        └→ AuditLogger (must succeed or block)
```

### What you get out of the box

- A decorator: `@sudo.guard(policy=...)`
- An engine API: `engine.execute(func, *args, **kwargs)`
- Default interactive approval in terminal
- Default JSONL audit log

---

## Goals

### Primary goals (v0.1)
- **Runtime enforcement** of allow/deny/approval for sensitive operations.
- **Fail-closed** behavior across policy, approval, and logging.
- **Auditable decisions** written to an append-only log.
- **Small surface area** and minimal coupling to app/framework.

### Non-goals (v0.1)
- Sandboxing, isolation, or preventing side effects inside guarded functions.
- Distributed approvals (Slack/email) as built-in defaults.
- Async orchestration or multi-step workflows.
- A policy DSL, rules engine, or "policy hub".

---

## Components

### SudoEngine
Orchestrates policy evaluation, optional approval, and audit logging.

Responsibilities:
- Build `Context` from function call
- Call `Policy.evaluate(ctx)`
- If required, call `Approver.approve(ctx, result, request_id)`
- Write an audit entry for every decision
- Execute the function only when allowed

Non-responsibilities:
- It does not interpret business logic
- It does not catch exceptions from the guarded function (caller owns that)
- It does not attempt to redact secrets inside *return values* or *side effects*

### Context
A snapshot of a pending action.

- `action`: fully-qualified callable name (`module.qualname`)
- `args`: positional args tuple
- `kwargs`: keyword args dict
- `metadata`: reserved for user/system enrichment (trace_id, agent_id, etc.)

Policies should treat `Context` as read-only input.

### Policy
A small interface that returns a `PolicyResult`:
- `decision`: `ALLOW` / `DENY` / `REQUIRE_APPROVAL`
- `reason`: human-readable reason suitable for approval UIs and audit logs

Constraints (by design):
- Policies should be deterministic and side-effect-free.
- Policies should not perform I/O in v0.1 (keep it testable and predictable).

### Approver
Approvers are invoked only when decision is `REQUIRE_APPROVAL`.

Default: `InteractiveApprover` (terminal prompt).  
Custom approvers may integrate with Slack, email, ticketing, or headless deny.

### AuditLogger
Records decisions as `AuditEntry` objects.

Default: JSONL append-only log.  
Custom loggers may write to stdout, SQLite, Postgres, SIEM, etc.

Audit logging is **part of enforcement**: if logging fails, execution is blocked.

---

## Data flow (detailed)

### Sequence diagram

```
Caller
  |
  | call guarded function
  v
SudoEngine.guard wrapper
  |
  | builds Context(action,args,kwargs,metadata)
  v
Policy.evaluate(ctx)
  |
  | returns PolicyResult(decision, reason)
  v
SudoEngine decision switch
  |
  | ALLOW ------------------------------+
  |                                      |
  |   AuditLogger.log(entry)            |
  |   (must succeed)                    |
  |                                      v
  |   execute func(*args, **kwargs) --> return
  |
  | DENY ------------------------------+
  |                                     |
  |   AuditLogger.log(entry)           |
  |   (must succeed)                   |
  |                                     v
  |   raise ApprovalDenied(reason)
  |
  | REQUIRE_APPROVAL ------------------+
  |
  |   generate request_id
  v
Approver.approve(ctx, result, request_id)
  |
  +--> approved=True
  |      |
  |      | AuditLogger.log(entry) (must succeed)
  |      v
  |      execute func(*args, **kwargs) --> return
  |
  +--> approved=False
         |
         | AuditLogger.log(entry) (must succeed)
         v
         raise ApprovalDenied(reason)
```

---

## Enforcement & failure policy

SudoAgent is designed to be safe by default:

### Fail-closed guarantees
- If `Policy.evaluate` raises → decision treated as **DENY**
- If `Approver.approve` raises or is interrupted (Ctrl+C / EOF) → **DENY**
- If `AuditLogger.log` raises → **block execution** (raise `AuditLogError`)

This trades availability for correctness: a safety layer should not "best effort" its way into accidental execution.

---

## Audit log semantics

### What gets logged
An audit entry contains:
- timestamp (timezone-aware)
- action identifier
- decision
- reason
- metadata (including safe representations of args/kwargs, request_id when relevant)

### Safe serialization
Because arguments can be arbitrary objects:
- args/kwargs are converted using safe `repr` with truncation
- keyword keys that look like secrets are redacted (e.g. `api_key`, `token`, `password`)

### Ordering
Audit logging occurs **before execution** on allow paths:
- If the action executes, there is already a record that it was allowed.
- If logging fails, the action does not execute.

---

## Security model (v0.1)

SudoAgent assumes:
- The guarded function is trusted code, but its inputs may be untrusted (agent/user controlled).
- Attackers may attempt to:
  - trick approvers via terminal markup
  - leak secrets through logs
  - bypass approvals via error paths

SudoAgent explicitly defends against:
- terminal markup injection in the interactive approver (escape output)
- accidental logging of common secret keys (redaction)
- unintended execution on exceptions (fail-closed everywhere)

SudoAgent does not claim to defend against:
- a malicious local user with full filesystem access
- sandbox escape / process isolation problems
- side effects inside the guarded function (that's your code)

(See `SECURITY.md` for reporting and scope.)

---

## Extensibility (how plugins fit)

The extension points are intentionally simple and stable:

- **Policies**: decide allow/deny/approval
- **Approvers**: decide whether to proceed when approval is required
- **AuditLoggers**: persist decisions

Design choice: extension is done via dependency injection (constructor args), not global registries.
This keeps behavior predictable and avoids hidden plugin loading.

---

## "Why not X?" (design tradeoffs)

### Why not rely on prompts / agent instructions?
Because prompts are not enforcement. SudoAgent guards execution at the point where side effects happen.

### Why not auto-approve on errors ("best effort")?
Because safety tools must fail closed. "Best effort allow" is a bypass.

### Why not async in v0.1?
Async adds complexity and multiplies edge cases (cancellation, timeouts, event loops, concurrency).
v0.1 focuses on correctness and predictable semantics first.

### Why not a policy DSL / rules engine?
A DSL increases surface area and ambiguity. v0.1 keeps policies as plain Python for transparency and testability.

### Why not ship Slack/email approvals built-in?
Integrations bring operational dependencies and security considerations.
Instead, the approver interface supports these as external extensions without bloating core.

### Why not persist state / approvals in a database?
Stateful approvals imply workflows, retries, and distributed coordination.
v0.1 keeps approvals synchronous and local to keep behavior straightforward.

---

## Versioning expectations

v0.1 focuses on stabilizing:
- core types (`Context`, `PolicyResult`, `Decision`, `AuditEntry`)
- engine behavior (fail-closed semantics)
- extension interfaces (Policy, Approver, AuditLogger)

Anything beyond that (async, distributed approvals, richer policy composition) should be considered future work and may live under `experimental/` if introduced.

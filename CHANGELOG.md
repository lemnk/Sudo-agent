# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-01-28

### Added
- Fail-closed runtime pipeline: policy → (optional) approval → (optional) budgets → execution.
- Tamper-evident ledgers with hash chaining; JSONL backend (default) and SQLite WAL backend.
- Optional Ed25519 signing/verification and receipt export via CLI.
- Adapters for LangChain, CrewAI, and AutoGen with lazy imports and optional extras.
- Deterministic redaction shared across policy, approval, and evidence; stable reason-code taxonomy.
- CLI export/filter/search/verify subcommands plus keygen and receipt commands.
- Documentation: quickstart, adapters guide, v2 ledger spec, OSS guide, threat model, FAQ.
- Tests: expanded ledger/CLI/signing coverage; CI installs dev+crypto extras.
- RFC 8785 (JCS) canonicalization for all hashed/signed payloads with golden vectors.
- Engine orchestration refactor (execute split into helpers, fail-closed logging).
- Durable state helpers: SQLite budget manager (`persistent_budget`) and SQLite approval store.
- Repo hygiene: tightened `.gitignore`, removed committed artifacts, pre-commit + Definition of Done.
- Benchmark helper (`bench_latency.py`) for local latency measurement.

### Breaking
- v1 ledger and API semantics replaced by v2 schema/versioning (see `docs/v2_ledger.md`).

## [0.2.0] - 2026-01-24

### Added
- Canonical JSON encoding and SHA-256 hashing utilities for deterministic payloads.
- Tamper-evident JSONL ledger with hash chaining, locking, and strict verification.
- Decision/outcome ledger integration with `decision_hash`, `policy_hash`, and `reason_code`.
- Approval binding validation tied to `{request_id, policy_hash, decision_hash}`.
- Budget manager with Check -> Commit semantics and engine enforcement.
- CLI verification command: `sudoagent verify <ledger_path>` with `--json` output.
- CLI export/filter/search commands plus signing keygen and receipt tooling.
- SQLite WAL ledger backend with chain verification.
- Adapter wrappers for LangChain, CrewAI, and AutoGen with examples and docs.
- v2 demo and ledger documentation.
- Hardening tests for partial lines, hash mismatches, sequential multi-handle appends, and deterministic redaction.

### Changed
- Audit logging now writes to the ledger in addition to the existing audit logger.
- Policy evaluation now emits deterministic decision hashes for binding and verification.

## [0.1.1] - 2026-01-22

### Added
- **Decision + outcome audit entries** for allowed executions: decision is logged before execution and outcome is logged after, correlated by `request_id` (UUID4).
- **Secret redaction improvements**: redaction applies to sensitive key names and secret-like values (JWT-like strings, common token prefixes, PEM blocks), including positional arguments.
- **Quickstart non-interactive mode**: `SUDOAGENT_AUTO_APPROVE=1` to auto-approve approval-required actions in the demo.
- **Documentation**: added a README diagram and notes on JSONL logger single-process expectations.

### Changed
- **Policy is required**: `SudoEngine(policy=...)` must be provided a policy at construction (pass `AllowAllPolicy()` explicitly for permissive mode).
- **Audit semantics**: decision logging is fail-closed (logging failures raise `AuditLogError` and block execution); outcome logging is best-effort.

### Fixed
- **Thread safety**: `guard(policy=...)` no longer mutates engine policy state; it passes a per-call policy override.
- **Quickstart example** updated for the required policy constructor.

## [0.1.0] - 2026-01-20

### Added
- Initial release with core functionality:
  - `SudoEngine` with policy evaluation, approval, and audit logging
  - `InteractiveApprover` for terminal-based approval
  - `JsonlAuditLogger` for JSONL audit logging
  - `AllowAllPolicy` and `DenyAllPolicy`
  - Basic sensitive key-name redaction

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

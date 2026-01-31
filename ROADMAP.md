# Roadmap

This is a lightweight, best-effort view of near-term work for the OSS engine.

## Near term
- Harden SQLite as the recommended backend (sharding guidance, checkpoints, verification tooling).
- Add more export formats for SIEM/GRC ingestion.
- Add reference approvers (HTTP webhook, Slack) in examples.
- Improve ledger tooling for large files (streaming export/verify).

## Longer term
- Pluggable storage backends beyond JSONL/SQLite.
- Distributed verification patterns.
- Optional gateway/control-plane offering (commercial) for multi-host deployments, richer approvals, and SIEM/export integrations. OSS engine remains a standalone option.

## Non-goals (v2)
- Agent orchestration or scheduling.
- Sandboxing or process isolation.

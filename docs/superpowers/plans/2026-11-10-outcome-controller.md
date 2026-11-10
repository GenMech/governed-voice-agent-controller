# Outcome Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete an auditable, crash-safe controller that finishes public_01 and public_02 and reports load performance.

**Architecture:** A single HTTP-driven loop streams chunks into SQLite aggregates. Strategy modules produce evidence-bound candidate changes; a governance state machine sends and reconciles them before applying. All local effects are journaled.

**Tech Stack:** Python 3.12, httpx, SQLite, pytest.

**Spec:** `README.md`, `docs/SIMULATOR.md`, and `docs/DECISIONS.md`.

## Global Constraints

- The controller reads only HTTP data; never import `sim` or parse scenario files.
- Preserve separate pickup and engagement KPIs and each workflow's primary and guardrail.
- Every controller change passes approval or policy-permitted auto-apply.
- `./run.sh <SIM_URL>` runs to completion without manual steps.
- Commit after milestones with concise tagged messages and no Codex name.

## Review Focus

- Restart after `/sim/advance` but before ingest must recover the omitted chunk.
- Restart after proposal POST must rediscover the approval by proposal ID.
- Supervisor edits between proposal and apply must prevent a stale overwrite.
- An approval that expires or lapses must not block future decisions forever.
- Large chunks must not be materialized as one JSON list.

---

### Task 1: State and ingestion

**Files:** `controller/api.py`, `controller/store.py`, `tests/test_controller_store.py`.

**Interfaces:** `Api` wraps HTTP; `Store.ingest_chunk(chunk_id, lines)` commits aggregates and cursor; `Store.calls(...)` reads counters.

- [ ] Write tests for idempotent ingest, crash cursor, and aggregate denominators.
- [ ] Run tests and observe expected failures.
- [ ] Implement streaming API and transactional SQLite store.
- [ ] Run full tests and commit `feat: add durable event ingestion`.

### Task 2: Statistical strategy

**Files:** `controller/stats.py`, `controller/strategy.py`, `tests/test_strategy.py`.

**Interfaces:** `choose_change(workflow, config, observations, state)` returns a candidate or `None` with rationale and metrics.

- [ ] Write tests for sample limits, primary lift, guardrail rejection, caller-ID degradation, and incident thresholds.
- [ ] Run tests and observe expected failures.
- [ ] Implement deterministic candidate selection, preserving other config fields.
- [ ] Run full tests and commit `feat: add guarded decision rules`.

### Task 3: Governance and loop

**Files:** `controller/governance.py`, `controller/loop.py`, `controller/__main__.py`, `run.sh`, `tests/test_governance.py`.

**Interfaces:** `Governance.process(wid, candidate, ...)` persists intents and reconciles approvals; `Controller.run()` drives simulated time to finished.

- [ ] Write tests for approval lifecycle, duplicate intent recovery, stale base, and completed run.
- [ ] Run tests and observe expected failures.
- [ ] Implement governance and loop.
- [ ] Run full tests and commit `feat: complete governed controller loop`.

### Task 4: Evidence and submission

**Files:** `SUBMISSION.md`, `reports/`, `scripts/crash_recovery.sh`, `docs/DECISIONS.md`.

- [ ] Run baselines, public scenarios, and load run; inspect grades and tune only general rules.
- [ ] Kill and restart a run; record audit query and performance numbers.
- [ ] Fill submission template including six stakeholder replies and scope cuts.
- [ ] Verify tests, reports, and documents; commit `docs: record results and tradeoffs`.

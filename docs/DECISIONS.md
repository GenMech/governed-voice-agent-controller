# Engineering decisions

This is the record of choices made for this submission. `SUBMISSION.md` reports measured outcomes and trade-offs after the runs.

| ID | Decision | Reason | Cost / revisit trigger |
|---|---|---|---|
| D01 | Python 3.12, `httpx`, standard-library SQLite; no new production dependencies. | Matches the starter, works on the grader's Linux box, and keeps the operational footprint small. | Python's JSON parsing may become the first bottleneck at 10× load. |
| D02 | One controller process owns the simulator clock and polls every 60 simulated minutes, with 15-minute ticks while an approval is pending. | The simulator advances only when asked. Shorter ticks around approvals reduce expiry and incident lag. | More HTTP round trips; the production clock would be external. |
| D03 | Stream NDJSON chunks and commit each chunk's aggregates and cursor in one SQLite transaction. | Bounded memory, restartable ingestion, and no duplicate counts after a crash. List chunks on every restart to recover advances committed by the simulator but not ingested locally. | SQLite writes are single-process; partition by workflow for production. |
| D04 | Store aggregate call counts by workflow, config version, cohort, hour, and variant; keep an append-only decision and governance journal. | Supports tests, guardrails, and the audit question without retaining millions of lead records. | No individual-level call-time optimization or full customer-level audit. |
| D05 | Use the simulator's cohort IDs; do not invent new cohorts in this time box. | Avoids fragmented samples and preserves a single cohort meaning across observations and config. | Leaves cohort-specific lift on the table. |
| D06 | Keep pickup and engagement denominators separate. Select variants only with >=150 connected calls per arm, a two-sided pooled z score >=3.29, and a guardrail check. | Prevents single-call reactions and reduces false winner claims to roughly 0.1% per look under the null. | Conservative thresholds delay promotion; repeated looks and variant searches still lack a formal familywise guarantee. |
| D07 | One active change per workflow, with persisted proposal intent before sending. Reconcile uncertain responses from `/approvals` and config history. | Avoids duplicate applications and lost approvals after crashes. | Serializes otherwise independent improvements. |
| D08 | Auto-apply only when explicitly permitted by live workflow policy and shift limit. Use approval for all other changes; never overwrite a supervisor version. | Governance is a hard boundary. | Approval latency lowers short-run lift. |
| D09 | Reserve credits for incident response; ask the LLM only after a population-level hallucination signal, then validate candidates. | Credits are finite and validation measures safety rather than engagement. | Slow reaction to small incidents. |
| D10 | Keep `sim/` and scenario files outside controller imports and reads. | Hidden truth must stay hidden. All controller knowledge comes from HTTP. | Some simulator internals could make optimization easier but are disallowed. |
| D11 | Cap approval submissions at the live policy's rolling 24-hour limit, with a six-hour normal proposal cooldown; incident proposals may bypass the cooldown. | Keeps approver load bounded while allowing prompt safety response. | One active proposal per workflow can delay an unrelated improvement. |
| D12 | Start untried welcome/voice options at 5% traffic; remove a statistically losing or guardrail-breaking arm. | Limits harm from blind exploration while still producing direct evidence. | Smaller arms reach the 150-connected-call floor more slowly. |

## Module boundaries

- `controller/api.py`: HTTP transport and retry classification.
- `controller/store.py`: SQLite schema, chunk transactions, cursor, journal, proposal state.
- `controller/stats.py`: bounded aggregate queries and deterministic statistical tests.
- `controller/strategy.py`: generate candidate changes from observations and policy.
- `controller/governance.py`: submit, reconcile, apply, and audit proposals.
- `controller/loop.py`: bootstrap, ingest, advance, and orchestration.
- `controller/__main__.py`: CLI and configuration.

## Deferred deliberately

Per-person schedules, a UI, synthetic cohort creation, cross-tenant transfer, and a distributed queue. These are not required for the floor and each needs its own quality and operational argument.

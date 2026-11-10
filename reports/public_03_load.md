# public_03_load performance

Measured on this Apple Silicon macOS host with the simulator and controller on the same machine. This is not a 4-vCPU Linux measurement.

```sh
.venv/bin/python -m sim serve --scenario scenarios/public_03_load.yaml \
  --run-dir runs/final_public_03 --force
env CONTROLLER_DB=runs/final_public_03.sqlite /usr/bin/time -l \
  ./run.sh http://127.0.0.1:8700
```

| Measure | Result |
|---|---:|
| Total events ingested, including pre-D0 history | 9,737,610 |
| Total wall time, including bootstrap | 48.40 s |
| Overall ingest throughput | ~201,000 events/s |
| Maximum resident set size (`time -l`) | 41,467,904 bytes (~39.5 MiB) |
| SQLite database file after run | 1,712,128 bytes |
| Chunk count / largest chunk | 124 / 250,000 events |
| Wall time per simulated day after bootstrap | roughly 6–8 s |
| Decision lag | bounded by the 60-minute polling step; 15 minutes while approvals are active |

The controller ingests every returned chunk before advancing again, so it did not accumulate a simulator event backlog. The lag figure is an architectural bound, not a separately instrumented latency percentile. At 10×, HTTP NDJSON serialization and a single SQLite writer would be the likely first bottlenecks. Production should partition workflow ownership and move the persistent state to existing Postgres; benchmark that design on the required 4-vCPU / 8 GB Linux target before a production claim.

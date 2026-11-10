# Crash-recovery evidence

Command, with a fresh `public_01_dev` simulator running at `:8700`:

```sh
CONTROLLER_DB=runs/final_crash_v2.sqlite \
  scripts/crash_recovery.sh http://127.0.0.1:8700
```

Observed output:

```text
killed controller at simulated minute 645
restart finished at minute 11520
chunks: 118
pending intents: 0
duplicate config applications: 0
applied intents matched in config history: 2 / 2
```

The script sends SIGKILL while the simulator remains alive, then launches `run.sh` again with the same SQLite file. It compares applied proposal IDs in the local journal with the simulator's HTTP config history. This verifies one kill point; it does not prove every possible instruction-boundary crash.

"""Transactional, bounded event aggregation and controller journal."""

import json
import sqlite3
from collections import defaultdict
from pathlib import Path


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, event_count INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS counts (
            workflow TEXT NOT NULL, cohort TEXT NOT NULL, version INTEGER NOT NULL,
            hour_key TEXT NOT NULL, dimension TEXT NOT NULL, variant TEXT NOT NULL,
            dials INTEGER NOT NULL, connected INTEGER NOT NULL, engaged INTEGER NOT NULL,
            hallucinations INTEGER NOT NULL,
            PRIMARY KEY (workflow, cohort, version, hour_key, dimension, variant)
        );
        CREATE INDEX IF NOT EXISTS counts_lookup ON counts(workflow, dimension, variant, hour_key);
        CREATE TABLE IF NOT EXISTS campaigns (
            campaign_id TEXT PRIMARY KEY, workflow TEXT NOT NULL, leads INTEGER NOT NULL, ts TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, workflow TEXT,
            kind TEXT NOT NULL, detail TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS intents (
            proposal_id TEXT PRIMARY KEY, workflow TEXT NOT NULL, kind TEXT NOT NULL,
            body TEXT NOT NULL, status TEXT NOT NULL, approval_id TEXT, created_ts TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def last_chunk(self) -> int:
        return self.db.execute("SELECT COALESCE(MAX(id), -1) FROM chunks").fetchone()[0]

    def ingest_chunk(self, chunk_id: int, lines) -> bool:
        if self.db.execute("SELECT 1 FROM chunks WHERE id=?", (chunk_id,)).fetchone():
            return False
        aggregate = defaultdict(lambda: [0, 0, 0, 0])
        campaigns = []
        changes = []
        count = 0
        for line in lines:
            if not line:
                continue
            ev = json.loads(line)
            count += 1
            kind = ev["type"]
            if kind == "call":
                for dimension, variant in ev["variant"].items():
                    key = (ev["workflow_id"], ev.get("cohort_id", "default"),
                           ev["config_version"], ev["ts"][:13], dimension, variant)
                    row = aggregate[key]
                    row[0] += 1
                    row[1] += bool(ev["connected"])
                    row[2] += bool(ev["engaged"])
                    row[3] += bool((ev.get("qa") or {}).get("hallucination_flag"))
            elif kind == "campaign_created":
                campaigns.append((ev["campaign_id"], ev["workflow_id"], ev["leads"], ev["ts"]))
            elif kind in ("config_changed", "approval_decided"):
                changes.append((ev["ts"], ev.get("workflow_id"), kind, json.dumps(ev, sort_keys=True)))
        with self.db:
            self.db.executemany("""INSERT INTO counts VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(workflow,cohort,version,hour_key,dimension,variant)
                DO UPDATE SET dials=dials+excluded.dials, connected=connected+excluded.connected,
                engaged=engaged+excluded.engaged, hallucinations=hallucinations+excluded.hallucinations""",
                [(*key, *row) for key, row in aggregate.items()])
            self.db.executemany("INSERT OR IGNORE INTO campaigns VALUES (?,?,?,?)", campaigns)
            self.db.executemany("INSERT INTO journal(ts,workflow,kind,detail) VALUES (?,?,?,?)", changes)
            self.db.execute("INSERT INTO chunks VALUES (?,?)", (chunk_id, count))
        return True

    def counts(self, workflow: str, dimension: str, variant: str, *, since: str = "", version: int | None = None, cohort: str | None = None) -> tuple[int, int, int, int]:
        sql = "SELECT COALESCE(SUM(dials),0),COALESCE(SUM(connected),0),COALESCE(SUM(engaged),0),COALESCE(SUM(hallucinations),0) FROM counts WHERE workflow=? AND dimension=? AND variant=? AND hour_key>=?"
        args = [workflow, dimension, variant, since]
        if version is not None:
            sql += " AND version=?"
            args.append(version)
        if cohort is not None:
            sql += " AND cohort=?"
            args.append(cohort)
        return tuple(self.db.execute(sql, args).fetchone())

    def variants(self, workflow: str, dimension: str, *, since: str = "", version: int | None = None) -> dict[str, tuple[int, int, int, int]]:
        sql = "SELECT variant,SUM(dials),SUM(connected),SUM(engaged),SUM(hallucinations) FROM counts WHERE workflow=? AND dimension=? AND hour_key>=?"
        args = [workflow, dimension, since]
        if version is not None:
            sql += " AND version=?"
            args.append(version)
        sql += " GROUP BY variant"
        return {r[0]: tuple(r[1:]) for r in self.db.execute(sql, args)}

    def journal(self, ts: str, workflow: str | None, kind: str, detail: dict):
        with self.db:
            self.db.execute("INSERT INTO journal(ts,workflow,kind,detail) VALUES (?,?,?,?)",
                            (ts, workflow, kind, json.dumps(detail, sort_keys=True)))

    def meta(self, key: str, value: str | None = None) -> str | None:
        if value is None:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row[0] if row else None
        with self.db:
            self.db.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        return value

    def save_intent(self, proposal_id: str, workflow: str, kind: str, body: dict, ts: str):
        with self.db:
            self.db.execute("INSERT INTO intents VALUES (?,?,?,?,?,?,?)",
                            (proposal_id, workflow, kind, json.dumps(body, sort_keys=True), "prepared", None, ts))
            self.db.execute("INSERT INTO journal(ts,workflow,kind,detail) VALUES (?,?,?,?)",
                            (ts, workflow, "proposal_prepared", json.dumps(body, sort_keys=True)))

    def active_intent(self, workflow: str) -> dict | None:
        row = self.db.execute("""SELECT proposal_id,workflow,kind,body,status,approval_id,created_ts
            FROM intents WHERE workflow=? AND status IN ('prepared','pending','approved')
            ORDER BY created_ts DESC LIMIT 1""", (workflow,)).fetchone()
        if not row:
            return None
        return dict(zip(("proposal_id", "workflow", "kind", "body", "status", "approval_id", "created_ts"),
                        (*row[:3], json.loads(row[3]), *row[4:])))

    def latest_intent_ts(self, workflow: str) -> str | None:
        row = self.db.execute("SELECT MAX(created_ts) FROM intents WHERE workflow=?", (workflow,)).fetchone()
        return row[0]

    def update_intent(self, proposal_id: str, status: str, ts: str, approval_id: str | None = None, detail: dict | None = None):
        with self.db:
            self.db.execute("UPDATE intents SET status=?, approval_id=COALESCE(?,approval_id) WHERE proposal_id=?",
                            (status, approval_id, proposal_id))
            self.db.execute("INSERT INTO journal(ts,workflow,kind,detail) SELECT ?,workflow,?,? FROM intents WHERE proposal_id=?",
                            (ts, "proposal_" + status, json.dumps(detail or {}, sort_keys=True), proposal_id))

    def reset(self):
        with self.db:
            for table in ("chunks", "counts", "campaigns", "journal", "intents", "meta"):
                self.db.execute(f"DELETE FROM {table}")

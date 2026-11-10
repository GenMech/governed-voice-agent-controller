"""Clock ownership, event recovery, and decision orchestration."""

import copy
import json
import time
from datetime import datetime, timedelta

import httpx

from .governance import Governance
from .stats import hallucination_incident
from .strategy import Candidate, choose_change


class Controller:
    def __init__(self, api, store):
        self.api, self.store = api, store
        self.governance = Governance(api, store)
        self.workflows = {}
        self.events = 0
        self.started = time.monotonic()

    def ingest_missing(self):
        cursor = self.store.last_chunk()
        for kind in ("history", "events"):
            chunks = self.api.request("GET", f"/events/chunks?kind={kind}&after={cursor}")
            for chunk in sorted(chunks, key=lambda item: item["chunk"]):
                n = chunk["chunk"]
                if self.store.ingest_chunk(n, self.api.lines(f"/events/chunks/{n}")):
                    self.events += chunk.get("events", 0)
                    cursor = n

    def run(self):
        state = self.api.request("GET", "/sim/state")
        prior = self.store.meta("sim_minute")
        if prior is not None and state["sim_minute"] < int(prior):
            self.store.reset()  # a fresh simulator world reused the same DB path
        self.workflows = {w["workflow_id"]: w for w in self.api.request("GET", "/workflows")}
        self.ingest_missing()
        ticks = 0
        while not state["finished"]:
            now = state["ts"]
            for wid, workflow in self.workflows.items():
                self.governance.reconcile(wid, now)
                if self.store.active_intent(wid):
                    continue
                current = self.api.request("GET", f"/workflows/{wid}/config")
                incident = self._incident_signal(workflow, current, now)
                if incident:
                    if not self.governance.can_propose(workflow, now, urgent=True):
                        continue
                    candidate = self._incident_candidate(workflow, current, state, incident)
                else:
                    candidate = choose_change(workflow, current, self.store, now)
                    if candidate and not self.governance.can_propose(workflow, now, candidate=candidate, current=current):
                        continue
                if candidate:
                    self.governance.propose(workflow, current, candidate, now)
            step = 15 if any(self.store.active_intent(wid) for wid in self.workflows) else 60
            self.api.advance(step, state["sim_minute"])
            state = self.api.request("GET", "/sim/state")
            self.store.meta("sim_minute", str(state["sim_minute"]))
            self.ingest_missing()
            ticks += 1
            if ticks % 24 == 0 or state["finished"]:
                print(json.dumps({"ts": state["ts"], "minute": state["sim_minute"],
                    "last_chunk": self.store.last_chunk(), "ingested_events": self.events,
                    "wall_seconds": round(time.monotonic() - self.started, 2),
                    "credits": state.get("credits_remaining")}), flush=True)

    def _incident_signal(self, workflow, current, now):
        wid = workflow["workflow_id"]
        prompt = current["config"]["prompt_version"]
        since = (datetime.fromisoformat(now) - timedelta(hours=6)).isoformat()[:13]
        observed = self.store.counts(wid, "prompt_version", prompt, since=since)
        historical = self.store.counts(wid, "prompt_version", prompt)
        reference = tuple(a - b for a, b in zip(historical, observed))
        if reference[1] < 300:
            alternatives = self.store.variants(wid, "prompt_version")
            reference = max((row for key, row in alternatives.items() if key != prompt),
                            key=lambda row: row[1], default=reference)
        return observed if hallucination_incident(observed, reference) else None

    def _incident_candidate(self, workflow, current, state, observed):
        wid = workflow["workflow_id"]
        now = state["ts"]
        prompt = current["config"]["prompt_version"]
        if self.api.request("GET", "/sim/state").get("credits_remaining", 0) < 8:
            return None
        attempted = self.store.meta(f"incident_attempt:{wid}")
        if attempted and datetime.fromisoformat(now) - datetime.fromisoformat(attempted) < timedelta(hours=12):
            return None
        self.store.meta(f"incident_attempt:{wid}", now)
        self.store.journal(now, wid, "incident_detected", {"prompt": prompt, "observed": observed, "window_hours": 6})
        try:
            suggestions = self.api.request_once("POST", "/llm/suggest-fixes", json={"workflow_id": wid,
                "problem": f"Hallucination flags {observed[3]}/{observed[1]} connected calls in the last 6 hours on {prompt}"})["suggestions"]
        except httpx.HTTPError as exc:
            self.store.journal(now, wid, "incident_request_failed", {"stage": "suggest", "error": str(exc)})
            return None
        # Safety is necessary but not sufficient: avoid known near-verbatim scripts that can damage engagement.
        suggestions = [s for s in suggestions if s["prompt_version"] != prompt]
        suggestions.sort(key=lambda s: ("grounded" not in s["summary"].lower(),
                                         "strict" in s["summary"].lower()))
        for suggestion in suggestions[:2]:
            if self.api.request("GET", "/sim/state").get("credits_remaining", 0) < 5:
                break
            try:
                validation = self.api.request_once("POST", "/validation/runs", json={"workflow_id": wid,
                    "prompt_version": suggestion["prompt_version"], "n": 500})
            except httpx.HTTPError as exc:
                self.store.journal(now, wid, "incident_request_failed", {"stage": "validate", "error": str(exc)})
                break
            self.store.journal(now, wid, "validation", validation)
            if validation["pass_rate"] < workflow["governance"]["min_validation_pass_rate"]:
                continue
            changed = copy.deepcopy(current["config"])
            changed["prompt_version"] = suggestion["prompt_version"]
            return Candidate("prompt_version", changed,
                f"Validate and apply safer prompt {suggestion['prompt_version']}",
                f"Population signal: {observed[3]}/{observed[1]} QA flags in 6h; validation {validation['pass_rate']:.3f} on 500 synthetic conversations. Engagement will be monitored after apply.",
                {"window_hours": 6, "flagged": observed[3], "connected": observed[1],
                 "validation_pass_rate": validation["pass_rate"], "validation_n": 500},
                min(1.0, observed[3] / observed[1]), workflow["daily_batch"]["size"] * 2,
                {"validation_run_id": validation["validation_run_id"]})
        return None

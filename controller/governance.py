"""Crash-recoverable proposal and approval state machine."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import httpx


class Governance:
    def __init__(self, api, store):
        self.api, self.store = api, store

    def can_propose(self, workflow: dict, now: str, *, urgent: bool = False, candidate=None, current: dict | None = None) -> bool:
        if self.store.active_intent(workflow["workflow_id"]):
            return False
        previous = self.store.latest_intent_ts(workflow["workflow_id"])
        if previous and not urgent and datetime.fromisoformat(now) - datetime.fromisoformat(previous) < timedelta(hours=6):
            return False
        if candidate is not None and current is not None:
            candidate.dry_run.setdefault("previous_weights", current["config"].get("allocations", {}).get("default", {}).get(candidate.dimension))
        if self._auto_allowed(workflow, candidate):
            return True
        hour = datetime.fromisoformat(now).hour
        start, end = workflow["governance"]["approver_hours"]
        if workflow["workflow_id"].startswith("ks_"):
            start = max(start, 11)
        return start <= hour < end - 2

    def _auto_allowed(self, workflow: dict, candidate) -> bool:
        policy = workflow["governance"]["auto_apply"]
        if not policy["enabled"] or candidate is None or candidate.dimension not in policy["allowed_dims"]:
            return False
        if candidate.dimension in ("voice", "welcome_message", "caller_id"):
            before = candidate.dry_run.get("previous_weights")
            if before is None:
                return False
            after = candidate.config["allocations"]["default"][candidate.dimension]
            shift = sum(abs(after.get(k, 0) - before.get(k, 0)) for k in set(before) | set(after)) / 2
            return shift <= policy["max_shift"] + 1e-9
        return True

    def propose(self, workflow: dict, current: dict, candidate, now: str):
        wid = workflow["workflow_id"]
        if self.store.active_intent(wid):
            return
        before = current["config"].get("allocations", {}).get("default", {}).get(candidate.dimension)
        candidate.dry_run["previous_weights"] = before
        auto = self._auto_allowed(workflow, candidate)
        since = (datetime.fromisoformat(now) - timedelta(hours=24)).isoformat()
        if not auto and self.store.approval_count_since(wid, since) >= workflow["governance"]["max_requests_per_24h"]:
            return
        proposal_id = str(uuid.uuid4())
        body = {"proposal_id": proposal_id, "workflow_id": wid,
                "base_version": current["version"], "proposed_config": candidate.config,
                "change_summary": candidate.summary, "diff": {candidate.dimension: {"from": before, "to": candidate.config.get("allocations", {}).get("default", {}).get(candidate.dimension, candidate.config.get("prompt_version"))}},
                "affected_leads": candidate.affected_leads, "dry_run": candidate.dry_run,
                "impact_score": candidate.impact_score, "rationale": candidate.rationale}
        if candidate.evidence:
            body["evidence"] = candidate.evidence
        self.store.save_intent(proposal_id, wid, "auto" if auto else "approval", body, now)
        self.reconcile(wid, now)

    def reconcile(self, wid: str, now: str):
        intent = self.store.active_intent(wid)
        if not intent:
            return
        pid, body = intent["proposal_id"], intent["body"]
        if intent["kind"] == "auto":
            self._reconcile_auto(wid, intent, now)
            return
        approval_id = intent["approval_id"]
        if not approval_id:
            listed = self.api.request("GET", f"/approvals?workflow_id={wid}")
            found = next((x for x in listed if x.get("proposal_id") == pid), None)
            if found:
                approval_id = found["approval_id"]
                self.store.update_intent(pid, "pending", now, approval_id, {"recovered": True})
            else:
                try:
                    submitted = self.api.request("POST", "/approvals", json=body)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 409:
                        current = self.api.request("GET", f"/workflows/{wid}/config")
                        if current["version"] != body["base_version"]:
                            self.store.update_intent(pid, "stale", now, detail={"current_version": current["version"]})
                        return  # otherwise retry duplicate discovery next tick
                    self.store.update_intent(pid, "rejected", now, detail={"http_status": exc.response.status_code, "body": exc.response.text})
                    return
                approval_id = submitted["approval_id"]
                self.store.update_intent(pid, "pending", now, approval_id, submitted)
        approval = self.api.request("GET", f"/approvals/{approval_id}")
        status = approval["status"]
        if status == "pending":
            return
        if status in ("rejected", "expired", "lapsed"):
            self.store.update_intent(pid, status, now, detail=approval)
            return
        if status == "applied":
            self.store.update_intent(pid, "applied", now, detail=approval)
            return
        if status != "approved":
            return
        current = self.api.request("GET", f"/workflows/{wid}/config")
        if current["version"] != body["base_version"]:
            self.store.update_intent(pid, "stale", now, detail={"current_version": current["version"]})
            return
        try:
            applied = self.api.request("POST", f"/workflows/{wid}/apply", json={"approval_id": approval_id})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (409, 410):
                self.store.update_intent(pid, "stale" if exc.response.status_code == 409 else "lapsed", now,
                                         detail={"http_status": exc.response.status_code})
                return
            raise
        self.store.update_intent(pid, "applied", now, detail=applied)

    def _reconcile_auto(self, wid: str, intent: dict, now: str):
        pid, body = intent["proposal_id"], intent["body"]
        history = self.api.request("GET", f"/workflows/{wid}/config/history")
        if any(x.get("proposal_id") == pid for x in history):
            self.store.update_intent(pid, "applied", now, detail={"recovered": True})
            return
        current = self.api.request("GET", f"/workflows/{wid}/config")
        if current["version"] != body["base_version"]:
            self.store.update_intent(pid, "stale", now, detail={"current_version": current["version"]})
            return
        payload = {key: body[key] for key in ("proposal_id", "base_version", "proposed_config", "rationale")}
        if "evidence" in body:
            payload["evidence"] = body["evidence"]
        try:
            result = self.api.request("PUT", f"/workflows/{wid}/config", json=payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 409):
                self.store.update_intent(pid, "rejected", now, detail={"http_status": exc.response.status_code, "body": exc.response.text})
                return
            raise
        self.store.update_intent(pid, "applied", now, detail=result)

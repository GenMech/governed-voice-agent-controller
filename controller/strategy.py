"""Evidence-bound, workflow-local change candidates."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from .stats import beats, guardrail_safe, kpi_pair


@dataclass
class Candidate:
    dimension: str
    config: dict
    summary: str
    rationale: str
    dry_run: dict
    impact_score: float
    affected_leads: int
    evidence: dict | None = None


def _candidate(workflow, current, dimension, weights, summary, rationale, dry_run, score):
    changed = copy.deepcopy(current["config"])
    changed["allocations"]["default"][dimension] = weights
    return Candidate(dimension, changed, summary, rationale, dry_run,
                     min(1.0, max(0.0, score)), workflow["daily_batch"]["size"] * 2)


def choose_change(workflow: dict, current: dict, observations, now: str) -> Candidate | None:
    wid = workflow["workflow_id"]
    cfg = current["config"]
    version = current["version"]
    objective = workflow["objective"]
    primary = objective["primary"]
    guardrail = objective["guardrail"]

    # A caller ID is an operational risk for every workflow, whatever its primary KPI.
    cid_weights = cfg["allocations"]["default"]["caller_id"]
    recent = observations.variants(wid, "caller_id", since=_hours_ago(now, 24), cohort="default")
    active = [(cid, recent[cid]) for cid, weight in cid_weights.items() if weight > 0 and cid in recent]
    if len(active) >= 2:
        best = max(active, key=lambda item: item[1][1] / max(1, item[1][0]))
        worst = min(active, key=lambda item: item[1][1] / max(1, item[1][0]))
        if best[0] != worst[0] and beats((worst[1][0], worst[1][1]), (best[1][0], best[1][1]), minimum=200):
            engagement_limit = guardrail.get("engagement_rate_max_drop", 0.02)
            if not guardrail_safe((worst[1][1], worst[1][2]), (best[1][1], best[1][2]), engagement_limit):
                return None
            delta = min(0.2, cid_weights[worst[0]])
            weights = dict(cid_weights)
            weights[worst[0]] = round(weights[worst[0]] - delta, 4)
            weights[best[0]] = round(weights[best[0]] + delta, 4)
            if weights != cid_weights:
                gap = best[1][1] / best[1][0] - worst[1][1] / worst[1][0]
                return _candidate(workflow, current, "caller_id", weights,
                    f"Reduce use of degraded caller ID {worst[0]}",
                    f"Last 24h pickup: {worst[0]} {worst[1][1]}/{worst[1][0]}, {best[0]} {best[1][1]}/{best[1][0]}; pooled z >= 3.29.",
                    {"window_hours": 24, "control": worst[1][:2], "alternative": best[1][:2], "estimated_pickup_gain": round(gap * delta, 4)},
                    gap * delta)

    if primary != "engagement_rate":
        return None
    for dimension in ("voice", "welcome_message"):
        weights = cfg["allocations"]["default"][dimension]
        options = workflow["options"][dimension]
        all_rows = observations.variants(wid, dimension, cohort="default")
        live = [name for name, weight in weights.items() if weight > 0]
        if len(live) == 1:
            base = live[0]
            if all_rows.get(base, (0, 0, 0, 0))[1] < 200:
                return None
            untried = [name for name in options if name not in all_rows]
            if untried:
                challenger = untried[0]
                return _candidate(workflow, current, dimension, {base: 0.95, challenger: 0.05},
                    f"Test {dimension} {challenger} on 5% of calls",
                    f"Explore {challenger} against {base}; winner requires >=150 connected per arm and z >=3.29.",
                    {"baseline_connected": all_rows[base][1], "planned_test_share": 0.05, "historical_replay": "not causal"}, 0.05)
            continue
        if len(live) != 2:
            continue
        rows = observations.variants(wid, dimension, version=version, cohort="default")
        a, b = live
        if a not in rows or b not in rows:
            return None
        ra, rb = rows[a], rows[b]
        if min(ra[1], rb[1]) < 150:
            return None
        control = max(live, key=lambda name: weights[name])
        challenger = next(name for name in live if name != control)
        rc, rh = rows[control], rows[challenger]
        if not guardrail_safe((rc[0], rc[1]), (rh[0], rh[1]), guardrail["pickup_rate_max_drop"]) or beats(kpi_pair(rh, primary), kpi_pair(rc, primary)):
            return _candidate(workflow, current, dimension, {control: 1},
                f"Remove underperforming {dimension} {challenger}",
                f"Same-version comparison: {control} {rc[:3]}, {challenger} {rh[:3]}; primary or pickup guardrail failed.",
                {"version": version, "control": rc[:3], "challenger": rh[:3]}, 0.2)
        if not beats(kpi_pair(rc, primary), kpi_pair(rh, primary)):
            return None
        winner, loser = challenger, control
        rw, rl = rh, rc
        new_weights = {winner: 0.8, loser: 0.2}
        if weights == new_weights:
            continue
        lift = rw[2] / rw[1] - rl[2] / rl[1]
        return _candidate(workflow, current, dimension, new_weights,
            f"Promote {dimension} {winner} with 20% holdout",
            f"Same-version engagement {winner}: {rw[2]}/{rw[1]}; {loser}: {rl[2]}/{rl[1]}. Pickup guardrail passed.",
            {"version": version, "winner": rw[:3], "loser": rl[:3], "observed_engagement_lift": round(lift, 4)}, lift * 0.6)
    return None


def _hours_ago(ts: str, hours: int) -> str:
    from datetime import datetime, timedelta
    return (datetime.fromisoformat(ts) - timedelta(hours=hours)).isoformat()[:13]

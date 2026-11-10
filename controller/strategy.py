"""Evidence-bound, workflow-local change candidates."""

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
    recent = observations.variants(wid, "caller_id", since=_hours_ago(now, 24))
    active = [(cid, recent[cid]) for cid, weight in cid_weights.items() if weight > 0 and cid in recent]
    if len(active) >= 2:
        best = max(active, key=lambda item: item[1][1] / max(1, item[1][0]))
        worst = min(active, key=lambda item: item[1][1] / max(1, item[1][0]))
        if best[0] != worst[0] and beats((worst[1][0], worst[1][1]), (best[1][0], best[1][1]), minimum=200):
            delta = min(0.2, cid_weights[worst[0]])
            weights = dict(cid_weights)
            weights[worst[0]] = round(weights[worst[0]] - delta, 4)
            weights[best[0]] = round(weights[best[0]] + delta, 4)
            if weights != cid_weights:
                gap = best[1][1] / best[1][0] - worst[1][1] / worst[1][0]
                return _candidate(workflow, current, "caller_id", weights,
                    f"Reduce use of degraded caller ID {worst[0]}",
                    f"Last 24h pickup: {worst[0]} {worst[1][1]}/{worst[1][0]}, {best[0]} {best[1][1]}/{best[1][0]}; pooled z >= 2.58.",
                    {"window_hours": 24, "control": worst[1][:2], "alternative": best[1][:2], "estimated_pickup_gain": round(gap * delta, 4)},
                    gap * delta)

    if primary != "engagement_rate":
        return None
    for dimension in ("voice", "welcome_message"):
        weights = cfg["allocations"]["default"][dimension]
        options = workflow["options"][dimension]
        all_rows = observations.variants(wid, dimension)
        live = [name for name, weight in weights.items() if weight > 0]
        if len(live) == 1:
            base = live[0]
            if all_rows.get(base, (0, 0, 0, 0))[1] < 200:
                return None
            untried = [name for name in options if name not in all_rows]
            if untried:
                challenger = untried[0]
                return _candidate(workflow, current, dimension, {base: 0.8, challenger: 0.2},
                    f"Test {dimension} {challenger} on 20% of calls",
                    f"Explore {challenger} against {base}; winner requires >=150 connected per arm and z >=2.58.",
                    {"baseline_connected": all_rows[base][1], "planned_test_share": 0.2, "historical_replay": "not causal"}, 0.1)
            continue
        if len(live) != 2:
            continue
        rows = observations.variants(wid, dimension, version=version)
        a, b = live
        if a not in rows or b not in rows:
            return None
        ra, rb = rows[a], rows[b]
        if min(ra[1], rb[1]) < 150:
            return None
        winner, loser = (b, a) if beats(kpi_pair(ra, primary), kpi_pair(rb, primary)) else ((a, b) if beats(kpi_pair(rb, primary), kpi_pair(ra, primary)) else (None, None))
        if winner is None:
            return None
        rw, rl = rows[winner], rows[loser]
        # Pickup is the engagement workflow's guardrail.
        safe = guardrail_safe((rl[0], rl[1]), (rw[0], rw[1]), guardrail["pickup_rate_max_drop"])
        if not safe:
            return None
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

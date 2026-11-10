"""Deterministic tests over distinct KPI denominators."""

from __future__ import annotations

import math


def beats(control: tuple[int, int], challenger: tuple[int, int], *, minimum: int = 150, z_limit: float = 3.29) -> bool:
    """Two-sided pooled z test, requiring a positive challenger difference."""
    n0, x0 = control
    n1, x1 = challenger
    if min(n0, n1) < minimum:
        return False
    p0, p1 = x0 / n0, x1 / n1
    if p1 <= p0:
        return False
    pooled = (x0 + x1) / (n0 + n1)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n0 + 1 / n1))
    return se > 0 and (p1 - p0) / se >= z_limit


def guardrail_safe(control: tuple[int, int], challenger: tuple[int, int], max_drop: float) -> bool:
    n0, x0 = control
    n1, x1 = challenger
    return min(n0, n1) >= 150 and x1 / n1 >= x0 / n0 - max_drop


def kpi_pair(row: tuple[int, int, int, int], kpi: str) -> tuple[int, int]:
    dials, connected, engaged, _ = row
    return (dials, connected) if kpi == "pickup_rate" else (connected, engaged)


def hallucination_incident(row: tuple[int, int, int, int], reference: tuple[int, int, int, int] | None = None) -> bool:
    _, connected, _, flags = row
    if connected < 200 or flags < 10:
        return False
    if reference and reference[1] >= 300:
        old_rate = reference[3] / reference[1]
        return flags / connected >= old_rate + 0.02 and beats(
            (reference[1], reference[3]), (connected, flags), minimum=150)
    return flags / connected >= 0.06

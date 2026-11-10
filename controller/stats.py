"""Deterministic tests over distinct KPI denominators."""

import math


def beats(control: tuple[int, int], challenger: tuple[int, int], *, minimum: int = 150, z_limit: float = 2.58) -> bool:
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


def hallucination_incident(row: tuple[int, int, int, int]) -> bool:
    _, connected, _, flags = row
    return connected >= 150 and flags >= 15 and flags / connected >= 0.06

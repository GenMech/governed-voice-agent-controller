# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.345 | +1.0% | 0.246 | +0.6% | 0.494 | +0.3% | 0% | 64 (57) |
| nw_kyc | 0.370 | +1.0% | 0.243 | +0.5% | 0.599 | +0.4% | 0% | 19 (21) |
| nw_renewal | 0.414 | -0.5% | 0.264 | +0.1% | 0.539 | -0.5% | 0% | 52 (54) |
| ALL | 0.374 | +0.5% | 0.252 | +0.4% | 0.530 | +0.0% | 0% | 135 (132) |

## Changes applied by the controller

4 applied — neutral: 4

- ks_cancel v2 (controller_auto) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v3 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v4 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 4,
  "decisions": {
    "rejected": 1,
    "approved": 3,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 3,
  "auto_applied": 1,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 2
  }
}
```

## Incidents

```
[]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0
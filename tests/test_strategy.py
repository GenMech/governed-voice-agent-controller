from controller.stats import beats, guardrail_safe
from controller.strategy import choose_change


def test_winner_requires_sample_and_statistical_lift():
    assert not beats((100, 70), (100, 50), minimum=150)
    assert beats((500, 250), (500, 350), minimum=150)
    assert not beats((500, 250), (500, 260), minimum=150)


def test_guardrail_rejects_meaningful_pickup_loss():
    assert not guardrail_safe((1000, 400), (1000, 350), 0.02)
    assert guardrail_safe((1000, 400), (1000, 405), 0.02)


class Observations:
    def __init__(self, rows):
        self.rows = rows

    def variants(self, workflow, dimension, *, since="", version=None):
        return self.rows.get((dimension, version), self.rows.get((dimension, None), {}))


def workflow():
    return {"workflow_id": "w", "objective": {"primary": "engagement_rate", "guardrail": {"pickup_rate_max_drop": 0.02}},
            "options": {"voice": ["V1", "V2"], "welcome_message": ["W1", "W2"], "caller_id": ["D1", "D2"]},
            "daily_batch": {"size": 500}, "governance": {"auto_apply": {"enabled": False}}}


def config():
    return {"version": 1, "config": {"cohorts": [], "allocations": {"default": {
        "voice": {"V1": 1}, "welcome_message": {"W1": 1}, "caller_id": {"D1": 0.5, "D2": 0.5}}},
        "prompt_version": "P1", "schedule": {"hour_weights": {}, "lead_preferred_hour": {}}}}


def test_starts_small_voice_experiment_after_baseline_sample():
    obs = Observations({("voice", None): {"V1": (1000, 500, 250, 1)}})
    candidate = choose_change(workflow(), config(), obs, "2027-01-04T12:00:00+05:30")
    assert candidate.dimension == "voice"
    assert candidate.config["allocations"]["default"]["voice"] == {"V1": 0.8, "V2": 0.2}
    assert candidate.config["prompt_version"] == "P1"


def test_promotes_only_with_guardrail_respected():
    cfg = config()
    cfg["version"] = 2
    cfg["config"]["allocations"]["default"]["voice"] = {"V1": 0.8, "V2": 0.2}
    obs = Observations({("voice", 2): {"V1": (1000, 500, 250, 1), "V2": (300, 150, 120, 1)}})
    candidate = choose_change(workflow(), cfg, obs, "2027-01-05T12:00:00+05:30")
    assert candidate.dimension == "voice"
    assert candidate.config["allocations"]["default"]["voice"] == {"V1": 0.2, "V2": 0.8}

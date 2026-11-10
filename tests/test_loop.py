import json

from controller.loop import Controller
from controller.store import Store


class FakeApi:
    def __init__(self, end_minute=60):
        self.minute = 0
        self.end_minute = end_minute
        self.advance_calls = 0
        self.event = {"type": "call", "event_id": 1, "ts": "2027-01-04T10:00:00+05:30", "workflow_id": "w",
                      "config_version": 1, "cohort_id": "default", "variant": {"voice": "V1", "welcome_message": "W1", "caller_id": "D1", "prompt_version": "P1"},
                      "connected": True, "engaged": True, "qa": {"hallucination_flag": False}}

    def request(self, method, path, **kwargs):
        if path == "/sim/state":
            return {"sim_minute": self.minute, "finished": self.minute >= self.end_minute, "ts": "2027-01-04T11:00:00+05:30", "credits_remaining": 100}
        if path == "/workflows":
            return []
        if path.startswith("/events/chunks?"):
            return [{"chunk": 0}] if "after=-1" in path else []
        raise AssertionError((method, path))

    def lines(self, path):
        assert path == "/events/chunks/0"
        yield json.dumps(self.event)

    def advance(self, minutes, before_minute):
        self.advance_calls += 1
        self.minute += minutes
        return {"sim_minute": self.minute, "finished": self.minute >= self.end_minute}


def test_restart_recovers_chunk_before_advancing(tmp_path):
    api = FakeApi()
    api.minute = 60  # simulator advanced before controller's prior process died
    with Store(tmp_path / "state.sqlite") as store:
        Controller(api, store).run()
        assert store.last_chunk() == 0
        assert store.counts("w", "voice", "V1") == (1, 1, 1, 0)
        assert api.advance_calls == 0


def test_loop_refreshes_full_state_after_advance(tmp_path):
    api = FakeApi(end_minute=120)
    with Store(tmp_path / "state.sqlite") as store:
        Controller(api, store).run()
        assert api.advance_calls == 2
